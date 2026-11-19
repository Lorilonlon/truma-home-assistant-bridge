import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from bridge.faults import FaultJournal, decode_fault, FAULT_SERVICES, FAULT_CHARACTERISTIC
from bridge.bluez import BlueZ, GATT
from bridge.protocol import CHARACTERISTICS, HEATER_SERVICE
from bridge.main import Bridge
from test_bridge import FakeBackend


class FaultTests(unittest.TestCase):
    def test_original_format_and_unknown_level(self):
        for raw in (b'', b'\0', b'\0' * 20):
            self.assertIsNone(decode_fault(raw))
        self.assertEqual(decode_fault(b'\x01W 001 H\0\0')['severity'], 'warning')
        self.assertEqual(decode_fault(b'\x02E 999 H\0')['code'], 'E 999 H')
        self.assertEqual(decode_fault(b'\x07EXAMPLE')['severity'], 'unknown')
        self.assertEqual(decode_fault(b'\x02')['code'], 'Code nicht angegeben')
        for raw in (b'\x02E\0evil', b'\x02E\nX', b'x'*513):
            with self.assertRaises(ValueError): decode_fault(raw)

    def test_dedup_restart_stale_seen_recovery_recurrence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'faults.json'
            j = FaultJournal(path)
            bad = {'heater': {'status':'ok', 'fault':decode_fault(b'\x02EXAMPLE')}}
            j.update(bad)
            event = j.event['id']
            j.update(bad)
            self.assertEqual(j.event['id'], event)
            j.mark_seen()
            self.assertEqual(j.event['id'], event)
            self.assertTrue(j.active['heater']['seen'])
            j = FaultJournal(path)
            self.assertTrue(j.view(True)['active'][0]['stale'])
            j.update({'heater': {'status':'unavailable','fault':None}})
            self.assertEqual(j.event['id'], event)
            self.assertIn('heater', j.active)
            j.update(bad)
            self.assertEqual(j.event['id'], event)
            j.update({'heater': {'status':'ok', 'fault':None}})
            self.assertNotEqual(j.event['id'], event)
            self.assertFalse(j.active)
            self.assertEqual(j.view(True)['summary'], 'Keine gemeldete Störung')
            self.assertEqual(j.view(False)['summary'], 'Fehlerstatus unbekannt')
            j.update(bad)
            self.assertIsNone(j.active['heater']['seen'])

    def test_command_failure_is_not_cleared_by_poll_and_history_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            j = FaultJournal(Path(d)/'faults.json')
            j.command_failed('Nicht bestätigt')
            event = j.event['id']
            j.command_failed('Nicht bestätigt')
            self.assertEqual(j.event['id'], event)
            j.update({'heater': {'status':'ok', 'fault':None}})
            self.assertIn('command', j.active)
            j.mark_seen()
            self.assertNotIn('command', j.active)
            for i in range(50): j.command_failed(str(i))
            self.assertEqual(len(j.history),30)
            self.assertFalse(j.view(True)['reset_supported'])


class FaultBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_scoped_discovery_and_no_reset_write(self):
        b = BlueZ({'adapter':'hci0','box_address':'00:11:22:33:44:55'})
        hs, ps = b.device_path+'/heat', b.device_path+'/panel'
        objects = {hs:{'org.bluez.GattService1':{'UUID':HEATER_SERVICE}},
                   ps:{'org.bluez.GattService1':{'UUID':FAULT_SERVICES['panel']}}}
        for kind, uuid in CHARACTERISTICS.items():
            objects[hs+'/'+kind] = {GATT:{'UUID':uuid,'Service':hs,'Flags':['read']}}
        for service in (hs,ps):
            objects[service+'/fault'] = {GATT:{'UUID':FAULT_CHARACTERISTIC,'Service':service,'Flags':['read','write']}}
        b.objects = AsyncMock(return_value=objects)
        await b.discover()
        self.assertEqual(b.paths['fault_heater'],hs+'/fault')
        self.assertEqual(b.paths['fault_panel'],ps+'/fault')
        for key in ('fault_heater','fault_panel','reset'):
            with self.assertRaises(ValueError): await b.write(key,b'\0')
        b.read = AsyncMock(side_effect=[b'\0', OSError('gone')])
        result = await b.read_faults()
        self.assertEqual(result['panel']['status'],'ok')
        self.assertEqual(result['heater']['status'],'unavailable')
        self.assertEqual(result['ac1']['status'],'unsupported')

    async def test_read_failure_does_not_break_heating_and_seen_is_local(self):
        with tempfile.TemporaryDirectory() as d:
            backend = FakeBackend()
            backend.read_faults = AsyncMock(side_effect=OSError('fault read failed'))
            b = Bridge({'allow_control':True},Path(d),backend)
            await b.snapshot()
            self.assertTrue(b.ready)
            self.assertFalse(b.faults.view(True)['fresh'])
            b.faults.command_failed('EXAMPLE')
            b.options['allow_control'] = False
            await b.command('fault_seen','seen',b.generation)
            self.assertEqual(backend.writes,[])
            self.assertFalse(b.faults.active)
