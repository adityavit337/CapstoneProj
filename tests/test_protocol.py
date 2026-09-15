import json
import unittest
from indoor_ble.protocol import parse_packet, Deduplicator
from tests.helpers import config, packet, wire


class ProtocolTests(unittest.TestCase):
    def setUp(self): self.cfg=config()

    def test_valid_channel_and_baseline(self):
        for ch,mask in ((0,7),(37,1),(38,2),(39,4)):
            self.assertEqual(parse_packet(wire(channel=ch,channel_mask=mask),self.cfg)["channel"],ch)

    def test_reject_payload_label_without_matching_mask(self):
        with self.assertRaises(ValueError): parse_packet(wire(channel=37,channel_mask=7),self.cfg)

    def test_reject_malformed_truncated_oversized(self):
        for raw in (b'{',b'[]',b'null',b'\xff',b'x'*1025):
            with self.subTest(raw=raw[:10]),self.assertRaises(ValueError): parse_packet(raw,self.cfg)

    def test_required_fields_types_and_ranges(self):
        cases={"rssi":[0,-128,"-65",float('nan'),True],"seq":[-1,2**32,False],"channel":[36,40,True],
               "tx_dbm":[21,-31],"tx_id":[101],"v":[2,True],"anchor":["D"],"simulated":["false",True]}
        for key,values in cases.items():
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError): parse_packet(wire(**{key:value}),self.cfg)
        p=packet(); del p['tx_boot']
        with self.assertRaises(ValueError): parse_packet(json.dumps(p).encode(),self.cfg)

    def test_simulation_is_explicit_and_cannot_enter_hardware(self):
        p=parse_packet(wire(simulated=True),self.cfg,simulated=True)
        self.assertTrue(p['simulated'])
        with self.assertRaises(ValueError): parse_packet(wire(),self.cfg,simulated=True)

    def test_reference_identity(self):
        self.assertEqual(parse_packet(wire(kind='reference',tx_id=2),self.cfg)['tx_id'],2)
        with self.assertRaises(ValueError): parse_packet(wire(kind='reference',tx_id=1),self.cfg)

    def test_heartbeat(self):
        p={'v':1,'type':'heartbeat','simulated':False,'anchor':'C','anchor_boot':1,'uptime_ms':3,'queue_drops':8}
        self.assertEqual(parse_packet(json.dumps(p).encode(),self.cfg)['queue_drops'],8)


class DedupTests(unittest.TestCase):
    def test_burst_identity_channels_and_reboots(self):
        d=Deduplicator(); p=packet()
        self.assertTrue(d.accept(p,0)); self.assertFalse(d.accept(p,1))
        for change in ({'channel':38},{'anchor':'B'},{'tx_boot':3},{'anchor_boot':4}):
            self.assertTrue(d.accept({**p,**change},2))
        self.assertEqual(d.duplicates,1)

    def test_wrap_gaps_late_and_reorder(self):
        d=Deduplicator()
        for t,s in enumerate((0xfffffffe,0xffffffff,0,3,1,2)):
            self.assertTrue(d.accept(packet(seq=s),t))
        self.assertEqual(d.gap_events,2); self.assertEqual(d.late,2)
        self.assertFalse(d.accept(packet(seq=1),10))

    def test_bounds_and_ttl(self):
        d=Deduplicator(ttl=2,max_entries=3)
        for i in range(10): d.accept(packet(seq=i),i/10)
        self.assertEqual(len(d.seen),3)
        self.assertTrue(d.accept(packet(seq=9),5))
        self.assertEqual(len(d.seen),1)
