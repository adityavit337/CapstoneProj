"""Strict UDP schema and bounded replay/sequence accounting."""
import json
from collections import OrderedDict

MASKS = {0: 7, 37: 1, 38: 2, 39: 4}


def _integer(p, key, lo, hi):
    if type(p.get(key)) is not int or not lo <= p[key] <= hi:
        raise ValueError(f"Invalid {key}")


def parse_packet(raw, config, simulated=False):
    if len(raw) > 1024:
        raise ValueError("Datagram exceeds 1024 bytes")
    try:
        p = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid JSON") from exc
    if not isinstance(p, dict) or p.get("v") != 1 or type(p.get("v")) is not int:
        raise ValueError("Unsupported protocol")
    if p.get("type") not in ("observation", "heartbeat") or not isinstance(p.get("anchor"), str) or p["anchor"] not in config["anchors"]:
        raise ValueError("Unknown packet type or anchor")
    if type(p.get("simulated")) is not bool or p["simulated"] != simulated:
        raise ValueError("Hardware and simulated sources must not be mixed")
    for key in ("anchor_boot", "uptime_ms"):
        _integer(p, key, 0, 0xFFFFFFFF)
    if p["type"] == "heartbeat":
        _integer(p, "queue_drops", 0, 0xFFFFFFFF)
        return p
    if p.get("kind") not in ("tag", "reference"):
        raise ValueError("Unknown transmitter kind")
    _integer(p, "tx_id", 1, 65535)
    if p["kind"] == "tag" and p["tx_id"] != config["tag_id"]:
        raise ValueError("Unconfigured tag")
    if p["kind"] == "reference":
        ids = {a["wire_id"] for k, a in config["anchors"].items() if k != p["anchor"]}
        if p["tx_id"] not in ids:
            raise ValueError("Unknown or self reference")
    for key in ("tx_boot", "seq"):
        _integer(p, key, 0, 0xFFFFFFFF)
    _integer(p, "rssi", -127, -1)
    _integer(p, "tx_dbm", -30, 20)
    _integer(p, "channel", 0, 39)
    _integer(p, "channel_mask", 1, 7)
    if p["channel"] not in MASKS or p["channel_mask"] != MASKS[p["channel"]]:
        raise ValueError("Channel label/mask mismatch")
    if p["kind"] == "reference" and p["channel"] == 0:
        raise ValueError("Reference experiment requires individual channels")
    return p


class Deduplicator:
    """One statistical sample per received burst, not per repeated PDU.

    Identity includes BOTH boot sessions. TTL and max_entries bound memory.
    gap_events counts forward sequence gaps, not a measured RF packet-loss rate.
    Late unique packets are accepted and separately counted.
    """
    def __init__(self, ttl=180.0, max_entries=50000):
        self.ttl, self.max_entries = ttl, max_entries
        self.seen = OrderedDict()
        self.high = OrderedDict()
        self.duplicates = self.gap_events = self.late = 0

    def accept(self, p, now):
        while self.seen and next(iter(self.seen.values())) < now-self.ttl:
            self.seen.popitem(last=False)
        stream = tuple(p[k] for k in ("anchor", "anchor_boot", "kind", "tx_id", "tx_boot", "channel"))
        key = stream + (p["seq"],)
        if key in self.seen:
            self.duplicates += 1
            return False
        self.seen[key] = now
        if len(self.seen) > self.max_entries:
            self.seen.popitem(last=False)
        previous = self.high.get(stream)
        if previous is not None:
            delta = (p["seq"]-previous) & 0xFFFFFFFF
            if 0 < delta < 0x80000000:
                self.gap_events += max(0, delta-1)
                self.high[stream] = p["seq"]
            else:
                self.late += 1
        else:
            self.high[stream] = p["seq"]
        self.high.move_to_end(stream)
        if len(self.high) > 128:
            self.high.popitem(last=False)
        return True
