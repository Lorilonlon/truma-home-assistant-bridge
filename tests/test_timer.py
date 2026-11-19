import asyncio
import copy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bridge.timer import (TIMER_CHARACTERISTICS, TIMER_WRITABLE, decode_enabled,
                          decode_times, encode_times, decode_timer, timer_write)
from bridge.protocol import CHARACTERISTICS, HEATER_SERVICE, encode_temperature
from bridge.main import Bridge
from bridge.bluez import BlueZ, GATT
from bridge.mqtt import MQTT
from test_bridge import FakeBackend


def fixture():
    # Synthetic protocol fixture, not a recorded successful timer write.
    return {'timer_enabled': b'\0', 'timer_time': bytes.fromhex('1e061408'),
            'timer_temperature': encode_temperature(19), 'timer_fan': b'\1\0',
            'timer_water': b'\0\0', 'timer_power': b'\0\0',
            'timer_water_power': b'\0\0', 'timer_energy': b'\1',
            'timer_water_energy': b'\1'}

class TimerBackend(FakeBackend):
    timer_writable = True
    def __init__(self):
        super().__init__()
        self.values.update(fixture())
    async def read_timer(self):
        return {k: await self.read(k) for k in TIMER_CHARACTERISTICS}

class TimerProtocolTests(unittest.TestCase):
    def test_byte_order_and_overnight(self):
        self.assertEqual(encode_times('06:30','08:20'),bytes.fromhex('1e061408'))
        self.assertEqual(decode_times(bytes.fromhex('3b170000')),('23:59','00:00'))
        for start,stop in [('00:00','23:59'),('22:15','06:45')]:
            self.assertEqual(decode_times(encode_times(start,stop)),(start,stop))
    def test_invalid_times(self):
        for v in ('24:00','12:60','2:00','02:00\n','02:00:00',None,123):
            with self.subTest(v=v),self.assertRaises(ValueError):encode_times(v,'08:00')
        for raw in (b'',b'\0'*3,b'\0'*5,bytes([60,0,0,1]),bytes([0,24,0,1])):
            with self.assertRaises(ValueError):decode_times(raw)
    def test_empty_flag_is_unknown_not_confirmed_off(self):
        self.assertIsNone(decode_enabled(b''))
        self.assertFalse(decode_enabled(b'\0'))
        self.assertTrue(decode_enabled(b'\1'))
        for raw in (b'\2',b'\xff',b'\1\0'):
            with self.assertRaises(ValueError):decode_enabled(raw)
    def test_synthetic_uninitialized_values(self):
        raw=fixture();raw.update(timer_enabled=b'',timer_time=b'\0'*4,timer_temperature=b'\0\0',timer_fan=b'\0\0')
        s=decode_timer(raw)
        self.assertIsNone(s['enabled']);self.assertEqual(s['start'],'00:00')
        self.assertEqual(timer_write('timer_enabled','OFF',s),('timer_enabled',b'\0'))
        with self.assertRaises(ValueError):timer_write('timer_enabled','ON',s)
        with self.assertRaises(ValueError):timer_write('timer_start','08:00',s)
    def test_edit_requires_off_and_never_enables(self):
        s=decode_timer(fixture())
        self.assertEqual(timer_write('timer_start','07:10',s),('timer_time',bytes.fromhex('0a071408')))
        for field,value in [('timer_temperature','22'),('timer_water','Hoch'),('timer_fan','High')]:
            self.assertNotEqual(timer_write(field,value,s)[0],'timer_enabled')
            with self.assertRaises(ValueError):timer_write(field,value,{**s,'enabled':True})
    def test_activation_validation(self):
        s=decode_timer(fixture())
        self.assertEqual(timer_write('timer_enabled','ON',s),('timer_enabled',b'\1'))
        for patch in ({'start':s['stop']},{'temperature':None},{'fan':'Aus'},
                      {'energy':2},{'power':900},{'water':'Unbekannt'}):
            with self.assertRaises(ValueError):timer_write('timer_enabled','ON',{**s,**patch})
        self.assertEqual(timer_write('timer_enabled','ON',{**s,'temperature':None,'water':'Hoch'})[1],b'\1')

class TimerBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.backend=TimerBackend()
        self.bridge=Bridge({'allow_control':True,'allow_timer_control':True},Path(self.tmp.name),self.backend)
        await self.bridge.snapshot()
    async def asyncTearDown(self):self.tmp.cleanup()
    async def test_poll_reflects_panel_changes_without_writes(self):
        self.backend.values.update(timer_time=encode_times('23:00','07:30'),timer_enabled=b'\1')
        await self.bridge.snapshot()
        self.assertEqual(self.bridge.timer['start'],'23:00');self.assertTrue(self.bridge.timer['enabled'])
        self.assertEqual(self.backend.writes,[])
    async def test_single_time_change_preserves_settings_and_main_heat(self):
        before=copy.deepcopy(self.backend.values)
        await self.bridge.command('timer_start','07:00',0)
        self.assertTrue(self.bridge.ready)
        self.assertEqual(self.backend.writes,[('timer_time',encode_times('07:00','08:20'))])
        for k,v in before.items():
            if k!='timer_time':self.assertEqual(self.backend.values[k],v)
        self.assertEqual(self.bridge.timer['start'],'07:00');self.assertFalse(self.bridge.timer['enabled'])
    async def test_active_edit_rejected(self):
        self.backend.values['timer_enabled']=b'\1'
        await self.bridge.command('timer_temperature','22',0)
        self.assertEqual(self.backend.writes,[])
        self.assertTrue(self.bridge.ready)
    async def test_invalid_timer_time_keeps_heating_available(self):
        await self.bridge.command('timer_start','25:00',0)
        self.assertEqual(self.backend.writes,[])
        self.assertTrue(self.bridge.ready)
    async def test_expired_queued_timer_does_not_mark_heater_disconnected(self):
        await self.bridge.command('timer_start','07:00',0,time.monotonic()-6)
        self.assertEqual(self.backend.writes,[])
        self.assertTrue(self.bridge.ready)
    async def test_default_option_and_read_only_block_commands(self):
        for patch in ({'allow_timer_control':False},{'allow_timer_control':True,'allow_control':False}):
            self.bridge.options.update(patch)
            await self.bridge.command('timer_enabled','ON',self.bridge.generation)
            self.assertEqual(self.backend.writes,[])
            await self.bridge.snapshot()
    async def test_unconfirmed_write_is_not_success(self):
        self.backend.mismatch=True
        await self.bridge.command('timer_start','07:00',0)
        self.assertIsNone(self.bridge.timer);self.assertIn('nicht bestätigt',self.bridge.error)
    async def test_timer_unavailable_keeps_heating_working(self):
        self.backend.read_timer=AsyncMock(side_effect=OSError('timer unavailable'))
        await self.bridge.snapshot()
        self.assertTrue(self.bridge.ready);self.assertIsNone(self.bridge.timer)
        await self.bridge.command('temperature','20',0)
        self.assertEqual(self.bridge.state['target'],20)
    async def test_missing_optional_timer_keeps_heating_working(self):
        self.backend.read_timer=AsyncMock(return_value=None)
        await self.bridge.snapshot()
        self.assertTrue(self.bridge.ready);self.assertIsNone(self.bridge.timer)
    async def test_panel_change_during_read_prevents_write(self):
        original=self.backend.read
        count=0
        async def read(k):
            nonlocal count
            if k=='timer_time':
                count+=1
                if count==2:return encode_times('08:00','09:00')
            return await original(k)
        self.backend.read=read
        await self.bridge.command('timer_start','07:00',0)
        self.assertEqual(self.backend.writes,[])
    async def test_panel_enable_just_before_edit_prevents_write(self):
        original=self.backend.read
        count=0
        async def read(k):
            nonlocal count
            if k=='timer_enabled':
                count+=1
                if count==2:return b'\1'
            return await original(k)
        self.backend.read=read
        await self.bridge.command('timer_start','07:00',0)
        self.assertEqual(self.backend.writes,[])
    async def test_panel_configuration_change_just_before_enable_prevents_write(self):
        first=fixture();changed={**first,'timer_energy':b'\2'}
        self.backend.read_timer=AsyncMock(side_effect=[first,first,changed])
        await self.bridge.command('timer_enabled','ON',0)
        self.assertEqual(self.backend.writes,[])
    async def test_expiry_generation_handover_stop_all_block(self):
        for patch in ('expiry','generation','handover','stop','restart'):
            await self.bridge.snapshot();self.bridge.paused_until=0;self.bridge.stopping=False;self.backend.restart_required=False
            generation=self.bridge.generation;arrived=time.monotonic()
            if patch=='expiry':arrived-=6
            elif patch=='generation':generation-=1
            elif patch=='handover':self.bridge.paused_until=time.monotonic()+30
            elif patch=='stop':self.bridge.stopping=True
            else:self.backend.restart_required=True
            await self.bridge.command('timer_enabled','ON',generation,arrived)
            self.assertEqual(self.backend.writes,[])
    async def test_expiry_during_snapshot_blocks_write(self):
        original=self.backend.read
        async def read(k):
            self.bridge.paused_until=time.monotonic()+30
            return await original(k)
        self.backend.read=read
        await self.bridge.command('timer_start','07:00',0)
        self.assertEqual(self.backend.writes,[])
        self.assertTrue(self.bridge.ready)
    async def test_explicit_off_works_with_unknown_flag_and_invalid_time(self):
        self.backend.values.update(timer_enabled=b'',timer_time=b'bad')
        await self.bridge.command('timer_enabled','OFF',0)
        self.assertEqual(self.backend.writes,[('timer_enabled',b'\0')])
        self.assertIsNone(self.bridge.timer)
    async def test_restart_does_not_replay(self):
        await self.bridge.command('timer_enabled','ON',0)
        self.backend.writes.clear()
        fresh=Bridge(self.bridge.options,Path(self.tmp.name),self.backend)
        await fresh.snapshot()
        self.assertTrue(fresh.timer['enabled']);self.assertEqual(self.backend.writes,[])

class TimerDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def objects(self,b):
        hs=b.device_path+'/heat';objects={hs:{'org.bluez.GattService1':{'UUID':HEATER_SERVICE}}}
        for name,uuid in {**CHARACTERISTICS,**TIMER_CHARACTERISTICS}.items():
            objects[hs+'/'+name]={GATT:{'UUID':uuid,'Service':hs,'Flags':['read','write']}}
        return objects,hs
    async def test_optional_complete_timer_discovery_and_write_allowlist(self):
        b=BlueZ({'adapter':'hci0','box_address':'00:11:22:33:44:55'});objects,hs=self.objects(b)
        b.objects=AsyncMock(return_value=objects);await b.discover();self.assertTrue(b.timer_writable)
        for k in ('timer_energy','timer_power','timer_water_energy','timer_water_power'):
            with self.assertRaises(ValueError):await b.write(k,b'\0')
        b.call=AsyncMock(return_value=[]);await b.write('timer_time',b'\0'*4)
        self.assertEqual(b.call.call_args.args[2],'WriteValue')
    async def test_missing_ambiguous_wrong_service_or_read_only(self):
        for problem in ('missing','duplicate','wrong_service','readonly'):
            b=BlueZ({'adapter':'hci0','box_address':'00:11:22:33:44:55'});objects,hs=self.objects(b)
            path=hs+'/timer_time'
            if problem=='missing':del objects[path]
            elif problem=='duplicate':objects[hs+'/duplicate']=copy.deepcopy(objects[path])
            elif problem=='wrong_service':objects[path][GATT]['Service']=b.device_path+'/other'
            else:objects[path][GATT]['Flags']=['read']
            b.objects=AsyncMock(return_value=objects);await b.discover()
            self.assertFalse(b.timer_writable);self.assertTrue(set(CHARACTERISTICS).issubset(b.paths))
            if problem!='readonly':self.assertIsNone(await b.read_timer())

class TimerMQTTTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_populates_valid_times_before_controls_become_available(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge({'allow_control':True,'allow_timer_control':True},Path(d),TimerBackend())
            await b.snapshot()
            m=MQTT(b,{'box_address':'00:11:22:33:44:55'})
            events=[];m.publish=lambda topic,payload,retain=True:events.append((topic,payload))
            b.ready=False;m.update()
            self.assertLess(events.index((m.base+'/timer/control','offline')),
                            next(i for i,(t,p) in enumerate(events) if t==m.base+'/timer/state'))
            events.clear();await b.snapshot();m.update()
            state_at=next(i for i,(t,p) in enumerate(events) if t==m.base+'/timer/state')
            self.assertEqual(events[state_at][1]['start'],'06:30')
            self.assertLess(state_at,events.index((m.base+'/timer/control','online')))
    async def test_discovery_has_confirmed_state_and_nonretained_commands(self):
        with tempfile.TemporaryDirectory() as d:
            b=Bridge({'allow_control':True,'allow_timer_control':True},Path(d),TimerBackend())
            await b.snapshot()
            m=MQTT(b,{'box_address':'00:11:22:33:44:55'});published={}
            m.publish=lambda topic,payload,retain=True:published.__setitem__(topic,payload)
            m.announce()
            configs={k:v for k,v in published.items() if k.endswith('/config') and '/timer' in k}
            self.assertEqual(len(configs),8)
            for c in configs.values():
                self.assertIn('default_entity_id',c)
                if 'command_topic' in c and 'payload_press' not in c:
                    self.assertFalse(c['optimistic']);self.assertFalse(c.get('retain',False))
            self.assertEqual(published[m.base+'/timer/control'],'online')
            b.timer=None;m.update()
            self.assertEqual(published[m.base+'/timer/control'],'offline')
            self.assertEqual(published[m.base+'/timer/stop'],'online')
            b.ready=False;m.update()
            self.assertEqual(published[m.base+'/timer/available'],'offline')
            self.assertEqual(published[m.base+'/timer/control'],'offline')
    async def test_retained_timer_command_rejected(self):
        scheduled=[];b=SimpleNamespace(generation=0,schedule_command=lambda *x:scheduled.append(x))
        m=MQTT(b,{'box_address':'00:11:22:33:44:55'})
        m.on_message(None,None,SimpleNamespace(topic=m.base+'/set/timer_enabled',payload=b'ON',retain=True))
        await asyncio.sleep(0);self.assertEqual(scheduled,[])
