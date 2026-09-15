import json
import math
import unittest
import urllib.error
import urllib.request

from indoor_ble.server import Application
from indoor_ble.survey import calculate_survey
from tests.helpers import config


def survey():
    # Synthetic analytical fixture, never inserted into the demo UI.
    return dict(reference=-59, exponent=2, width=6, height=5,
                points=[dict(x=x, y=y, rssi=-59-20*math.log10(math.hypot(x-2, y-2)))
                        for x, y in [(0, 0), (6, 0), (0, 5), (6, 5)]])


class SurveyTests(unittest.TestCase):
    def test_recovers_known_stationary_tag_and_one_metre_range(self):
        p = survey()
        result = calculate_survey(p)
        self.assertAlmostEqual(result['position']['x'], 2, places=4)
        self.assertAlmostEqual(result['position']['y'], 2, places=4)
        p['points'] = [dict(x=0, y=0, rssi=-59)]
        result = calculate_survey(p)
        self.assertEqual(result['points'][0]['distance'], 1)
        self.assertIsNone(result['position'])

    def test_bad_geometry_keeps_distances_but_never_claims_position(self):
        p = survey()
        p['points'] = [dict(x=x, y=0, rssi=-65) for x in [0, 1, 2]]
        self.assertIsNone(calculate_survey(p)['position'])
        p['points'][2]['x'] = 1
        self.assertIsNone(calculate_survey(p)['position'])

    def test_rejects_missing_calibration_nonfinite_and_outside_room(self):
        for field, value in [('reference', None), ('reference', float('nan')),
                             ('exponent', 0), ('width', True), ('points', [])]:
            with self.subTest(field=field, value=value):
                p = survey(); p[field] = value
                with self.assertRaises(ValueError): calculate_survey(p)
        p = survey(); p['points'][0]['x'] = 7
        with self.assertRaises(ValueError): calculate_survey(p)

    def test_manual_http_mode_and_calculation(self):
        cfg = config(); cfg['network']['http_port'] = 0
        app = Application(cfg, manual=True)
        try:
            app.start(udp=False)
            self.assertIsNone(app.udp)
            url = f'http://127.0.0.1:{app.http.server_port}'
            with urllib.request.urlopen(url) as r:
                self.assertIn(b'SEQUENTIAL SURVEY', r.read())
            req = urllib.request.Request(url+'/api/survey', data=json.dumps(survey()).encode(),
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as r:
                self.assertAlmostEqual(json.load(r)['position']['x'], 2, places=4)
            req.data = b'[]'
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req)
            self.assertEqual(err.exception.code, 400)
            err.exception.close()
        finally:
            app.close()
