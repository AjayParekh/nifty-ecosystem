"""
factors/confluence.py

L3 — Confluence Engine.
Takes the outputs from Regime, OI, and Volume, and makes the final trading decision.
This is the "Judge" that ensures all layers agree before a signal is confirmed.
"""
from config.settings import (
    CONFIRM_MIN_RAW_SCORE,
    WATCH_MIN_RAW_SCORE,
    POSITION_CAP_NONE
)

def resolve_confluence(oi_res, vol_res, regime_res):
    """
    Combines the three layers into a single actionable output.
    
    Returns:
        dict: {
            "action": "CONFIRM_BUY" | "CONFIRM_SELL" | "WATCH" | "VETO" | "NEUTRAL",
            "direction": "BULLISH" | "BEARISH" | "NONE",
            "position_cap": float (0.0 to 1.0),
            "reasons": list of strings explaining the decision
        }
    """
    reasons = []
    
    # 1. Regime Check (Highest Priority)
    if regime_res["trade_permission"] == "VETO":
        reasons.extend(regime_res["reasons"])
        reasons.append("VETOED by Macro Regime")
        return {
            "action": "VETO",
            "direction": "NONE",
            "position_cap": POSITION_CAP_NONE,
            "reasons": reasons
        }
        
    # 2. Data Availability Check
    if not oi_res["available"] or vol_res["gate"] == "FAIL":
        reasons.append("Insufficient data (OI or Volume missing)")
        return {
            "action": "NEUTRAL",
            "direction": "NONE",
            "position_cap": POSITION_CAP_NONE,
            "reasons": reasons
        }

    oi_score = oi_res["score"]
    vol_gate = vol_res["gate"]
    
    # 3. Evaluate Direction based on OI
    direction = "NONE"
    if oi_score >= CONFIRM_MIN_RAW_SCORE:
        direction = "BULLISH"
    elif oi_score <= -CONFIRM_MIN_RAW_SCORE:
        direction = "BEARISH"
        
    # 4. Check if we are in the WATCH zone (weaker signal)
    if direction == "NONE" and abs(oi_score) >= WATCH_MIN_RAW_SCORE:
        reasons.append(f"Weak OI direction ({oi_score:+.2f}) — watching")
        return {
            "action": "WATCH",
            "direction": "BULLISH" if oi_score > 0 else "BEARISH",
            "position_cap": regime_res["position_cap"],
            "reasons": reasons
        }
    elif direction == "NONE":
        reasons.append("OI is completely flat/neutral")
        return {
            "action": "NEUTRAL",
            "direction": "NONE",
            "position_cap": POSITION_CAP_NONE,
            "reasons": reasons
        }

    # 5. Volume Gate Check
    if vol_gate == "CHURN":
        reasons.append(f"Volume is high but OI is flat — CHURN detected.")
        reasons.append(vol_res["reason"])
        return {
            "action": "VETO",
            "direction": direction,
            "position_cap": POSITION_CAP_NONE,
            "reasons": reasons
        }
    elif vol_gate == "WEAK":
        reasons.append(f"Volume confirmation is weak.")
        reasons.append(vol_res["reason"])
        return {
            "action": "WATCH",
            "direction": direction,
            "position_cap": regime_res["position_cap"],
            "reasons": reasons
        }

    # 6. If we reach here, everything is passing!
    # OI is strong, Volume is PASS, Regime is ALLOW or CAUTION.
    reasons.extend(oi_res["reasons"])
    reasons.extend(regime_res["reasons"])
    reasons.append(vol_res["reason"])
    
    action = "CONFIRM_BUY" if direction == "BULLISH" else "CONFIRM_SELL"
    
    if regime_res["trade_permission"] == "CAUTION":
        reasons.append("Macro is CAUTION — trading at half size.")

    return {
        "action": action,
        "direction": direction,
        "position_cap": regime_res["position_cap"],
        "reasons": reasons
    }
