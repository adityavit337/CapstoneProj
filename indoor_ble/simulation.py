"""Deterministic synthetic RSSI; never evidence of physical accuracy."""
import json
import math
import random


class Simulator:
    def __init__(self,config,seed=17):
        self.cfg=config; self.rng=random.Random(seed); self.seq=0

    def step(self,engine,now,elapsed):
        room=self.cfg["room"]
        x=room["width"]*(0.5+0.25*math.cos(elapsed/12))
        y=room["height"]*(0.5+0.25*math.sin(elapsed/12))
        pcfg=self.cfg["position"]
        for name,a in self.cfg["anchors"].items():
            common={"v":1,"simulated":True,"anchor":name,"anchor_boot":123,"uptime_ms":int(elapsed*1000)&0xFFFFFFFF}
            engine.ingest(json.dumps({**common,"type":"heartbeat","queue_drops":0}).encode(),now)
            for channel in (37,38,39):
                if self.rng.random()<0.06:
                    continue
                d=max(0.15,math.hypot(x-a["x"],y-a["y"]))
                rssi=pcfg["rssi_at_1m"]-10*pcfg["path_loss_n"]*math.log10(d)+self.rng.gauss(0,2)+(channel-38)*1.0
                p={**common,"type":"observation","kind":"tag","tx_id":self.cfg["tag_id"],"tx_boot":456,"seq":self.seq,
                   "channel":channel,"channel_mask":1<<(channel-37),"rssi":max(-127,min(-1,round(rssi))),"tx_dbm":0}
                engine.ingest(json.dumps(p).encode(),now)
                if self.rng.random()<0.2:
                    engine.ingest(json.dumps(p).encode(),now+.0001)
                for txname,tx in self.cfg["anchors"].items():
                    if txname==name:
                        continue
                    rd=math.hypot(tx["x"]-a["x"],tx["y"]-a["y"])
                    reference={**p,"kind":"reference","tx_id":tx["wire_id"],"tx_boot":700+tx["wire_id"],
                               "rssi":round(-59-22*math.log10(rd)+self.rng.gauss(0,1.5))}
                    engine.ingest(json.dumps(reference).encode(),now)
        engine.truth={"x":x,"y":y,"note":"SIMULATED trajectory, not measured ground truth"}
        self.seq=(self.seq+1)&0xFFFFFFFF


def replay_packets(path):
    import csv
    integer_keys=("v","anchor_boot","uptime_ms","tx_id","tx_boot","seq","channel","channel_mask","rssi","tx_dbm")
    with open(path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("simulated","").lower()!="true":
                raise ValueError("Replay input must explicitly be labelled simulated")
            p={k:int(row[k]) for k in integer_keys}
            p.update(type="observation",simulated=True,anchor=row["anchor"],kind=row["kind"])
            yield float(row["elapsed_s"]),p
