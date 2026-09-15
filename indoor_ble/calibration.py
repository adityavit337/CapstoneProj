import math
import statistics
from collections import defaultdict, deque


class ReferenceFitter:
    def __init__(self, config):
        self.cfg=config
        self.samples=defaultdict(lambda:deque(maxlen=3000))

    def add(self,p,now):
        self.samples[(p["anchor"],p["channel"],p["tx_id"])].append((now,p["rssi"],p["tx_dbm"]))

    def models(self,now):
        cfg=self.cfg["calibration"]
        anchors=self.cfg["anchors"]
        result={}
        for receiver,rx in anchors.items():
            for channel in (37,38,39):
                links=[]
                normalized=True
                for name,tx in anchors.items():
                    if receiver==name:
                        continue
                    samples=self.samples[(receiver,channel,tx["wire_id"])]
                    while samples and samples[0][0] < now-cfg["window_s"]:
                        samples.popleft()
                    offset=cfg["reference_tx_offsets_db"].get(name,{}).get(str(channel))
                    normalized &= offset is not None
                    if len(samples) < cfg["min_samples_per_link"]:
                        continue
                    # A power change invalidates this link until older samples expire.
                    if len({s[2] for s in samples}) != 1:
                        continue
                    d=math.hypot(rx["x"]-tx["x"],rx["y"]-tx["y"])
                    links.append((math.log10(d),statistics.mean(s[1] for s in samples)-(offset or 0),len(samples)))
                model={"independent_distances":len(links),"parameters":2,"spatial_residual_dof":max(0,len(links)-2),
                       "normalized_transmitters":normalized,"status":"insufficient links"}
                if len(links)==2:
                    span=abs(links[1][0]-links[0][0])
                    model["log_distance_span"]=span
                    if span < cfg["min_log_distance_span"]:
                        model["status"]="ill-conditioned distance span"
                    else:
                        slope=(links[1][1]-links[0][1])/(links[1][0]-links[0][0])
                        intercept=links[0][1]-slope*links[0][0]
                        n=-slope/10
                        plausible=0.8 <= n <= 6 and -100 <= intercept <= -20
                        model.update(intercept=intercept,n=n,samples=sum(x[2] for x in links),plausible=plausible,
                                     status="exploratory; zero spatial validation dof" if plausible else "implausible fit; rejected")
                        if not normalized:
                            model["status"] += "; transmitter offsets unknown"
                result[f"{receiver}:{channel}"]=model
        return result
