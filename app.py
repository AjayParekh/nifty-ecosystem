import streamlit as st
import datetime as dt
import pytz
import pandas as pd
from streamlit_autorefresh import st_autorefresh

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
.section-header { font-size: 1.2rem; font-weight: bold; margin-bottom: 10px; border-bottom: 2px solid #eee; padding-bottom: 5px; }
.executor-box { padding: 20px; border-radius: 12px; background-color: #f8f9fa; border: 2px dashed #007bff; margin-bottom: 20px; color: #111;}
.pnl-box { padding: 20px; border-radius: 12px; background-color: #2c3e50; color: white; border: 2px solid #1a252f; margin-bottom: 20px;}
</style>
""", unsafe_allow_html=True)

IST = pytz.timezone(settings.IST_TZ)
now = dt.datetime.now(IST)
LOT_SIZE = 65

# --- 2. INITIALIZATION ---
try:
    upstox.init(st.secrets["UPSTOX_TOKEN"])
except Exception as e:
    st.error(f"⚠️ **Setup Error:** {e}. Please check your Streamlit Secrets.")
    st.stop()

if "tracker" not in st.session_state:
    st.session_state.tracker = FreshnessTracker()
tracker = st.session_state.tracker

if "active_trade" not in st.session_state:
    st.session_state.active_trade = None

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

today_str = now.strftime('%Y-%m-%d')

# --- DYNAMIC EXPIRY FETCHING ---
if "nearest_expiry" not in st.session_state:
    contracts = upstox.get_option_contracts(settings.NIFTY_INDEX_KEY)
    valid_expiries = []
    for c in contracts:
        exp = c.get("expiry")
        if exp and exp >= today_str:
            valid_expiries.append(exp)
            
    if valid_expiries:
        st.session_state.nearest_expiry = sorted(valid_expiries)[0]
    else:
        st.session_state.nearest_expiry = today_str

expiry_date = st.session_state.nearest_expiry
oi_resp = upstox.get_change_oi(settings.NIFTY_INDEX_KEY, expiry_date, today_str)

# --- FETCHING OPTION CONTRACTS & GREEKS ---
strike_map = {}
if spot_price > 0:
    if "contracts" not in st.session_state:
        st.session_state.contracts = upstox.get_option_contracts(settings.NIFTY_INDEX_KEY)
    
    all_c = st.session_state.contracts
    valid_c = [c for c in all_c if c.get("expiry") == expiry_date and c.get("strike_price")]
    
    for c in valid_c:
        s = float(c["strike_price"])
        if s not in strike_map: strike_map[s] = {}
        strike_map[s][c["instrument_type"]] = c["instrument_key"]

    sorted_strikes = sorted(strike_map.keys())
    if sorted_strikes:
        atm_idx = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - spot_price))
        atm_strike = sorted_strikes[atm_idx]
        
        start_idx = max(0, atm_idx - 2)
        end_idx = min(len(sorted_strikes), atm_idx + 3)
        selected_strikes = sorted_strikes[start_idx:end_idx]
        
        greek_keys = []
        for s in selected_strikes:
            if "CE" in strike_map[s]: greek_keys.append(strike_map[s]["CE"])
            if "PE" in strike_map[s]: greek_keys.append(strike_map[s]["PE"])
            
        greeks_data = upstox.get_option_greeks(greek_keys)
        quotes_data = upstox.get_quotes_bulk(greek_keys) # Get LTPs for the 5 strikes
    else:
        atm_strike = 0
        greeks_data = {}
        quotes_data = {}
else:
    atm_strike = 0
    greeks_data = {}
    quotes_data = {}

# Calculate Totals, PCR, Near-ATM OI
total_call_chg = 0
total_put_chg = 0
total_call_oi = 0
total_put_oi = 0
pcr = 0.0
near_call_chg = 0
near_put_chg = 0

if oi_resp and oi_resp.get("status") == "success":
    data_block = oi_resp.get("data")
    if isinstance(data_block, list):
        items = data_block
    elif isinstance(data_block, dict):
        items = data_block.get("call_put_oi_data_list") or []
    else:
        items = []
    
    for item in items:
        total_call_chg += item.get("call_change_oi", 0) or 0
        total_put_chg += item.get("put_change_oi", 0) or 0
        total_call_oi += item.get("call_oi", 0) or 0
        total_put_oi += item.get("put_oi", 0) or 0
        
    if total_call_oi > 0 and total_put_oi > 0:
        pcr = total_put_oi / total_call_oi
    elif total_call_chg > 0 and total_put_chg > 0:
        pcr = total_put_chg / total_call_chg

    if spot_price > 0 and items:
        for item in items:
            if abs(item.get("strike_price", 0) - atm_strike) <= 150:
                near_call_chg += item.get("call_change_oi", 0) or 0
                near_put_chg += item.get("put_change_oi", 0) or 0

# --- DYNAMIC FUTURES KEY FETCHING ---
if "fut_key" not in st.session_state:
    f_key = upstox.get_nearest_futures_key("NIFTY")
    st.session_state.fut_key = f_key if f_key else settings.NIFTY_FUT_KEY
fut_key = st.session_state.fut_key

if fut_key:
    fut_q = upstox.get_quote(fut_key)
else:
    fut_q = None

fut_price = fut_q.get("last_price", 0) if fut_q else 0
fut_chg = fut_q.get("net_change", 0) if fut_q else 0
fut_pct = (fut_chg / max(fut_price - fut_chg, 1)) * 100 if fut_q else 0
fut_vol = fut_q.get("volume", 0) if fut_q else 0
fut_oi = fut_q.get("oi", 0) if fut_q else 0

if "prev_fut_oi" not in st.session_state:
    st.session_state.prev_fut_oi = fut_oi
prev_fut_oi = st.session_state.prev_fut_oi
st.session_state.prev_fut_oi = fut_oi

tracker.record_spot(now, spot_price)
tracker.record_oi(now, oi_resp)
report = tracker.report(now)

vol_baseline = 10000 

# --- 4. EVALUATION ---
expected_nifty_pct = (wti_pct * -settings.CRUDE_WEIGHT) + (inr_pct * -settings.INR_WEIGHT)
external_gap = expected_nifty_pct - spot_pct

regime_res = regime_factor.evaluate_regime(vix_ltp, vix_pct, wti_ltp, wti_pct, inr_pct)
oi_res = oi_factor.calculate_oi_score(oi_resp, spot_price)
vol_res = volume_factor.evaluate_volume_gate(fut_vol, fut_oi, prev_fut_oi, vol_baseline)
final_decision = confluence.resolve_confluence(oi_res, vol_res, regime_res)

# --- 5. TRADE EXECUTOR & P&L LOGIC ---
trade_action = "NONE"
trade_strike = 0
trade_type = "NONE"
entry_premium = 0
current_premium = 0
pnl_points = 0
pnl_inr = 0
pnl_pct = 0

# If a NEW CONFIRM signal fires, lock in the trade
if "CONFIRM" in final_decision["action"] and atm_strike > 0:
    trade_action = "BUY"
    trade_strike = atm_strike
    trade_type = "CE" if final_decision["action"] == "CONFIRM_BUY" else "PE"
    
    opt_key = strike_map.get(trade_strike, {}).get(trade_type)
    opt_ltp = quotes_data.get(opt_key, {}).get("last_price", 0) if opt_key else 0
    
    if opt_ltp > 0:
        # Check if we need to create a new trade (different strike/type or no active trade)
        if not st.session_state.active_trade or \
           st.session_state.active_trade["strike"] != trade_strike or \
           st.session_state.active_trade["type"] != trade_type:
            
            st.session_state.active_trade = {
                "strike": trade_strike,
                "type": trade_type,
                "entry_ltp": opt_ltp,
                "entry_time": now
            }

# If there is an active trade, calculate live PnL
if st.session_state.active_trade:
    t = st.session_state.active_trade
    trade_strike = t["strike"]
    trade_type = t["type"]
    entry_premium = t["entry_ltp"]
    
    opt_key = strike_map.get(trade_strike, {}).get(trade_type)
    # Fetch live LTP for the active trade option
    live_q = upstox.get_quote(opt_key) if opt_key else None
    current_premium = live_q.get("last_price", 0) if live_q else 0
    
    if current_premium > 0 and entry_premium > 0:
        pnl_points = current_premium - entry_premium
        pnl_inr = pnl_points * LOT_SIZE
        pnl_pct = (pnl_points / entry_premium) * 100
        trade_action = "ACTIVE"

# --- 6. ALERT STATUS DETERMINATION ---
alert_status = "IN_SYNC"
is_weekday = now.weekday() < 5
is_market_hours = dt.time(9, 0) <= now.time() <= dt.time(16, 0)

if abs(external_gap) > settings.GAP_THRESHOLD_PCT and is_market_hours:
    if external_gap > 0:
        if vix_pct > 2.0: alert_status = "TRAP_RISE_VIX_SPIKE"
        elif spot_pct < 0: alert_status = "TRAP_RISE_PRICE_FALLING"
        else: alert_status = "SAFE_GAP_RISE"
    else:
        if vix_pct < -2.0: alert_status = "TRAP_DROP_VIX_FALLING"
        elif spot_pct > 0: alert_status = "TRAP_DROP_PRICE_RISING"
        else: alert_status = "SAFE_GAP_DROP"

# --- 7. LOGGING ---
log_row = {
    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    "nifty_spot": round(spot_price, 2), "nifty_chg": round(spot_chg, 2), "nifty_pct": round(spot_pct, 2),
    "fut_price": round(fut_price, 2), "fut_chg": round(fut_chg, 2), "fut_pct": round(fut_pct, 2),
    "fut_vol": fut_vol, "fut_oi": fut_oi,
    "vix_ltp": round(vix_ltp, 2), "vix_chg": round(vix_chg, 2), "vix_pct": round(vix_pct, 2),
    "wti_ltp": round(wti_ltp, 2), "wti_chg": round(wti_chg, 2), "wti_pct": round(wti_pct, 2),
    "inr_ltp": round(inr_ltp, 3), "inr_chg": round(inr_chg, 3), "inr_pct": round(inr_pct, 2),
    "external_score": round(expected_nifty_pct, 2), "external_gap": round(external_gap, 2),
    "internal_score": round(oi_res["score"], 2),
    "atm_strike": atm_strike,
    "total_call_oi": total_call_oi, "total_put_oi": total_put_oi,
    "total_call_chg": total_call_chg, "total_put_chg": total_put_chg,
    "pcr": round(pcr, 2),
    "near_call_chg": near_call_chg, "near_put_chg": near_put_chg,
    "oi_score": round(oi_res["score"], 2),
    "vol_ratio": round(vol_res.get("ratio", 0), 2),
    "volume_gate": vol_res["gate"],
    "regime_status": regime_res["trade_permission"],
    "alert_status": alert_status,
    "trade_action": trade_action, "trade_strike": trade_strike, "trade_type": trade_type,
    "entry_premium": round(entry_premium, 2), "current_premium": round(current_premium, 2),
    "pnl_points": round(pnl_points, 2), "pnl_inr": round(pnl_inr, 2), "pnl_pct": round(pnl_pct, 2),
    "atm_ce_delta": round(greeks_data.get(strike_map.get(atm_strike, {}).get("CE"), {}).get("delta", 0) or 0, 3), 
    "atm_ce_theta": round(greeks_data.get(strike_map.get(atm_strike, {}).get("CE"), {}).get("theta", 0) or 0, 2), 
    "atm_ce_iv": round(greeks_data.get(strike_map.get(atm_strike, {}).get("CE"), {}).get("iv", 0) or 0, 2),
    "atm_pe_delta": round(greeks_data.get(strike_map.get(atm_strike, {}).get("PE"), {}).get("delta", 0) or 0, 3), 
    "atm_pe_theta": round(greeks_data.get(strike_map.get(atm_strike, {}).get("PE"), {}).get("theta", 0) or 0, 2), 
    "atm_pe_iv": round(greeks_data.get(strike_map.get(atm_strike, {}).get("PE"), {}).get("iv", 0) or 0, 2),
    "final_action": final_decision["action"],
    "position_cap": final_decision["position_cap"],
    "reason": " | ".join(final_decision["reasons"])
}

if is_weekday and is_market_hours:
    log_book.save_log_to_github(log_row, st.secrets)

# --- 8. UI RENDER ---
st.title("🎯 Nifty Ecosystem Dashboard")

def render_card(label, value, chg, pct, is_inr=False):
    cls = "pos" if chg >= 0 else "neg"
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "—"
    val_str = f"{value:,.2f}"
    if is_inr: val_str = f"{value:.3f}"
    chg_str = f"{arrow} {chg:+,.2f} ({pct:+.2f}%)"
    if is_inr: chg_str = f"{arrow} {chg:+.3f} ({pct:+.2f}%)"
    return f'<div class="card"><div class="metric-label">{label}</div><div class="big-price">{val_str}</div><div class="{cls}">{chg_str}</div></div>'

c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.markdown(render_card("Nifty Spot", spot_price, spot_chg, spot_pct), unsafe_allow_html=True)
with c2: st.markdown(render_card("Nifty Futures", fut_price, fut_chg, fut_pct), unsafe_allow_html=True)
with c3: st.markdown(render_card("India VIX", vix_ltp, vix_chg, vix_pct), unsafe_allow_html=True)
with c4: st.markdown(render_card("WTI Crude", wti_ltp, wti_chg, wti_pct), unsafe_allow_html=True)
with c5: st.markdown(render_card("USD/INR", inr_ltp, inr_chg, inr_pct, is_inr=True), unsafe_allow_html=True)

st.markdown("---")

if "TRAP" in alert_status:
    st.markdown(f'<div class="alert-box alert-trap">🛑 <b>{alert_status.replace("_", " ")}</b><br>Macro implies Nifty should move <b>{external_gap:+.2f}%</b>, but the Internal Flow is diverging. <b>DO NOT TRADE THE GAP.</b></div>', unsafe_allow_html=True)
elif "SAFE" in alert_status:
    st.markdown(f'<div class="alert-box alert-safe">🚨 <b>SAFE GAP ALERT</b><br>Macro implies Nifty should move <b>{external_gap:+.2f}%</b> more. <b>⚠️ WAIT for the Internal Engine to say CONFIRM.</b></div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="alert-box alert-info">⚪ <b>EXTERNAL MACRO IN SYNC</b> — Gap is {external_gap:+.2f}%.</div>', unsafe_allow_html=True)

action = final_decision["action"]
css_class = "neutral"
if "BUY" in action: css_class = "buy"
elif "SELL" in action: css_class = "sell"
elif action in ("WATCH", "VETO"): css_class = "wait"

st.markdown(f'<div class="decision-box {css_class}"><h1 style="margin:0; font-size: 3rem;">{action.replace("_", " ")}</h1><p style="font-size: 1.2rem; margin-top: 10px;">Direction: <b>{final_decision["direction"]}</b> | Position Size: <b>{final_decision["position_cap"] * 100:.0f}%</b></p></div>', unsafe_allow_html=True)

# --- TRADE EXECUTOR & P&L UI ---
if st.session_state.active_trade:
    t = st.session_state.active_trade
    pnl_color = "#28a745" if pnl_inr >= 0 else "#dc3545"
    pnl_sign = "+" if pnl_inr >= 0 else ""
    
    st.markdown(f"""
    <div class="pnl-box" style="border-color: {pnl_color};">
        <h3 style="margin-top:0;">🎯 ACTIVE TRADE: {t['type']} {t['strike']} (Entry: {t['entry_time'].strftime('%H:%M:%S')})</h3>
        <div style="display:flex; justify-content:space-between; font-size:1.2rem;">
            <div><b>Entry Premium:</b> ₹{entry_premium:.2f}</div>
            <div><b>Current Premium:</b> ₹{current_premium:.2f}</div>
            <div><b>Lot Size:</b> {LOT_SIZE}</div>
            <div style="color:{pnl_color};"><b>Live P&L:</b> {pnl_sign}₹{pnl_inr:,.2f} ({pnl_sign}{pnl_pct:.2f}%)</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
elif "CONFIRM" in action and atm_strike > 0:
    st.markdown("---")
    st.markdown("### 🎯 TRADE EXECUTOR (Actionable Setup)")
    sl_buffer = 20
    target_buffer = 40
    
    if action == "CONFIRM_BUY":
        rec_action = f"BUY {atm_strike} CE"
        sl_price = spot_price - sl_buffer
        target_price = spot_price + target_buffer
        color = "#28a745"
    elif action == "CONFIRM_SELL":
        rec_action = f"BUY {atm_strike} PE"
        sl_price = spot_price + sl_buffer
        target_price = spot_price - target_buffer
        color = "#dc3545"
        
    st.markdown(f"""
    <div class="executor-box" style="border-color: {color};">
        <h3 style="margin-top:0; color: {color};">{rec_action}</h3>
        <p style="font-size: 1.1rem; margin-bottom: 5px;"><b>Current Spot:</b> {spot_price:,.2f}</p>
        <p style="font-size: 1.1rem; margin-bottom: 5px;"><b>Stop Loss (Spot):</b> <span style="color:#dc3545; font-weight:bold;">{sl_price:,.2f}</span> ({sl_buffer} pts)</p>
        <p style="font-size: 1.1rem; margin-bottom: 5px;"><b>Target 1 (Spot):</b> <span style="color:#28a745; font-weight:bold;">{target_price:,.2f}</span> ({target_buffer} pts)</p>
    </div>
    """, unsafe_allow_html=True)

# --- GREEKS DISPLAY ---
st.markdown("---")
st.markdown("### 📊 Option Greeks (ATM Window)")
if sorted_strikes and greeks_data:
    ce_key_atm = strike_map.get(atm_strike, {}).get("CE")
    pe_key_atm = strike_map.get(atm_strike, {}).get("PE")
    ce_g = greeks_data.get(ce_key_atm, {})
    pe_g = greeks_data.get(pe_key_atm, {})
    
    c_delta = ce_g.get("delta", 0) or 0
    p_delta = pe_g.get("delta", 0) or 0
    gamma = ce_g.get("gamma", 0) or 0
    c_theta = ce_g.get("theta", 0) or 0
    p_theta = pe_g.get("theta", 0) or 0
    vega = ce_g.get("vega", 0) or 0
    c_iv = ce_g.get("iv", 0) or 0
    p_iv = pe_g.get("iv", 0) or 0
    skew = p_iv - c_iv
    
    greek_text = f"**ATM Greeks @ {atm_strike:,.0f}:** Δ Call/Put: {c_delta:.2f} / {p_delta:.2f} &nbsp;|&nbsp; Γ Gamma: {gamma:.5f} &nbsp;|&nbsp; Θ Theta C/P: {c_theta:.1f} / {p_theta:.1f} &nbsp;|&nbsp; V Vega: {vega:.2f} &nbsp;|&nbsp; IV Call/Put: {c_iv:.1f}% / {p_iv:.1f}% &nbsp;|&nbsp; IV skew (P−C): {skew:+.2f}"
    st.info(greek_text)
    
    greeks_table = []
    for s in selected_strikes:
        ce_k = strike_map[s].get("CE")
        pe_k = strike_map[s].get("PE")
        ce_d = greeks_data.get(ce_k, {})
        pe_d = greeks_data.get(pe_k, {})
        
        greeks_table.append({
            "Strike": s,
            "Type": "ATM" if s == atm_strike else ("ITM" if s < atm_strike else "OTM"),
            "CE Premium": quotes_data.get(ce_k, {}).get("last_price", 0),
            "CE Delta": ce_d.get("delta", 0),
            "CE Theta": ce_d.get("theta", 0),
            "CE IV": ce_d.get("iv", 0),
            "PE Premium": quotes_data.get(pe_k, {}).get("last_price", 0),
            "PE Delta": pe_d.get("delta", 0),
            "PE Theta": pe_d.get("theta", 0),
            "PE IV": pe_d.get("iv", 0),
            "IV Skew": (pe_d.get("iv", 0) or 0) - (ce_d.get("iv", 0) or 0),
        })
    st.dataframe(pd.DataFrame(greeks_table).style.format({"CE Premium": "{:.2f}", "PE Premium": "{:.2f}", "CE Delta": "{:.3f}", "PE Delta": "{:.3f}"}), use_container_width=True)
else:
    st.warning("Option Greeks data not available.")

st.markdown("### ⚖️ Engine Breakdown (Internal vs External)")
ecol1, ecol2 = st.columns(2)

with ecol1:
    st.markdown('<div class="section-header">🌍 External Engine (Macro)</div>', unsafe_allow_html=True)
    st.metric("WTI Impact", f"{wti_pct * -settings.CRUDE_WEIGHT:+.2f}%", "Bullish" if wti_pct < 0 else "Bearish", delta_color="normal")
    st.metric("INR Impact", f"{inr_pct * -settings.INR_WEIGHT:+.2f}%", "Bullish" if inr_pct < 0 else "Bearish", delta_color="normal")
    st.metric("Expected Nifty Move", f"{expected_nifty_pct:+.2f}%", f"Actual: {spot_pct:+.2f}%")

with ecol2:
    st.markdown('<div class="section-header">🔥 Internal Engine (Flow)</div>', unsafe_allow_html=True)
    st.write(f"**Status:** {regime_res['trade_permission']} | **OI Score:** {oi_res['score']:+.2f} | **Expiry:** {expiry_date}")
    st.markdown(f"""
    **VIX Status:** {vix_ltp:.2f} ({vix_pct:+.2f}%)  
    **Volume Gate:** {vol_res['gate']} ({vol_res.get('ratio', 0):.1f}x baseline)  
    **ATM Strike:** {atm_strike}  
    **Near-ATM Call ΔOI:** {near_call_chg:+,}  
    **Near-ATM Put ΔOI:** {near_put_chg:+,}  
    **Overall PCR:** {pcr:.2f}  
    **Futures Volume:** {fut_vol:,} | **Futures OI:** {fut_oi:,}
    """)

st.markdown("---")
st.caption(f"Data Status: {report['reason']} | Last updated: {now.strftime('%H:%M:%S IST')}")
