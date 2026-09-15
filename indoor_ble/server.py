import argparse
import json
import socketserver
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_config
from .engine import Engine
from .simulation import Simulator, replay_packets
from .survey import calculate_survey


class UDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address=True
    daemon_threads=True


class Application:
    def __init__(self,config,log_dir=None,simulated=False,manual=False):
        self.manual=manual
        self.cfg=config; self.engine=Engine(config,log_dir,simulated)
        self.lock=threading.RLock(); self.started=time.monotonic()
        self.udp=None; self.http=None

    def handlers(self):
        app=self
        class UDP(socketserver.BaseRequestHandler):
            def handle(self):
                raw,sock=self.request
                with app.lock:
                    p=app.engine.ingest(raw)
                if p and p["type"]=="heartbeat":
                    # Compact control protocol; echo uptime to reject old replies.
                    phase=int((time.monotonic()-app.started)*1000)%12000
                    reply=f"SYNC1 {p['uptime_ms']} {phase} {int(app.cfg['calibration']['enabled'])}"
                    sock.sendto(reply.encode(),self.client_address)
        class HTTP(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def reply(self,status,body,content_type="application/json"):
                if not isinstance(body,bytes):
                    body=json.dumps(body,allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type",content_type)
                self.send_header("Content-Length",str(len(body)))
                self.send_header("Cache-Control","no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):
                    pass

            def do_GET(self):
                if self.path=="/":
                    page="survey.html" if app.manual else "dashboard.html"
                    self.reply(200,Path(__file__).with_name(page).read_bytes(),"text/html; charset=utf-8")
                elif self.path=="/survey":
                    self.reply(200,Path(__file__).with_name("survey.html").read_bytes(),"text/html; charset=utf-8")
                elif self.path=="/api/state":
                    with app.lock:
                        state=app.engine.snapshot()
                    self.reply(200,state)
                else:
                    self.reply(404,{"error":"Not found"})

            def do_POST(self):
                if self.path not in ("/api/ground-truth", "/api/survey"):
                    self.reply(404,{"error":"Not found"}); return
                # Local UI only; reject cross-site forms and oversized payloads.
                origin=self.headers.get("Origin")
                host=self.headers.get("Host")
                if origin and origin != "http://"+str(host):
                    self.reply(403,{"error":"Origin rejected"}); return
                try:
                    length=int(self.headers.get("Content-Length","0"))
                    if not 0<length<=8192 or self.headers.get_content_type()!="application/json":
                        raise ValueError("Expected small JSON body")
                    p=json.loads(self.rfile.read(length))
                    if self.path=="/api/survey":
                        self.reply(200,calculate_survey(p)); return
                    with app.lock:
                        row=app.engine.set_truth(p["x"],p["y"],p.get("note",""))
                    self.reply(200,row)
                except (ValueError,KeyError,TypeError) as exc:
                    self.reply(400,{"error":str(exc)})
        return UDP,HTTP

    def start(self,udp=True):
        udp_handler,http_handler=self.handlers()
        net=self.cfg["network"]
        try:
            if udp:
                self.udp=UDPServer((net["udp_host"],net["udp_port"]),udp_handler)
                threading.Thread(target=self.udp.serve_forever,daemon=True).start()
            self.http=ThreadingHTTPServer((net["http_host"],net["http_port"]),http_handler)
            self.http.daemon_threads=True
            threading.Thread(target=self.http.serve_forever,daemon=True).start()
        except Exception:
            self.close()
            raise

    def close(self):
        for server in (self.udp,self.http):
            if server:
                server.shutdown(); server.server_close()
        self.engine.close()


def main():
    parser=argparse.ArgumentParser(description="Local BLE positioning receiver and floor map")
    parser.add_argument("--config",default="config/room.json")
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--simulate",action="store_true")
    modes.add_argument("--manual",action="store_true",help="Two-board manual RSSI distance and sequential survey; no UDP")
    modes.add_argument("--replay",help="Replay simulated CSV in real time")
    parser.add_argument("--duration",type=float,default=0,help="Stop after seconds; zero runs until Ctrl+C")
    parser.add_argument("--log-dir")
    args=parser.parse_args()
    cfg=load_config(args.config)
    simulated=args.simulate or bool(args.replay)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    log_dir=args.log_dir or str(Path("logs")/(("simulation_" if simulated else "hardware_")+stamp))
    app=Application(cfg,log_dir,simulated,manual=args.manual)
    simulator=Simulator(cfg) if args.simulate else None
    replay=iter(replay_packets(args.replay)) if args.replay else None
    next_packet=next(replay,None) if replay else None
    app.start(udp=not simulated and not args.manual)
    net=cfg["network"]
    print(f"{'MANUAL SEQUENTIAL SURVEY' if args.manual else 'SIMULATED DATA' if simulated else 'HARDWARE MODE'} | http://{net['http_host']}:{app.http.server_port} | CSV: {log_dir}",flush=True)
    if not simulated and not args.manual:
        print(f"Listening for anchors on UDP {net['udp_host']}:{net['udp_port']}",flush=True)
    started=time.monotonic()
    try:
        while True:
            now=time.monotonic(); elapsed=now-started
            with app.lock:
                if simulator:
                    simulator.step(app.engine,now,elapsed)
                while next_packet and next_packet[0]<=elapsed:
                    app.engine.ingest(json.dumps(next_packet[1]).encode(),now)
                    next_packet=next(replay,None)
                if not args.manual:
                    app.engine.estimate(now)
            if args.duration and elapsed>=args.duration:
                break
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()


if __name__=="__main__":
    main()
