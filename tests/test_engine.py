import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from indoor_ble.engine import Engine
from indoor_ble.calibration import ReferenceFitter
from indoor_ble.simulation import Simulator, replay_packets
from tests.helpers import config, packet, wire


class EngineTests(unittest.TestCase):
    def feed_position(self,e,channel=0,mask=7):
        truth=(2.5,2)
        for seq in range(4):
            for name,a in e.cfg['anchors'].items():
                r=round(-59-22*math.log10(math.dist(truth,(a['x'],a['y']))))
                e.ingest(wire(anchor=name,rssi=r,channel=channel,channel_mask=mask,seq=seq),10+seq*.1)
        return truth

    def test_baseline_position_and_staleness(self):
        e=Engine(config());truth=self.feed_position(e)
        pos=e.estimate(11)['baseline']
        self.assertLess(math.dist((pos['x'],pos['y']),truth),.4)
        self.assertIsNone(e.result['advanced'])
        self.assertIsNone(e.estimate(20)['baseline'])
        self.assertFalse(e.snapshot(20)['anchors']['A']['online'])

    def test_all_channels_required_and_repeats_do_not_create_samples(self):
        e=Engine(config())
        for _ in range(10): e.ingest(wire(),1)
        self.assertEqual(len(e.samples[('A',37)]),1)
        self.feed_position(e,37,1);self.feed_position(e,38,2)
        self.assertIsNone(e.estimate(11)['advanced'])
        self.feed_position(e,39,4)
        self.assertIsNotNone(e.estimate(11.5)['advanced'])
        self.assertIsNotNone(e.result['tracked'])

    def test_missing_anchor_never_gives_origin_position(self):
        e=Engine(config())
        for s in range(3):e.ingest(wire(seq=s),s)
        self.assertIsNone(e.estimate(3)['baseline'])

    def test_bad_packets_do_not_kill_receiver(self):
        e=Engine(config())
        for bad in (b'{}',b'NaN',b'{"anchor":[]}'):
            self.assertIsNone(e.ingest(bad))
        self.assertEqual(e.stats['rejected'],3)

    def test_logs_include_raw_duplicates_and_manual_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            e=Engine(config(),temp);truth=self.feed_position(e)
            e.ingest(wire(anchor='A',channel=0,channel_mask=7,seq=0),10.5)
            e.estimate(11); row=e.set_truth(*truth,note='floor mark 1',now=11)
            self.assertLess(row['baseline_error_m'],.4)
            e.close()
            with (Path(temp)/'observations.csv').open(newline='') as f: observations=list(csv.DictReader(f))
            self.assertEqual(len(observations),13)
            self.assertEqual(observations[-1]['accepted'],'False')
            for name in ('positions.csv','ground_truth.csv'):self.assertTrue((Path(temp)/name).exists())

    def test_simulation_produces_comparable_results(self):
        e=Engine(config(),simulated=True);s=Simulator(e.cfg)
        for i in range(20):s.step(e,100+i*.5,i*.5);e.estimate(100+i*.5)
        self.assertTrue(e.snapshot(110)['simulated'])
        self.assertIsNotNone(e.result['baseline']);self.assertIsNotNone(e.result['advanced'])
        self.assertGreater(e.dedup.duplicates,0)
        self.assertTrue(all(m.get('spatial_residual_dof')==0 for m in e.result['reference_models'].values()))


class ReferenceTests(unittest.TestCase):
    def fill(self,f,now=1):
        cfg=f.cfg
        for rx,a in cfg['anchors'].items():
            for tx,b in cfg['anchors'].items():
                if rx==tx:continue
                d=math.dist((a['x'],a['y']),(b['x'],b['y']))
                for _ in range(10): f.add(packet(anchor=rx,kind='reference',tx_id=b['wire_id'],rssi=-59-22*math.log10(d)),now)

    def test_two_distances_fit_but_cannot_validate(self):
        f=ReferenceFitter(config()); self.fill(f)
        model=f.models(2)['A:37']
        self.assertEqual(model['independent_distances'],2);self.assertEqual(model['spatial_residual_dof'],0)
        self.assertAlmostEqual(model['n'],2.2);self.assertAlmostEqual(model['intercept'],-59)
        self.assertFalse(model['normalized_transmitters'])

    def test_reference_model_expires(self):
        f=ReferenceFitter(config());self.fill(f)
        self.assertEqual(f.models(300)['A:37']['status'],'insufficient links')

    def test_replicates_of_one_link_not_independent_distances(self):
        f=ReferenceFitter(config())
        for _ in range(100): f.add(packet(kind='reference',tx_id=2),1)
        self.assertEqual(f.models(2)['A:37']['independent_distances'],1)

    def test_power_change_invalidates_mixed_link(self):
        f=ReferenceFitter(config());self.fill(f)
        f.add(packet(kind='reference',tx_id=2,tx_dbm=3),1)
        self.assertEqual(f.models(2)['A:37']['independent_distances'],1)
