"""
factors/regime_factor.py

L1 — Regime filter. Decides ALLOW / CAUTION / VETO based on macro backdrop.
Macro NEVER flips direction. It only restricts or shrinks position size.
"""
from config.settings import (
    VIX_PANIC_MAX, VIX_SPIKE_PCT,
    CRUDE_LOW_BAND, CRUDE_HIGH_BAND, CRUDE_HARD_VETO,
    INR_WEAK_PCT, INR_PANIC_PCT,
    POSITION_CAP_FULL, POSITION_CAP_HALF, POSITION_CAP_NONE
)

def evaluate_regime(vix_ltp, vix_pct, wti_ltp, wti_pct, inr_pct):
    """
    Evaluates the macro environment.
    Returns a dictionary with trade_permission, position_cap, and reasons.
    """
    reasons = []
    permission = "ALLOW"
    pos_cap = POSITION_CAP_FULL

    # 1. VIX Filter (Panic = No Trade)
    if vix_ltp is not None:
        if vix_ltp >= VIX_PANIC_MAX:
            permission = "VETO"
            pos_cap = POSITION_CAP_NONE
            reasons.append(f"VIX EXTREME ({vix_ltp:.1f}) — cash only")
        elif vix_pct and vix_pct >= VIX_SPIKE_PCT:
            if permission != "VETO":
                permission = "CAUTION"
                pos_cap = min(pos_cap, POSITION_CAP_HALF)
            reasons.append(f"VIX spiking intraday (+{vix_pct:.1f}%)")

    # 2. Crude Oil Filter (Too high = Inflation = Bad for Nifty)
    if wti_ltp is not None:
        if wti_ltp >= CRUDE_HARD_VETO:
            permission = "VETO"
            pos_cap = POSITION_CAP_NONE
            reasons.append(f"Crude critical (${wti_ltp:.1f}) — hard veto on longs")
        elif wti_ltp > CRUDE_HIGH_BAND:
            if permission == "ALLOW":
                permission = "CAUTION"
                pos_cap = POSITION_CAP_HALF
            reasons.append(f"Crude high (${wti_ltp:.1f}) — import pressure")
        elif wti_ltp < CRUDE_LOW_BAND:
            reasons.append(f"Crude low (${wti_ltp:.1f}) — positive for Nifty")

    # 3. USD/INR Filter (Rupee crashing = FII outflows = Bad for Nifty)
    if inr_pct is not None:
        if inr_pct >= INR_PANIC_PCT:
            permission = "VETO"
            pos_cap = POSITION_CAP_NONE
            reasons.append(f"INR panic ({inr_pct:+.2f}%) — massive FII selling risk")
        elif inr_pct >= INR_WEAK_PCT:
            if permission == "ALLOW":
                permission = "CAUTION"
                pos_cap = POSITION_CAP_HALF
            reasons.append(f"INR weak ({inr_pct:+.2f}%)")

    return {
        "trade_permission": permission,
        "position_cap": pos_cap,
        "reasons": reasons
    }
