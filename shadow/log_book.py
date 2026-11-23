"""
shadow/log_book.py
Handles saving the daily logs to a private GitHub repository.
Uses a unique session ID to prevent conflicts when multiple machines are open.
"""
import base64
import csv
import datetime as dt
import io
import requests
import time
import random

COLUMNS = [
    "timestamp", 
    "nifty_spot", "nifty_chg", "nifty_pct",
    "fut_price", "fut_chg", "fut_pct", "fut_vol", "fut_oi",
    "vix_ltp", "vix_chg", "vix_pct",
    "wti_ltp", "wti_chg", "wti_pct",
    "inr_ltp", "inr_chg", "inr_pct",
    "external_score", "external_gap",
    "internal_score",
    "atm_strike",
    "total_call_oi", "total_put_oi", 
    "total_call_chg", "total_put_chg", "pcr",
    "near_call_chg", "near_put_chg",
    "oi_score", "vol_ratio", "volume_gate", "regime_status", 
    "alert_status",
    "trade_action", "trade_strike", "trade_type",
    "entry_premium", "current_premium", 
    "pnl_points", "pnl_inr", "pnl_pct",
    "atm_ce_delta", "atm_ce_theta", "atm_ce_iv", "atm_ce_vol",
    "atm_pe_delta", "atm_pe_theta", "atm_pe_iv", "atm_pe_vol",
    "final_action", "position_cap", "reason"
]

def _get_github_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

def save_log_to_github(row_dict, secrets, session_id="main"):
    """
    Appends a row to a session-specific CSV file on GitHub.
    """
    try:
        token = secrets["GITHUB_LOG_TOKEN"]
        repo = secrets["GITHUB_LOG_REPO"]
    except KeyError:
        return "Missing GitHub secrets"

    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    # Use session ID to prevent conflicts
    file_path = f"logs/{date_str}_session_{session_id}.csv"
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = _get_github_headers(token)

    max_retries = 3
    for attempt in range(max_retries):
        time.sleep(random.uniform(0.1, 0.3))

        r = requests.get(url, headers=headers)
        sha = None
        existing_rows = []
        
        if r.status_code == 200:
            data = r.json()
            sha = data["sha"]
            content = base64.b64decode(data["content"]).decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            existing_rows = list(reader)
        elif r.status_code != 404:
            return f"GitHub read error: {r.status_code}"

        existing_rows.append(row_dict)

        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(existing_rows)
        new_content = out.getvalue()

        payload = {
            "message": f"Log update for {date_str} (Session {session_id})",
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha

        r_put = requests.put(url, headers=headers, json=payload)
        
        if r_put.status_code in (200, 201):
            return "Success"
        elif r_put.status_code == 409:
            continue
        else:
            return f"GitHub write error: {r_put.status_code}"

    return "Failed after max retries"
