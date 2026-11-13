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
.alert-box { padding: 15px; border-radius: 10px; margin-bottom: 15px; font-weight: bold; }
.alert-trap { background-color: #f8d7da; color: #721c24; border-left: 5px solid #dc3545; }
.alert-safe { background-color: #d4edda; color: #155724; border-left: 5px solid #28a745; }
.alert-info { background-color: #d1ecf1; color: #0c5460; border-left: 5px solid #17a2b8; }
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
spot_q = upstox.get_quote(settings.NIFTY_INDEX_KEY)
vix_q = upstox.get_quote(settings.INDIA_VIX_KEY)

spot_price = spot_q.get("last_price", 0) if spot_q else 0
spot_chg = spot_q.get("net_change", 0) if spot_q else 0
spot_pct = (spot_chg / max(spot_price - spot_chg, 1)) * 100 if spot_q else 0

vix_ltp = vix_q.get("last_price", 0) if vix_q else 0
vix_chg = vix_q.get("net_change", 0) if vix_q else 0
vix_pct = (vix_chg / max(vix_ltp - vix_chg, 1)) * 100 if vix_q else 0

macro_data = macro_client.get_macro_snapshot()
wti_ltp = macro_data["wti"]["ltp"] if macro_data and macro_data["wti"] else 0
wti_chg = macro_data["wti"]["chg"] if macro_data and macro_data["wti"] else 0
wti_pct = macro_data["wti_pct"] if macro_data else 0

inr_ltp = macro_data["inr"]["ltp"] if macro_data and macro_data["inr"] else 0
inr_chg = macro_data["inr"]["chg"] if macro_data and macro_data["inr"] else 0
inr_pct = macro_data["inr_pct"] if macro_data else 0

days_until_tuesday = (1 - now.weekday()) % 7
expiry_date = (now + dt.timedelta(days=days_until_tuesday)).strftime('%Y-%m-%d')
today_str = now.strftime('%Y-%m-%d')

oi_resp = upstox.get_change_oi(settings.NIFTY_INDEX_KEY, expiry_date, today_str)

# Calculate Total Change OI, PCR, and Near-ATM Change OI
total_call_chg = 0
total_put_chg = 0
total_call_oi = 0
total_put_oi = 0
pcr = 0.0
near_call_chg = 0
near_put_chg = 0

if oi_resp and oi_resp.get("status") == "success":
    items = oi_resp.get("data", {}).get("call_put_oi_data_list", [])
    
    # 1. Calculate Totals
    for item in items:
        total_call_chg += item.get("call_change_oi", 0) or 0
        total_put_chg += item.get("put_change_oi", 0) or 0
        total_call_oi += item.get("call_oi", 0) or 0
        total_put_oi += item.get("put_oi", 0) or 0
        
    if total_call_oi > 0:
        pcr = total_put_oi / total_call_oi

    # 2. Calculate Near-ATM (Focus on +/- 3 strikes)
    if spot_price > 0 and items:
        # Find ATM strike (closest to spot)
        atm_item = min(items, key=lambda x: abs(x["strike_price"] - spot_price))
        atm_strike = atm_item["strike_price"]
        
        # Nifty strike interval is typically 50, but we'll use 150 points to cover ~3 strikes up/down
        strike_window = 150
        
        for item in items:
            if abs(item["strike_price"] - atm_strike) <= strike_window:
                near_call_chg += item.get("call_change_oi", 0) or 0
                near_put_chg += item.get("put_change_oi", 0) or 0

tracker.record_spot(now, spot_price)
tracker.record_oi(now, oi_resp)
report = tracker.report(now)

fut_q = upstox.get_quote(settings.NIFTY_FUT_KEY)
fut_vol = fut_q.get("volume", 0) if fut_q else 0
fut_oi = fut_q.get("oi", 0) if fut_q else 0

vol_baseline = 10000 

# --- 4. EVALUATION ---
regime_res = regime_factor.evaluate_regime(vix_ltp, vix_pct, wti_ltp, wti_pct, inr_pct)
oi_res = oi_factor.calculate_oi_score(oi_resp, spot_price)
vol_res = volume_factor.evaluate_volume_gate(fut_vol, fut_oi, fut_oi * 0.99, vol_baseline)
final_decision = confluence.resolve_confluence(oi_res, vol_res, regime_res)

# --- 5. MACRO GAP PREDICTOR ---
expected_nifty_pct = (wti_pct * -settings.CRUDE_WEIGHT) + (inr_pct * -settings.INR_WEIGHT)
gap_pct = expected_nifty_pct - spot_pct

# --- 6. LOGGING ---
log_row = {
    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    "nifty_spot": round(spot_price, 2), "nifty_chg": round(spot_chg, 2), "nifty_pct": round(spot_pct, 2),
    "vix_ltp": round(vix_ltp, 2), "vix_chg": round(vix_chg, 2), "vix_pct": round(vix_pct, 2),
    "wti_ltp": round(wti_ltp, 2), "wti_chg": round(wti_chg, 2), "wti_pct": round(wti_pct, 2),
    "inr_ltp": round(inr_ltp, 3), "inr_chg": round(inr_chg, 3), "inr_pct": round(inr_pct, 2),
    "fut_vol": fut_vol, 
    "fut_oi": fut_oi,
    "total_call_chg": total_call_chg,
    "total_put_chg": total_put_chg,
    "pcr": round(pcr, 2),
    "near_call_chg": near_call_chg,
    "near_put_chg": near_put_chg,
    "oi_score": round(oi_res["score"], 2),
    "volume_gate": vol_res["gate"],
    "regime_status": regime_res["trade_permission"],
    "final_action": final_decision["action"],
    "position_cap": final_decision["position_cap"],
    "reason": " | ".join(final_decision["reasons"])
}

is_weekday = now.weekday() < 5
is_market_hours = dt.time(9, 0) <= now.time() <= dt.time(16, 0)
if is_weekday and is_market_hours:
    log_book.save_log_to_github(log_row, st.secrets)

# --- 7. UI RENDER ---
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

# MACRO GAP ALERT LOGIC
if abs(gap_pct) > settings.GAP_THRESHOLD_PCT and is_market_hours:
    if gap_pct > 0:
        if vix_pct > 2.0:
            st.markdown(f'<div class="alert-box alert-trap">🛑 <b>TRAP ALERT (Rise Expected, but VIX is Spiking)</b><br>Macro implies Nifty should be up <b>{gap_pct:+.2f}%</b>. However, VIX is spiking <b>{vix_pct:+.2f}%</b>. Fear is increasing. Wait for VIX to cool down before buying.</div>', unsafe_allow_html=True)
        elif spot_pct < 0:
            st.markdown(f'<div class="alert-box alert-trap">🛑 <b>TRAP ALERT (Rise Expected, But Nifty is Falling)</b><br>Macro implies Nifty should be up <b>{gap_pct:+.2f}%</b>, but it is down <b>{spot_pct:.2f}%</b>. Be careful with shorts.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box alert-safe">🚨 <b>SAFE GAP ALERT (Rise Expected)</b><br>Macro implies Nifty should be up <b>{gap_pct:+.2f}%</b> more than its current move. VIX is calm ({vix_pct:+.2f}%). Look for Long setups.</div>', unsafe_allow_html=True)
    else:
        if vix_pct < -2.0:
            st.markdown(f'<div class="alert-box alert-trap">🛑 <b>TRAP ALERT (Drop Expected, but VIX is Falling)</b><br>Macro implies Nifty should be down <b>{gap_pct:+.2f}%</b>. However, VIX is dropping <b>{vix_pct:+.2f}%</b>. Fear is fading. Be careful with shorts.</div>', unsafe_allow_html=True)
        elif spot_pct > 0:
            st.markdown(f'<div class="alert-box alert-trap">🛑 <b>TRAP ALERT (Drop Expected, But Nifty is Rising)</b><br>Macro implies Nifty should be down <b>{gap_pct:+.2f}%</b>, but it is up <b>{spot_pct:.2f}%</b>. Be careful with longs.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-box alert-safe">🚨 <b>SAFE GAP ALERT (Drop Expected)</b><br>Macro implies Nifty should drop <b>{gap_pct:+.2f}%</b> more. VIX is supportive ({vix_pct:+.2f}%). Look for Short setups.</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="alert-box alert-info">⚪ <b>NIFTY & MACRO IN SYNC</b> — Gap is {gap_pct:+.2f}% (Threshold: {settings.GAP_THRESHOLD_PCT}%). VIX is at {vix_pct:+.2f}%. No catch-up trade available.</div>', unsafe_allow_html=True)

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

st.subheader("📊 Gap Calculation Breakdown")
g1, g2, g3 = st.columns(3)
g1.metric("WTI Impact", f"{wti_pct * -settings.CRUDE_WEIGHT:+.2f}%", "Bullish for Nifty" if wti_pct < 0 else "Bearish for Nifty", delta_color="normal")
g2.metric("INR Impact", f"{inr_pct * -settings.INR_WEIGHT:+.2f}%", "Bullish for Nifty" if inr_pct < 0 else "Bearish for Nifty", delta_color="normal")
g3.metric("Expected Nifty Move", f"{expected_nifty_pct:+.2f}%", f"Actual: {spot_pct:+.2f}%")

st.markdown("---")

col1, col2, col3, col4 = st.columns(4)
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
with col4:
    st.subheader("🎯 Near-ATM Change OI")
    st.caption(f"Call Chg: **{near_call_chg:+,}**")
    st.caption(f"Put Chg: **{near_put_chg:+,}**")
    st.caption(f"PCR: {pcr:.2f} | Vol: {fut_vol:,}")

st.markdown("---")
st.caption(f"Data Status: {report['reason']} | Last updated: {now.strftime('%H:%M:%S IST')}")
