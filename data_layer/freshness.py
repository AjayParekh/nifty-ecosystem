"""
data_layer/freshness.py

L0 — Data freshness tracker. Every layer above reads from here.

Rules:
  * A failed fetch is NEVER treated as a zero.
  * A repeated identical response is NEVER counted as a new observation.
  * Freshness is judged per feed (spot, oi, volume) using STALE_AFTER thresholds
    from config.settings.
"""
import math
from collections import deque
import datetime as dt
from config.settings import (
    SPOT_BUFFER_MIN,
    SPOT_STALE_SEC,
    OI_STALE_SEC,
    VOLUME_STALE_SEC,
)

_STALE = {"spot": SPOT_STALE_SEC, "oi": OI_STALE_SEC, "volume": VOLUME_STALE_SEC}

class _Feed:
    def __init__(self):
        self.last_success = None
        self.last_hash = None
        self.last_change = None
        self.ok = 0
        self.errors = 0
        self.missing = 0
        self.unchanged = 0
        self.last_error = None

    def record(self, now, ok, payload_hash=None, error=None, missing=False):
        if not ok:
            if missing:
                self.missing += 1
            else:
                self.errors += 1
            self.last_error = str(error)[:200] if error else ("missing" if missing else "error")
            return False
        self.last_success = now
        self.ok += 1
        if payload_hash is None or payload_hash != self.last_hash:
            self.last_hash = payload_hash
            self.last_change = now
            return True
        self.unchanged += 1
        return False

    def status(self, now):
        if self.last_success is None:
            return "NEVER"
        age = (now - self.last_success).total_seconds()
        return "STALE" if age > _STALE.get(self, 30) else "FRESH"

def _valid_price(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if (math.isfinite(x) and x > 0) else None

def _hash_oi_items(items):
    """None stays None — never coerced to zero. So a missing field shows up as a change."""
    return hash(tuple(sorted(
        (it.get("strike_price"), it.get("call_change_oi"), it.get("put_change_oi"))
        for it in items
    )))

class FreshnessTracker:
    def __init__(self):
        self.feeds = {"spot": _Feed(), "oi": _Feed(), "volume": _Feed()}
        self.spot_buf = deque()             # [(ts, price), ...] trimmed to SPOT_BUFFER_MIN

    # ---------------------------------------------------------- record
    def record_spot(self, now, price):
        p = _valid_price(price)
        if p is None:
            return self.feeds["spot"].record(now, False, error="spot unavailable", missing=True)
        self.spot_buf.append((now, p))
        cutoff = now - dt.timedelta(minutes=SPOT_BUFFER_MIN)
        while self.spot_buf and self.spot_buf[0][0] < cutoff:
            self.spot_buf.popleft()
        return self.feeds["spot"].record(now, True, payload_hash=p)

    def record_oi(self, now, resp, error=None):
        if error is not None:
            return self.feeds["oi"].record(now, False, error=f"fetch: {error}")
        if not isinstance(resp, dict):
            return self.feeds["oi"].record(now, False, error="no response", missing=True)
        if resp.get("status") != "success":
            msg = resp.get("errors") or resp.get("message") or "unknown"
            return self.feeds["oi"].record(now, False, error=f"API: {msg}")
        items = (resp.get("data") or {}).get("call_put_oi_data_list") or []
        if not items:
            return self.feeds["oi"].record(now, False, error="empty strike list", missing=True)
        return self.feeds["oi"].record(now, True, payload_hash=_hash_oi_items(items))

    def record_volume(self, now, snapshot_hash):
        return self.feeds["volume"].record(now, True, payload_hash=snapshot_hash)

    # ------------------------------------------------------------ read
    def freshness(self, now):
        out = {}
        for kind, feed in self.feeds.items():
            age = (now - feed.last_success).total_seconds() if feed.last_success else None
            if feed.last_success is None:
                status = "NEVER"
            elif age > _STALE[kind]:
                status = "STALE"
            else:
                status = "FRESH"
            out[kind] = {
                "status": status, "age": age,
                "errors": feed.errors, "missing": feed.missing,
                "unchanged": feed.unchanged,
                "last_success": feed.last_success, "last_change": feed.last_change,
                "last_error": feed.last_error,
            }
        return out

    def report(self, now):
        """Single source of truth: is it safe to fire a signal right now?"""
        fresh = self.freshness(now)
        if fresh["spot"]["status"] != "FRESH":
            return {"feeds": fresh, "reliable": False, "reason": f"spot {fresh['spot']['status']}"}
        if fresh["oi"]["status"] != "FRESH":
            return {"feeds": fresh, "reliable": False, "reason": f"oi {fresh['oi']['status']}"}
        return {"feeds": fresh, "reliable": True, "reason": "OK"}

    def spot(self, now, tol_sec=15):
        """Latest spot within tol_sec, else None. Never back-fills older samples."""
        if not self.spot_buf:
            return None
        ts, price = self.spot_buf[-1]
        if (now - ts).total_seconds() > tol_sec:
            return None
        return price

    def spot_between(self, ts_a, ts_b):
        """Samples recorded in [ts_a, ts_b]. Used later for outcome tracking (L4)."""
        return [(t, p) for t, p in self.spot_buf if ts_a <= t <= ts_b]
