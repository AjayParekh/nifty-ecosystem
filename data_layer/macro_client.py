"""
data_layer/macro_client.py

Yahoo Finance feed for the two macro anchors: WTI crude and USD/INR.
No Upstox token needed. Public endpoint.

Returns None on failure — never returns 0. Downstream code must handle None.
"""
import datetime as dt
import pytz
import requests

IST = pytz.timezone("Asia/Kolkata")
_TIMEOUT = 6
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

def _fetch_meta(symbol: str):
    for host in _HOSTS:
        try:
            r = requests.get(
                f"https://{host}/v8/finance/chart/{symbol}",
                headers=_UA, timeout=_TIMEOUT,
            )
            r.raise_for_status()
            result = (r.json().get("chart") or {}).get("result")
            if not result:
                continue
            return result[0].get("meta") or {}
        except Exception:
            continue
    return None

def _quote_from_meta(meta):
    if not meta:
        return None
    last = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose")
    if last is None or prev in (None, 0):
        return None
    chg = last - prev
    pct = chg / prev * 100
    return {
        "ltp": float(last),
        "prev": float(prev),
        "chg": float(chg),
        "pct": float(pct),
        "market_closed": (chg == 0.0),
    }

def get_wti():
    return _quote_from_meta(_fetch_meta("CL=F"))

def get_usdinr():
    return _quote_from_meta(_fetch_meta("USDINR=X"))

def get_macro_snapshot():
    """
    Combined macro view used by the regime layer.

    adjusted_wti_pct = ((1 + WTI%) * (1 + INR%)) - 1) * 100
        — the MCX-crude-equivalent move, same formula your crudeoilm.py uses.
    """
    wti = get_wti()
    inr = get_usdinr()
    if wti is None and inr is None:
        return None
    wti_pct = wti["pct"] if wti else 0.0
    inr_pct = inr["pct"] if inr else 0.0
    adjusted = (((1 + wti_pct / 100) * (1 + inr_pct / 100)) - 1) * 100
    return {
        "wti": wti,
        "inr": inr,
        "wti_pct": wti_pct,
        "inr_pct": inr_pct,
        "adjusted_wti_pct": adjusted,
        "both_market_closed": bool(
            (wti is None or wti["market_closed"]) and (inr is None or inr["market_closed"])
        ),
        "fetched_at": dt.datetime.now(IST).strftime("%H:%M:%S"),
    }
