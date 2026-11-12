"""
factors/volume_factor.py

L2 — Volume Gate.
Validates OI changes with volume. OI alone can be misleading (e.g., churn).
A signal is only valid if Volume is high AND OI is genuinely changing.
"""
from config.settings import (
    VOL_RATIO_PASS,
    VOL_RATIO_WEAK,
    VOL_OI_CHANGE_MIN,
    VOL_OI_CHANGE_FLAT
)

def evaluate_volume_gate(current_vol, current_oi, prev_oi, vol_baseline):
    """
    Evaluates if the current volume and OI change support a valid trade.
    
    Returns a dict:
      gate: "PASS" (strong), "WEAK" (not enough), "CHURN" (volume up but OI flat), "FAIL" (missing data)
      reason: string explaining the decision
      ratio: volume ratio vs baseline
    """
    if current_vol is None or current_oi is None or prev_oi is None or not vol_baseline:
        return {
            "gate": "FAIL",
            "reason": "Missing volume or OI data",
            "ratio": 0.0
        }

    # 1. Calculate Volume Ratio
    vol_ratio = current_vol / max(vol_baseline, 1.0)
    
    # 2. Calculate OI Change Percentage
    oi_change_abs = abs(current_oi - prev_oi)
    oi_change_pct = oi_change_abs / max(prev_oi, 1.0)

    # 3. Apply Gate Logic
    if vol_ratio >= VOL_RATIO_PASS:
        if oi_change_pct >= VOL_OI_CHANGE_MIN:
            return {
                "gate": "PASS",
                "reason": f"High volume ({vol_ratio:.1f}x) + OI moving ({oi_change_pct*100:.1f}%)",
                "ratio": vol_ratio
            }
        elif oi_change_pct < VOL_OI_CHANGE_FLAT:
            return {
                "gate": "CHURN",
                "reason": f"High volume ({vol_ratio:.1f}x) but OI is flat ({oi_change_pct*100:.1f}%) — Churn",
                "ratio": vol_ratio
            }
    
    if vol_ratio >= VOL_RATIO_WEAK:
        return {
            "gate": "WEAK",
            "reason": f"Moderate volume ({vol_ratio:.1f}x) — insufficient conviction",
            "ratio": vol_ratio
        }

    return {
        "gate": "FAIL",
        "reason": f"Low volume ({vol_ratio:.1f}x)",
        "ratio": vol_ratio
    }
