import json
import math
from pathlib import Path


def load_config(path="config/room.json"):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(cfg)
    return cfg


def validate_config(cfg):
    room = cfg["room"]
    if any(not math.isfinite(room[k]) or room[k] <= 0 for k in ("width", "height")):
        raise ValueError("Room dimensions must be finite and positive")
    anchors = cfg["anchors"]
    if set(anchors) != {"A", "B", "C"}:
        raise ValueError("This three-anchor prototype requires IDs A, B, C")
    points = [(a["x"], a["y"]) for a in anchors.values()]
    for x, y in points:
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= room["width"] and 0 <= y <= room["height"]):
            raise ValueError("Anchor coordinates must be inside the room")
    a, b, c = points
    cross = abs((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]))
    distances = [math.dist(a, b), math.dist(a, c), math.dist(b, c)]
    if min(distances) < 0.1 or cross / max(distances)**2 < 0.05:
        raise ValueError("Anchors must be distinct and non-collinear, with useful triangle area")
    if cfg["calibration"]["enabled"] and min(abs(x-y) for i, x in enumerate(distances) for y in distances[i+1:]) < 0.1:
        raise ValueError("Reference experiment requires three distinct separations (>=0.1 m apart)")
    ids = [a["wire_id"] for a in anchors.values()]
    if len(set(ids)) != 3 or any(type(i) is not int or not 1 <= i <= 65535 for i in ids):
        raise ValueError("Anchor wire IDs must be unique uint16 values")
    if type(cfg["tag_id"]) is not int or not 1 <= cfg["tag_id"] <= 65535:
        raise ValueError("tag_id must be uint16")
    p = cfg["position"]
    for key in ("window_s", "stale_s", "online_s", "path_loss_n", "rssi_variance_floor", "acceleration_variance"):
        if not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError(f"position.{key} must be finite and positive")
    if not math.isfinite(p["rssi_at_1m"]) or not -120 <= p["rssi_at_1m"] <= -10:
        raise ValueError("Invalid one-metre RSSI")
    if type(p["min_samples"]) is not int or p["min_samples"] < 1:
        raise ValueError("min_samples must be a positive integer")
    cal = cfg["calibration"]
    if not all(type(cal[k]) in (int,float) and math.isfinite(cal[k]) and cal[k]>0 for k in ("window_s","min_log_distance_span")) or type(cal["min_samples_per_link"]) is not int or cal["min_samples_per_link"] < 2:
        raise ValueError("Invalid reference fit limits")
    if cal["apply_to_tag"] and not cal["transfer_offsets_measured"]:
        raise ValueError("Applying reference models requires measured transmitter transfer offsets")
    for key in ("reference_tx_offsets_db", "tag_transfer_offsets_db"):
        for name, channels in cal[key].items():
            if name not in anchors:
                raise ValueError("Unknown offset anchor")
            for ch, offset in channels.items():
                if ch not in ("37", "38", "39") or type(offset) not in (int,float) or not math.isfinite(offset):
                    raise ValueError("Offsets require channels 37/38/39 and finite dB values")
    for key in ("udp_port", "http_port"):
        if type(cfg["network"][key]) is not int or not 1 <= cfg["network"][key] <= 65535:
            raise ValueError("Invalid network port")
    return cfg
