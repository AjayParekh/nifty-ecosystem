"""
data_layer/upstox_client.py

All Upstox network calls live here. Nothing else in the system talks to Upstox.

Every function returns the raw Upstox JSON dict.
On any failure it returns: {"status": "error", "errors": [{"message": "<reason>"}]}
so callers can always check `resp.get("status") == "success"`.
"""
import json
from urllib.parse import quote
import requests

_BASE = "https://api.upstox.com"
_TIMEOUT = 12
_TOKEN = None

class UpstoxError(Exception):
    """Raised only for programming errors (missing token), never for network failures."""

def init(token: str):
    """Call once at app startup. Accepts 'Bearer xxx' or 'xxx'."""
    global _TOKEN
    if not token or not str(token).strip():
        raise UpstoxError("Upstox token is empty — set UPSTOX_TOKEN in Streamlit secrets")
    token = str(token).strip()
    _TOKEN = token if token.startswith("Bearer ") else "Bearer " + token

def _headers():
    if not _TOKEN:
        raise UpstoxError("upstox_client.init() was never called")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": _TOKEN,
    }

def _get(path: str, params: dict):
    try:
        r = requests.get(_BASE + path, params=params, headers=_headers(), timeout=_TIMEOUT)
    except requests.RequestException as e:
        return {"status": "error", "errors": [{"message": f"network: {type(e).__name__}"}]}
    try:
        return r.json()
    except ValueError:
        return {"status": "error", "errors": [{"message": f"non-JSON {r.status_code}: {r.text[:200]}"}]}

def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# ---------------------------------------------------------------- quotes
def get_quote(instrument_key: str):
    """Single instrument quote. Returns the quote dict directly."""
    j = _get("/v2/market-quote/quotes", {"instrument_key": instrument_key})
    if j.get("status") == "success" and j.get("data"):
        return next(iter(j["data"].values()))
    return None

def get_quotes_bulk(instrument_keys):
    """Bulk quotes. Returns {instrument_token: quote_dict}. Upstox allows ~300 keys per call."""
    out = {}
    for chunk in _chunks(list(instrument_keys), 300):
        j = _get("/v2/market-quote/quotes", {"instrument_key": ",".join(chunk)})
        if j.get("status") != "success":
            return out
        for v in (j.get("data") or {}).values():
            tok = v.get("instrument_token")
            if tok:
                out[tok] = v
    return out

def get_option_greeks(instrument_keys):
    """Bulk greeks + volume. Upstox allows ~50 keys per call on this endpoint."""
    out = {}
    for chunk in _chunks(list(instrument_keys), 50):
        j = _get("/v3/market-quote/option-greek", {"instrument_key": ",".join(chunk)})
        if j.get("status") != "success":
            continue
        out.update(j.get("data") or {})
    return out

# ------------------------------------------------------------ option chain
def get_option_chain(underlying_key: str, expiry_date: str):
    """Returns the full option chain for a given underlying and expiry."""
    return _get("/v2/option/chain", {"instrument_key": underlying_key, "expiry_date": expiry_date})

def get_option_contracts(underlying_key: str):
    """Returns list of {expiry, strike_price, instrument_key, ...} for expiry discovery."""
    j = _get("/v2/option/contract", {"instrument_key": underlying_key})
    return j.get("data") or []

# --------------------------------------------------------------- OI flow
def get_change_oi(instrument_key: str, expiry: str, date: str, interval: int = 2):
    return _get("/v2/market/change-oi", {
        "instrument_key": instrument_key, "expiry": expiry,
        "date": date, "interval": interval,
    })

def get_oi(instrument_key: str, expiry: str, date: str):
    return _get("/v2/market/oi", {
        "instrument_key": instrument_key, "expiry": expiry, "date": date,
    })

def get_futures_smartlist(asset_type: str = "INDEX", category: str = "TOP_TRADED", page_size: int = 20):
    return _get("/v2/market/smartlist/futures", {
        "asset_type": asset_type, "category": category,
        "page_number": 1, "page_size": page_size,
    })

# ------------------------------------------------------- historical candle
def get_historical_candle(instrument_key: str, unit: str, to_date: str, from_date: str):
    """unit: 'day' | '1minute' | '30minute' — matches Upstox v2 API."""
    return _get(
        f"/v2/historical-candle/{quote(instrument_key, safe='')}/{unit}/{to_date}/{from_date}",
        {},
    )


# ------------------------------------------------------- futures helper
import gzip
def get_nearest_futures_key(underlying_symbol="NIFTY"):
    """Fetches the NSE instrument master and finds the nearest active Futures contract."""
    try:
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        all_ins = json.loads(gzip.decompress(r.content))
        
        import datetime as dt
        today = dt.date.today().isoformat()
        futs = []
        for i in all_ins:
            if i.get("instrument_type") == "FUT" and i.get("underlying_symbol") == underlying_symbol:
                # Expiry comes as a timestamp, convert to date string
                exp_ts = i.get("expiry", 0) / 1000
                exp_date = dt.datetime.fromtimestamp(exp_ts).date().isoformat()
                if exp_date >= today:
                    futs.append({"key": i["instrument_key"], "expiry": exp_date})
        
        if not futs:
            return None
            
        # Sort by expiry and take the closest one
        futs.sort(key=lambda x: x["expiry"])
        return futs[0]["key"]
    except Exception:
        return None
