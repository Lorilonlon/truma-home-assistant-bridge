import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from bridge.main import Bridge, create_web
from bridge.mqtt import MQTT
from bridge.bluez import Agent, BlueZ, GATT, HEATER_SERVICE, CHARACTERISTICS
from dbus_next import DBusError
from aiohttp.test_utils import TestClient, TestServer
from test_bridge import FakeBackend

class CommandResilience(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.bridge = Bridge({'allow_control':True},Path(self.tmp.name),self.backend)
        await self.bridge.snapshot()
    async def asyncTearDown(self):
        self.tmp.cleanup()
    async def test_expiry_during_read_blocks_write(self):
        clock = [time.monotonic()]
        original = self.backend.read
        async def slow_read(k):
            clock[0] += 5
            return await original(k)
        self.backend.read = slow_read
        with patch('bridge.main.time.monotonic',side_effect=lambda:clock[0]):
            await self.bridge.command('temperature','25',0,clock[0])
        self.assertEqual(self.backend.writes,[])
        self.assertFalse(self.bridge.ready)
    async def test_slow_validation_after_poll_wait_is_accepted(self):
        # Regression: a timely command must survive >3 s of necessary reads.
        # Simulate 4 s queue age and 1.1 s per read (7.7 s transaction total).
        clock = [time.monotonic()]
        original = self.backend.read
        async def slow_read(k):
            clock[0] += 1.1
            return await original(k)
        self.backend.read = slow_read
        with patch('bridge.main.time.monotonic',side_effect=lambda:clock[0]):
            await self.bridge.command('temperature','19',0,clock[0]-4)
        self.assertTrue(self.bridge.ready)
        self.assertEqual(self.bridge.state['target'],19)
        self.assertEqual(len(self.backend.writes),1)
        self.assertFalse(self.bridge.faults.active)

    async def test_generation_changes_during_slow_validation_still_block(self):
        original = self.backend.read
        async def changed(k):
            self.bridge.generation += 1
            return await original(k)
        self.backend.read = changed
        await self.bridge.command('temperature','19',0)
        self.assertEqual(self.backend.writes,[])
        self.assertFalse(self.bridge.ready)

    async def test_hung_read_times_out_and_releases_lock(self):
        async def hung(k):
            await asyncio.Event().wait()
        self.backend.read = hung
        with patch('bridge.main.COMMAND_EXECUTION_SECONDS',0.03):
            await asyncio.wait_for(self.bridge.command('temperature','19',0),1)
        self.assertEqual(self.backend.writes,[])
        self.assertFalse(self.bridge.lock.locked())
        self.assertFalse(self.bridge.ready)
        self.assertIn('Zeitlimit',self.bridge.error)

    async def test_expired_wait_behind_poll_does_not_run_later(self):
        await self.bridge.lock.acquire()
        try:
            with patch('bridge.main.COMMAND_QUEUE_SECONDS',0.03):
                await asyncio.wait_for(self.bridge.command('temperature','19',0),1)
            self.assertEqual(self.backend.writes,[])
            self.assertTrue(self.bridge.ready)
            self.assertEqual(self.bridge.generation,0)
        finally:
            self.bridge.lock.release()
        await asyncio.sleep(0)
        self.assertEqual(self.backend.writes,[])

    async def test_timeout_after_write_is_not_retried(self):
        original = self.backend.read
        async def lose_reply(k):
            if self.backend.writes:
                await asyncio.Event().wait()
            return await original(k)
        self.backend.read = lose_reply
        with patch('bridge.main.COMMAND_EXECUTION_SECONDS',0.03):
            await asyncio.wait_for(self.bridge.command('temperature','21',0),1)
        self.assertEqual(len(self.backend.writes),1)
        self.assertFalse(self.bridge.ready)
        self.assertNotEqual(self.bridge.state['target'],21)

    async def test_expiry_between_two_writes_stops_remaining_steps(self):
        clock = [time.monotonic()]
        original = self.backend.write
        async def slow_write(k,payload):
            await original(k,payload)
            clock[0] += 13
        self.backend.write = slow_write
        with patch('bridge.main.time.monotonic',side_effect=lambda:clock[0]):
            await self.bridge.command('mode','off',0,clock[0])
        self.assertEqual(self.backend.writes,[('fan',b'\0')])
        self.assertFalse(self.bridge.ready)
    async def test_daemon_restart_during_read_blocks_write(self):
        original=self.backend.read
        async def changed(k):
            self.backend.restart_required=True
            return await original(k)
        self.backend.read=changed
        await self.bridge.command('mode','heat',0)
        self.assertEqual(self.backend.writes,[])
    async def test_shutdown_blocks_commands(self):
        self.bridge.stopping=True
        await self.bridge.command('temperature','25',0)
        self.assertEqual(self.backend.writes,[])
    async def test_handover_blocks_commands(self):
        self.bridge.paused_until=time.monotonic()+300
        await self.bridge.command('temperature','25',0)
        self.assertEqual(self.backend.writes,[])
    async def test_corrupted_saved_target_is_ignored(self):
        (Path(self.tmp.name)/'last-target.json').write_text('{bad')
        again=Bridge({'allow_control':True},Path(self.tmp.name),self.backend)
        self.assertIsNone(again.last_target)
    async def test_failed_preset_save_never_writes_hardware(self):
        self.backend.values['temperature']=b'\0\0'
        with patch.object(self.bridge,'remember_target',side_effect=OSError('disk full')):
            await self.bridge.command('temperature','24',0)
        self.assertEqual(self.backend.writes,[])
        self.assertFalse(self.bridge.ready)
    async def test_partial_snapshot_keeps_previous_complete_state(self):
        old=dict(self.bridge.state)
        original=self.backend.read
        async def partial(k):
            if k=='water':raise OSError('lost link')
            return await original(k)
        self.backend.read=partial
        await self.bridge.command('temperature','24',0)
        self.assertEqual(self.bridge.state,old)
        self.assertEqual(self.backend.writes,[])
    async def test_rapid_presets_then_explicit_heat(self):
        self.backend.values['temperature']=b'\0\0'
        for value in ('21','22','23'):
            self.bridge.schedule_command('temperature',value,0)
        await asyncio.gather(*self.bridge.command_tasks)
        self.assertEqual(self.backend.writes,[])
        self.assertEqual(self.bridge.state['target'],23)
        await self.bridge.command('mode','heat',0)
        self.assertEqual(self.bridge.state['target'],23)
        self.assertEqual(self.bridge.state['mode'],'heat')

class TransportResilience(unittest.IsolatedAsyncioTestCase):
    async def test_publish_failure_is_retryable(self):
        transport=MQTT(SimpleNamespace(),{'box_address':'00:11:22:33:44:55'})
        calls=[]
        def publish(*args,**kwargs):
            calls.append(args)
            return SimpleNamespace(rc=4 if len(calls)==1 else 0)
        transport.client=SimpleNamespace(publish=publish)
        transport.connected=True
        transport.publish('status','online')
        transport.publish('status','online')
        transport.publish('status','online')
        self.assertEqual(len(calls),2)
    async def test_malformed_and_oversized_mqtt_are_ignored(self):
        calls=[]
        transport=MQTT(SimpleNamespace(generation=1,schedule_command=lambda *x:calls.append(x)),{'box_address':'00:11:22:33:44:55'})
        for payload in (b'\xff',b'a'*129):
            transport.on_message(None,None,SimpleNamespace(topic=transport.base+'/set/temperature',payload=payload,retain=False))
        await asyncio.sleep(0)
        self.assertEqual(calls,[])
    async def test_pairing_is_target_and_time_restricted(self):
        backend=BlueZ({'adapter':'hci0','box_address':'00:11:22:33:44:55'})
        agent=Agent(backend)
        with self.assertRaises(DBusError):agent.check(backend.device_path)
        backend.pair_until=time.monotonic()+60
        with self.assertRaises(DBusError):agent.check('/org/bluez/hci0/dev_OTHER')
        agent.check(backend.device_path)
    async def test_duplicate_characteristic_rejected(self):
        backend=BlueZ({'adapter':'hci0','box_address':'00:11:22:33:44:55'})
        service=backend.device_path+'/service01'
        objects={service:{'org.bluez.GattService1':{'UUID':HEATER_SERVICE}}}
        for n in (1,2):
            objects[service+f'/char{n}']={GATT:{'UUID':CHARACTERISTICS['temperature'],'Service':service,'Flags':['read','write']}}
        async def get_objects():return objects
        backend.objects=get_objects
        with self.assertRaisesRegex(RuntimeError,'Mehrdeutige'):
            await backend.discover()
    async def test_ingress_denies_direct_requests(self):
        async with TestClient(TestServer(create_web(SimpleNamespace()))) as client:
            for path in ('/','/api/status','/api/diagnostics'):
                response=await client.get(path)
                self.assertEqual(response.status,403)
            response=await client.post('/api/pair',headers={'X-Truma-Action':'1'})
            self.assertEqual(response.status,403)
