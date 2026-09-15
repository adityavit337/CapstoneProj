import json
from indoor_ble.config import load_config


def config():
    return load_config()


def packet(**changes):
    p={"v":1,"type":"observation","simulated":False,"anchor":"A","anchor_boot":1,"uptime_ms":1000,
       "kind":"tag","tx_id":100,"tx_boot":2,"seq":1,"channel":37,"channel_mask":1,"rssi":-65,"tx_dbm":0}
    p.update(changes)
    return p


def wire(**changes):
    return json.dumps(packet(**changes)).encode()
