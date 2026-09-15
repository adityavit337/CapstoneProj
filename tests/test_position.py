import copy
import math
import unittest
from indoor_ble.config import validate_config
from indoor_ble.position import distance_from_rssi, filtered_rssi, channel_distance, fuse_distances, trilaterate, AxisKalman
from tests.helpers import config


class PositionTests(unittest.TestCase):
    def test_path_loss_known_distances(self):
        for d in (.5,1,2,5,10):
            r=-59-22*math.log10(d)
            self.assertAlmostEqual(distance_from_rssi(r),d,places=10)

    def test_exact_trilateration_many_points(self):
        anchors=[(.5,.5),(5.5,.5),(1,4.5)]
        for x in (0.3,1,2,4,5.7):
            for y in (.2,1.5,3,4.8):
                result=trilaterate(anchors,[math.dist((x,y),a) for a in anchors],bounds=(6,5))
                self.assertLess(math.hypot(result['x']-x,result['y']-y),.001)

    def test_reject_collinear_and_invalid_ranges(self):
        with self.assertRaises(ValueError): trilaterate([(0,0),(1,1),(2,2)],[1,2,3])
        with self.assertRaises(ValueError): trilaterate([(0,0),(1,0),(0,1)],[1,float('nan'),3])

    def test_noisy_anchor_downweighted(self):
        anchors=[(0,0),(6,0),(0,5),(6,5)]; truth=(2,2)
        distances=[math.dist(truth,a) for a in anchors]; distances[3]+=4
        naive=trilaterate(anchors,distances,bounds=(6,5))
        weighted=trilaterate(anchors,distances,[.1,.1,.1,100],(6,5))
        error=lambda p:math.hypot(p['x']-2,p['y']-2)
        self.assertLess(error(weighted),error(naive)/5)

    def test_fusion_accounts_for_variance_and_disagreement(self):
        d,v=fuse_distances([(2,.1),(8,10)])
        self.assertLess(abs(d-2),.1); self.assertGreater(v,.1)

    def test_filter_rejects_single_rssi_outlier(self):
        mean,var=filtered_rssi([-60,-61,-59,-60,-100])
        self.assertAlmostEqual(mean,-60); self.assertGreaterEqual(var,4)

    def test_distance_uncertainty_grows_with_range(self):
        near=channel_distance(-59,4,-59,2.2)
        far=channel_distance(-81,4,-59,2.2)
        self.assertGreater(far[1],near[1]*50)

    def test_kalman_tracks_velocity_and_stays_finite(self):
        k=AxisKalman(0)
        for i in range(1,50): value=k.update(i*.2,.2,.1,.1)
        self.assertLess(abs(value-9.8),.1); self.assertGreater(k.p00,0)
        self.assertTrue(math.isfinite(k.update(100,.2,.1,.1)))

    def test_geometry_and_identifiability_config(self):
        cfg=config(); validate_config(cfg)
        cfg['anchors']['C'].update(x=2,y=.5)
        with self.assertRaises(ValueError): validate_config(cfg)
        cfg=config(); cfg['anchors']['C'].update(x=.5,y=5.5); cfg['room']['height']=6
        with self.assertRaises(ValueError): validate_config(cfg) # equal reference distances

    def test_no_implicit_transfer_of_reference_model(self):
        cfg=config();cfg['calibration']['apply_to_tag']=True
        with self.assertRaises(ValueError):validate_config(cfg)
