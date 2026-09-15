import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from indoor_ble.server import Application
from tests.helpers import config, wire


class ServerTests(unittest.TestCase):
    def setUp(self):
        cfg=config();cfg['network'].update(udp_host='127.0.0.1',udp_port=0,http_port=0)
        self.app=Application(cfg);self.app.start()
        self.url=f'http://127.0.0.1:{self.app.http.server_port}'

    def tearDown(self):self.app.close()

    def test_real_udp_receiver_http_dashboard_and_sync_reply(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            addr=self.app.udp.server_address
            s.sendto(b'{bad',addr);s.sendto(wire(),addr)
            heartbeat={'v':1,'type':'heartbeat','simulated':False,'anchor':'B','anchor_boot':4,'uptime_ms':333,'queue_drops':0}
            s.sendto(json.dumps(heartbeat).encode(),addr)
            reply,_=s.recvfrom(1024);self.assertTrue(reply.startswith(b'SYNC1 333 '))
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with urllib.request.urlopen(self.url+'/api/state') as r:state=json.load(r)
            if state['stats']['accepted']==1 and state['stats']['rejected']==1:break
            time.sleep(.01)
        self.assertEqual(state['stats']['accepted'],1);self.assertEqual(state['stats']['rejected'],1)
        with urllib.request.urlopen(self.url) as r:self.assertIn(b'Floor map',r.read())

    def test_ground_truth_endpoint_validation(self):
        def post(p,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=urllib.request.Request(self.url+'/api/ground-truth',data=json.dumps(p).encode(),headers=headers)
            return urllib.request.urlopen(req)
        with post({'x':2,'y':2}) as r:self.assertEqual(json.load(r)['x'],2)
        for p in ({'x':float('nan'),'y':2},{'x':-1,'y':0},{'y':2}):
            with self.assertRaises(urllib.error.HTTPError) as e:post(p)
            self.assertEqual(e.exception.code,400)
            e.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as e:post({'x':1,'y':1},'https://example.com')
        self.assertEqual(e.exception.code,403)
        e.exception.close()
