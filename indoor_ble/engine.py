import csv
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from .protocol import Deduplicator, parse_packet
from .position import filtered_rssi, channel_distance, fuse_distances, trilaterate, AxisKalman
from .calibration import ReferenceFitter


class CsvLogs:
    def __init__(self,root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.files={}
        self.writers={}

    def write(self,name,row):
        if name not in self.files:
            path=self.root/(name+".csv")
            exists=path.exists() and path.stat().st_size>0
            f=path.open("a",newline="",encoding="utf-8")
            self.files[name]=f
            self.writers[name]=csv.DictWriter(f,fieldnames=list(row))
            if not exists:
                self.writers[name].writeheader()
        self.writers[name].writerow(row)

    def flush(self):
        for f in self.files.values():
            f.flush()

    def close(self):
        for f in self.files.values():
            f.close()


class Engine:
    def __init__(self,config,log_dir=None,simulated=False):
        self.cfg=config; self.simulated=simulated
        self.logs=CsvLogs(log_dir) if log_dir else None
        self.dedup=Deduplicator(); self.references=ReferenceFitter(config)
        self.samples=defaultdict(lambda:deque(maxlen=1000))
        self.online={}; self.stats={"accepted":0,"rejected":0}
        self.last_error=""; self.truth=None; self.result={}
        self.version=0; self.last_version=-1; self.filter_time=None; self.axes=None
        self.started=time.monotonic()

    def ingest(self,raw,now=None):
        now=time.monotonic() if now is None else now
        try:
            p=parse_packet(raw,self.cfg,self.simulated)
        except (ValueError,TypeError) as exc:
            self.stats["rejected"]+=1; self.last_error=str(exc)
            return None
        status=self.online.setdefault(p["anchor"],{})
        status.update(last_seen=now,boot=p["anchor_boot"])
        if p["type"]=="heartbeat":
            status["queue_drops"]=p["queue_drops"]
            return p
        accepted=self.dedup.accept(p,now)
        if self.logs:
            row={"received_utc":datetime.now(timezone.utc).isoformat(),"received_monotonic_s":now,**p,"accepted":accepted}
            # Fixed schema: ignore arbitrary extra wire keys.
            fields=("received_utc","received_monotonic_s","v","type","simulated","anchor","anchor_boot","uptime_ms","kind","tx_id","tx_boot","seq","channel","channel_mask","rssi","tx_dbm","accepted")
            self.logs.write("observations",{k:row[k] for k in fields})
        if not accepted:
            return p
        self.stats["accepted"]+=1
        if p["kind"]=="reference":
            if self.cfg["calibration"]["enabled"]:
                self.references.add(p,now)
        else:
            self.samples[(p["anchor"],p["channel"])].append((now,p["rssi"]))
            self.version+=1
        return p

    def estimate(self,now=None):
        now=time.monotonic() if now is None else now
        pcfg=self.cfg["position"]; cal=self.cfg["calibration"]
        models=self.references.models(now) if cal["enabled"] else {}
        ranges={}; base=[]; adv=[]; points=[]
        for name,a in self.cfg["anchors"].items():
            pooled=[]; channels={}; estimates=[]
            for channel in (0,37,38,39):
                samples=self.samples[(name,channel)]
                while samples and samples[0][0] < now-pcfg["window_s"]:
                    samples.popleft()
                values=[r for t,r in samples if now-t <= pcfg["stale_s"]]
                if len(values) < pcfg["min_samples"]:
                    continue
                pooled.extend(values)
                rssi,var=filtered_rssi(values,pcfg["rssi_variance_floor"])
                intercept,n=pcfg["rssi_at_1m"],pcfg["path_loss_n"]
                applied=False
                model=models.get(f"{name}:{channel}",{})
                offset=cal["tag_transfer_offsets_db"].get(name,{}).get(str(channel))
                if cal["apply_to_tag"] and cal["transfer_offsets_measured"] and offset is not None and model.get("plausible") and model.get("normalized_transmitters"):
                    intercept,n=model["intercept"]+offset,model["n"]
                    applied=True
                d,v=channel_distance(rssi,var,intercept,n)
                channels[str(channel)]={"rssi":rssi,"rssi_variance":var,"distance_m":d,"variance_m2":v,"samples":len(values),"reference_model_applied":applied}
                if channel:
                    estimates.append((d,v))
            if pooled:
                r,v=filtered_rssi(pooled,pcfg["rssi_variance_floor"])
                bd,bv=channel_distance(r,v,pcfg["rssi_at_1m"],pcfg["path_loss_n"])
                points.append((a["x"],a["y"]))
                base.append(bd)
                ranges[name]={"baseline_m":bd,"channels":channels}
                # Require all three channels per anchor for the comparative result.
                if len(estimates)==3:
                    fd,fv=fuse_distances(estimates)
                    adv.append((fd,fv))
                    ranges[name].update(fused_m=fd,fused_variance_m2=fv)
        baseline=advanced=tracked=None
        bounds=(self.cfg["room"]["width"],self.cfg["room"]["height"])
        if len(base)==3:
            baseline=trilaterate(points,base,bounds=bounds)
        if len(adv)==3:
            advanced=trilaterate(points,[x[0] for x in adv],[x[1] for x in adv],bounds)
        if advanced and pcfg["kalman"]:
            if self.axes is None or self.filter_time is None or now-self.filter_time>pcfg["stale_s"]:
                self.axes=[AxisKalman(advanced["x"]),AxisKalman(advanced["y"])]
                self.filter_time=now
            elif self.version != self.last_version:
                dt=max(0.001,min(2.0,now-self.filter_time))
                for axis,key in zip(self.axes,("x","y")):
                    axis.update(advanced[key],dt,advanced["variance_"+key],pcfg["acceleration_variance"])
                self.filter_time=now
            tracked={"x":self.axes[0].x,"y":self.axes[1].x}
        elif advanced is None:
            self.axes=None; self.filter_time=None
        changed=self.version != self.last_version
        self.last_version=self.version
        self.result={"baseline":baseline,"advanced":advanced,"tracked":tracked,"ranges":ranges,"reference_models":models,
                     "status":"position available" if baseline else "waiting for fresh readings from all three anchors"}
        if self.logs and changed and baseline:
            row={"utc":datetime.now(timezone.utc).isoformat(),"monotonic_s":now,"simulated":self.simulated}
            for label,pos in (("baseline",baseline),("advanced",advanced),("tracked",tracked)):
                for key in ("x","y","residual_m"):
                    row[label+"_"+key]=pos.get(key,"") if pos else ""
            self.logs.write("positions",row)
        if self.logs:
            self.logs.flush()
        return self.result

    def set_truth(self,x,y,note="",now=None):
        now=time.monotonic() if now is None else now
        room=self.cfg["room"]
        if type(x) not in (int,float) or type(y) not in (int,float) or not math.isfinite(x+y) or not 0<=x<=room["width"] or not 0<=y<=room["height"]:
            raise ValueError("Ground truth must be finite and inside the room")
        self.estimate(now)
        row={"utc":datetime.now(timezone.utc).isoformat(),"monotonic_s":now,"simulated":self.simulated,"x":x,"y":y,"note":str(note)[:200]}
        for label in ("baseline","advanced","tracked"):
            pos=self.result.get(label)
            row[label+"_error_m"]=math.hypot(pos["x"]-x,pos["y"]-y) if pos else ""
        self.truth={"x":x,"y":y,"recorded_monotonic_s":now,"note":str(note)[:200]}
        if self.logs:
            self.logs.write("ground_truth",row); self.logs.flush()
        return row

    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        anchors={}
        for name,a in self.cfg["anchors"].items():
            st=self.online.get(name,{})
            age=now-st["last_seen"] if "last_seen" in st else None
            anchors[name]={**a,"online":age is not None and age<=self.cfg["position"]["online_s"],"age_s":age,"queue_drops":st.get("queue_drops",0)}
        return {"simulated":self.simulated,"room":self.cfg["room"],"anchors":anchors,"truth":self.truth,
                "stats":{**self.stats,"duplicates":self.dedup.duplicates,"sequence_gap_events":self.dedup.gap_events,"late":self.dedup.late},
                "last_error":self.last_error,**self.result}

    def close(self):
        if self.logs:
            self.logs.close()
