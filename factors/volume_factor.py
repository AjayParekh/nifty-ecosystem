"""
factors/volume_factor.py
"""
from config.settings import (
    VOL_RATIO_PASS, VOL_RATIO_WEAK, VOL_OI_CHANGE_MIN, VOL_OI_CHANGE_FLAT
)

def evaluate_volume_gate(current_vol, current_oi, prev_oi, vol_baseline):
    if current_vol is None or not vol_baseline:
        return {"gate": "FAIL", "reason": "Missing volume data", "ratio": 0.0}

    vol_ratio = current_vol / max(vol_baseline, 1.0)
    
    # If prev_oi is 0 or missing, we just rely on Volume Ratio
    if not prev_oi or prev_oi == 0:
        if vol_ratio >= VOL_RATIO_PASS:
            return {"gate": "PASS", "reason": f"High Volume ({vol_ratio:.1f}x). OI pending.", "ratio": vol_ratio}
        return {"gate": "FAIL", "reason": f"Low volume ({vol_ratio:.1f}x)", "ratio": vol_ratio}

    oi_change_pct = abs(current_oi - prev_oi) / max(prev_oi, 1.0)

    if vol_ratio >= VOL_RATIO_PASS:
        if oi_change_pct >= VOL_OI_CHANGE_MIN:
            return {"gate": "PASS", "reason": f"Volume {vol_ratio:.1f}x + OI moving", "ratio": vol_ratio}
        elif oi_change_pct < VOL_OI_CHANGE_FLAT:
            # Relaxed: If volume is > 5x, we give it a pass even if OI looks flat
            if vol_ratio > 5.0:
                return {"gate": "PASS", "reason": f"Massive Volume ({vol_ratio:.1f}x) overriding flat OI", "ratio": vol_ratio}
            return {"gate": "CHURN", "reason": f"Volume {vol_ratio:.1f}x but OI flat", "ratio": vol_ratio}
    
    if vol_ratio >= VOL_RATIO_WEAK:
        return {"gate": "WEAK", "reason": f"Moderate volume ({vol_ratio:.1f}x)", "ratio": vol_ratio}

    return {"gate": "FAIL", "reason": f"Low volume ({vol_ratio:.1f}x)", "ratio": vol_ratio}
