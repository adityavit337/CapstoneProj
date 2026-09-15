"""Create a short stationary SYNTHETIC capture for real-time CSV replay."""
import csv
import math
import random
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from indoor_ble.config import load_config

cfg=load_config(ROOT/'config/room.json');rng=random.Random(3)
rows=[]
for sequence in range(15):
    for name,a in cfg['anchors'].items():
        for ch in (37,38,39):
            d=math.hypot(2.5-a['x'],2-a['y'])
            row={'elapsed_s':sequence*.5,'v':1,'type':'observation','simulated':True,'anchor':name,'anchor_boot':12,'uptime_ms':sequence*500,
                 'kind':'tag','tx_id':cfg['tag_id'],'tx_boot':34,'seq':sequence,'channel':ch,'channel_mask':1<<(ch-37),
                 'rssi':round(-59-22*math.log10(d)+rng.gauss(0,1.5)),'tx_dbm':0}
            rows.append(row)
            if sequence%5==0:rows.append(dict(row))
target=ROOT/'sample/observations_simulated.csv';target.parent.mkdir(exist_ok=True)
with target.open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(f'{len(rows)} SIMULATED observations written to {target}')
