import streamlit as st
import datetime as dt
import pytz
from streamlit_autorefresh import st_autorefresh

# Import our custom modules
from config import settings
from data_layer import upstox_client as upstox
from data_layer import macro_client
from data_layer.freshness import FreshnessTracker
from factors import oi_factor, volume_factor, regime_factor, confluence
from shadow import log_book

# --- 1. PAGE CONFIG & STYLES ---
st.set_page_config(page_title="Nifty Ecosystem", page_icon="🎯", layout="wide")
st_autorefresh(interval=settings.UI_REFRESH_SEC * 1000, key="nifty_refresh")

st.markdown("""
<style>
.card { background: #fff; padding: 20px; border-radius: 12px; border: 1px solid #e1e4e8; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 15px; color: #111; }
.big-price { font-size: 2.5rem; font-weight: 800; margin: 0; }
.metric-label { font-size: 0.9rem; color: #666; font-weight: 600; text-transform: uppercase; }
.pos { color: #00873c; font-weight: 600; font-size: 1rem;} 
.neg { color: #eb4444; font-weight: 600; font-size: 1rem;}
.decision-box { padding: 30px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px; }
.buy { background: linear-gradient(135deg, #11998e, #38ef7d); }
.sell { background: linear-gradient(135deg, #cb2d3e, #ef473a); }
.wait { background: linear-gradient(135deg, #f12711, #f5af19); }
.neutral { background: linear-gradient(135deg, #2c3e50, #4ca1af); }
</style>
""", unsafe_allow_html=True)

IST = pytz.timezone(settings.IST_TZ)
now = dt.datetime.now(IST)

# --- 2. INITIALIZATION ---
try:
    upstox.init(st.secrets["UPSTOX_TOKEN"])
except Exception as e:
    st.error(f"⚠️ **Setup Error:** {e}. Please check your Streamlit Secrets.")
    st.stop()

if "tracker" not in st.session_state:
    st.session_state.tracker = FreshnessTracker()
tracker = st.session_state.tracker

# --- 3. DATA FETCHING ---
# A. Spot & VIX
spot_q = upstox.get_quote(settings.NIFTY_INDEX_KEY)
vix_q = upstox.get_quote(settings.INDIA_VIX_KEY)

spot_price = spot_q.get("last_price", 0) if spot_q else 0
spot_chg = spot_q.get("net_change", 0) if spot_q else 0
spot_pct = (spot_chg / max(spot_price - spot_chg, 1)) * 100 if spot_q else 0

vix_ltp = vix_q.get("last_price", 0) if vix_q else 0
vix_chg = vix_q.get("net_change", 0) if vix_q else 0
vix_pct = (vix_chg / max(vix_ltp - vix_chg, 1)) * 100 if vix_q else 0

# B. Macro (Crude & INR)
macro_data = macro_client.get_macro_snapshot()
wti_ltp = macro_data["wti"]["ltp"] if macro_data and macro_data["wti"] else 0
wti_chg = macro_data["wti"]["chg"] if macro_data and macro_data["wti"] else 0
wti_pct = macro_data["wti_pct"] if macro_data else 0

inr_ltp = macro_data["inr"]["ltp"] if macro_data and macro_data["inr"] else 0
inr_chg = macro_data["inr"]["chg"] if macro_data and macro_data["inr"] else 0
inr_pct = macro_data["inr_pct"] if macro_data else 0

# C. OI & Expiry
days_until_tuesday = (1 - now.weekday()) % 7
expiry_date = (now + dt.timedelta(days=days_until_tuesday)).strftime('%Y-%m-%d')
today_str = now.strftime('%Y-%m-%d')

oi_resp = upstox.get_change_oi(settings.NIFTY_INDEX_KEY, expiry_date, today_str)

tracker.record_spot(now, spot_price)
tracker.record_oi(now, oi_resp)
report = tracker.report(now)

# D. Volume Baseline (Using Futures as proxy)
fut_q = upstox.get_quote(settings.NIFTY_FUT_KEY)
fut_vol = fut_q.get("volume", 0) if fut_q else 0
fut_oi = fut_q.get("oi", 0) if fut_q else 0
vol_baseline = 100000 

# --- 4. EVALUATION ---
regime_res = regime_factor.evaluate_regime(vix_ltp, vix_pct, wti_ltp, wti_pct, inr_pct)
oi_res = oi_factor.calculate_oi_score(oi_resp, spot_price)
vol_res = volume_factor.evaluate_volume_gate(fut_vol, fut_oi, fut_oi * 0.99, vol_baseline)
final_decision = confluence.resolve_confluence(oi_res, vol_res, regime_res)

# --- 5. LOGGING ---
log_row = {
    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    "nifty_spot": spot_price, "nifty_chg": spot_chg, "nifty_pct": round(spot_pct, 2),
    "vix_ltp": vix_ltp, "vix_chg": vix_chg, "vix_pct": round(vix_pct, 2),
    "wti_ltp": wti_ltp, "wti_chg": wti_chg, "wti_pct": round(wti_pct, 2),
    "inr_ltp": inr_ltp, "inr_chg": inr_chg, "inr_pct": round(inr_pct, 2),
    "oi_score": round(oi_res["score"], 2),
    "volume_gate": vol_res["gate"],
    "regime_status": regime_res["trade_permission"],
    "final_action": final_decision["action"],
    "position_cap": final_decision["position_cap"],
    "reason": " | ".join(final_decision["reasons"])
}
# Fire the logger (ignores errors silently so it doesn't break the UI)
log_book.save_log_to_github(log_row, st.secrets)

# --- 6. UI RENDER ---
st.title("🎯 Nifty Ecosystem Dashboard")

def render_card(label, value, chg, pct, is_inr=False):
    cls = "pos" if chg >= 0 else "neg"
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "—"
    val_str = f"{value:,.2f}"
    if is_inr: val_str = f"{value:.3f}"
    chg_str = f"{arrow} {chg:+,.2f} ({pct:+.2f}%)"
    if is_inr: chg_str = f"{arrow} {chg:+.3f} ({pct:+.2f}%)"
    
    return f"""
    <div class="card">
        <div class="metric-label">{label}</div>
        <div class="big-price">{val_str}</div>
        <div class="{cls}">{chg_str}</div>
    </div>
    """

c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(render_card("Nifty 50", spot_price, spot_chg, spot_pct), unsafe_allow_html=True)
with c2: st.markdown(render_card("India VIX", vix_ltp, vix_chg, vix_pct), unsafe_allow_html=True)
with c3: st.markdown(render_card("WTI Crude", wti_ltp, wti_chg, wti_pct), unsafe_allow_html=True)
with c4: st.markdown(render_card("USD/INR", inr_ltp, inr_chg, inr_pct, is_inr=True), unsafe_allow_html=True)

st.markdown("---")

# Main Decision Box
action = final_decision["action"]
css_class = "neutral"
if "BUY" in action: css_class = "buy"
elif "SELL" in action: css_class = "sell"
elif action in ("WATCH", "VETO"): css_class = "wait"

st.markdown(f"""
<div class="decision-box {css_class}">
    <h1 style="margin:0; font-size: 3rem;">{action.replace('_', ' ')}</h1>
    <p style="font-size: 1.2rem; margin-top: 10px;">Direction: <b>{final_decision['direction']}</b> | Position Size: <b>{final_decision['position_cap'] * 100:.0f}%</b></p>
</div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("🛡️ Macro Regime")
    st.write(f"**Status:** {regime_res['trade_permission']}")
    for r in regime_res["reasons"]: st.caption(f"• {r}")
with col2:
    st.subheader("⚖️ OI Direction")
    st.write(f"**Score:** {oi_res['score']:+.2f}")
    for r in oi_res["reasons"]: st.caption(f"• {r}")
with col3:
    st.subheader("📊 Volume Gate")
    st.write(f"**Status:** {vol_res['gate']}")
    st.caption(f"• {vol_res['reason']}")

st.markdown("---")
st.caption(f"Data Status: {report['reason']} | Last updated: {now.strftime('%H:%M:%S IST')}")
