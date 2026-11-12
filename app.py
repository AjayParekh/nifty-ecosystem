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

# --- 1. PAGE CONFIG & STYLES ---
st.set_page_config(page_title="Nifty Ecosystem", page_icon="🎯", layout="wide")
st_autorefresh(interval=settings.UI_REFRESH_SEC * 1000, key="nifty_refresh")

st.markdown("""
<style>
.card { background: #fff; padding: 20px; border-radius: 12px; border: 1px solid #e1e4e8; box-shadow: 0 4px 10px rgba(0,0,0,0.03); margin-bottom: 15px; color: #111; }
.big-price { font-size: 2.5rem; font-weight: 800; margin: 0; }
.metric-label { font-size: 0.9rem; color: #666; font-weight: 600; text-transform: uppercase; }
.pos { color: #00873c; } .neg { color: #eb4444; }
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

# Initialize Freshness Tracker in Session State
if "tracker" not in st.session_state:
    st.session_state.tracker = FreshnessTracker()
tracker = st.session_state.tracker

# --- 3. DATA FETCHING ---
# A. Spot & VIX
spot_q = upstox.get_quote(settings.NIFTY_INDEX_KEY)
vix_q = upstox.get_quote(settings.INDIA_VIX_KEY)

spot_price = spot_q.get("last_price") if spot_q else None
vix_ltp = vix_q.get("last_price") if vix_q else None
vix_pct = vix_q.get("net_change", 0) / max(vix_q.get("close", 1), 1) * 100 if vix_q else None

# B. Macro (Crude & INR)
macro_data = macro_client.get_macro_snapshot()
wti_ltp = macro_data["wti"]["ltp"] if macro_data and macro_data["wti"] else None
wti_pct = macro_data["wti_pct"] if macro_data else None
inr_pct = macro_data["inr_pct"] if macro_data else None

# C. OI & Expiry
# Get nearest expiry dynamically (Tuesday)
days_until_tuesday = (1 - now.weekday()) % 7
expiry_date = (now + dt.timedelta(days=days_until_tuesday)).strftime('%Y-%m-%d')
today_str = now.strftime('%Y-%m-%d')

oi_resp = upstox.get_change_oi(settings.NIFTY_INDEX_KEY, expiry_date, today_str)

# Record in tracker
tracker.record_spot(now, spot_price)
tracker.record_oi(now, oi_resp)
report = tracker.report(now)

# D. Extract Volume & OI for Gate (using Futures as a proxy for overall market conviction)
fut_q = upstox.get_quote(settings.NIFTY_FUT_KEY)
fut_vol = fut_q.get("volume") if fut_q else 0
fut_oi = fut_q.get("oi") if fut_q else 0

# Calculate Volume Baseline (Simplified for first run: using a flat 1L as baseline)
# In a full setup, you'd store this in st.session_state over time.
vol_baseline = 100000 

# --- 4. EVALUATION ---
# A. Regime
regime_res = regime_factor.evaluate_regime(vix_ltp, vix_pct, wti_ltp, wti_pct, inr_pct)

# B. OI Score
oi_res = oi_factor.calculate_oi_score(oi_resp, spot_price)

# C. Volume Gate
vol_res = volume_factor.evaluate_volume_gate(fut_vol, fut_oi, fut_oi * 0.99, vol_baseline)

# D. Confluence
final_decision = confluence.resolve_confluence(oi_res, vol_res, regime_res)

# --- 5. UI RENDER ---

st.title("🎯 Nifty Ecosystem Dashboard")

# Top Row: Prices
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f'<div class="card"><div class="metric-label">Nifty 50</div><div class="big-price">{spot_price:,.2f}</div></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="card"><div class="metric-label">India VIX</div><div class="big-price">{vix_ltp:.2f}</div></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="card"><div class="metric-label">WTI Crude</div><div class="big-price">${wti_ltp:.2f}</div></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="card"><div class="metric-label">USD/INR Move</div><div class="big-price">{inr_pct:+.2f}%</div></div>', unsafe_allow_html=True)

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

# Detailed Breakdown
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🛡️ Macro Regime")
    st.write(f"**Status:** {regime_res['trade_permission']}")
    for r in regime_res["reasons"]:
        st.caption(f"• {r}")

with col2:
    st.subheader("⚖️ OI Direction")
    st.write(f"**Score:** {oi_res['score']:+.2f}")
    for r in oi_res["reasons"]:
        st.caption(f"• {r}")

with col3:
    st.subheader("📊 Volume Gate")
    st.write(f"**Status:** {vol_res['gate']}")
    st.caption(f"• {vol_res['reason']}")

# Data Freshness Footer
st.markdown("---")
st.caption(f"Data Status: {report['reason']} | Last updated: {now.strftime('%H:%M:%S IST')}")
