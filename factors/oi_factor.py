"""
factors/oi_factor.py

L2 — OI Directional Score. 
Reads the change-in-OI response and calculates a score from -1.0 to +1.0.
Negative = Bearish (Call buildup / Put unwinding)
Positive = Bullish (Put buildup / Call unwinding)

This keeps your original logic but packages it cleanly.
"""
import math
from config.settings import OI_TOP_STRIKES

def calculate_oi_score(change_oi_response, spot_price):
    """
    Parses the Upstox change-OI response and returns a directional score.
    Returns: dict with 'score' (float -1.0 to 1.0), 'reasons' (list), and 'available' (bool).
    """
    if not change_oi_response or change_oi_response.get("status") != "success":
        return {"score": 0.0, "reasons": ["Change OI data unavailable"], "available": False}
    
    data = change_oi_response.get("data") or {}
    items = data.get("call_put_oi_data_list") or []
    if not items:
        return {"score": 0.0, "reasons": ["Empty strike list"], "available": False}

    # Filter out strikes with no OI change
    valid_items = []
    for item in items:
        call_chg = item.get("call_change_oi", 0) or 0
        put_chg = item.get("put_change_oi", 0) or 0
        diff = abs(put_chg - call_chg)
        if diff > 0:
            valid_items.append({
                "strike": item["strike_price"],
                "call_chg": call_chg,
                "put_chg": put_chg,
                "diff": diff,
                "type": "HIGH PUT" if put_chg > call_chg else "HIGH CALL"
            })

    if not valid_items:
        return {"score": 0.0, "reasons": ["No net OI change found"], "available": True}

    # Sort by the largest change difference
    valid_items.sort(key=lambda x: x["diff"], reverse=True)
    top_strikes = valid_items[:OI_TOP_STRIKES]

    # Calculate raw net change (Put change - Call change)
    # Bullish if Put > Call, Bearish if Call > Put
    total_diff = sum(item["put_chg"] - item["call_chg"] for item in top_strikes)
    
    # Calculate a max theoretical difference for normalization
    max_possible = sum(item["diff"] for item in top_strikes)
    
    if max_possible == 0:
        raw_score = 0.0
    else:
        raw_score = total_diff / max_possible
        
    # Clip to [-1.0, 1.0]
    final_score = max(-1.0, min(1.0, raw_score))
    
    reasons = []
    if final_score > 0.2:
        reasons.append("Bullish OI shift (Put writing > Call writing)")
    elif final_score < -0.2:
        reasons.append("Bearish OI shift (Call writing > Put writing)")
    else:
        reasons.append("Neutral OI shift")

    return {
        "score": final_score,
        "reasons": reasons,
        "available": True,
        "top_strikes": top_strikes
    }
