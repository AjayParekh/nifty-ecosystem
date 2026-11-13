"""
shadow/log_book.py
Handles saving the daily logs to a private GitHub repository.
"""
import base64
import csv
import datetime as dt
import io
import requests

COLUMNS = [
    "timestamp", 
    "nifty_spot", "nifty_chg", "nifty_pct",
    "fut_price", "fut_chg", "fut_pct", "fut_vol", "fut_oi",
    "vix_ltp", "vix_chg", "vix_pct",
    "wti_ltp", "wti_chg", "wti_pct",
    "inr_ltp", "inr_chg", "inr_pct",
    "expected_nifty_pct", "gap_pct",
    "atm_strike",
    "total_call_oi", "total_put_oi", 
    "total_call_chg", "total_put_chg", "pcr",
    "near_call_chg", "near_put_chg",
    "oi_score", "vol_ratio", "volume_gate", "regime_status", 
    "final_action", "position_cap", "reason"
]
def _get_github_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

def save_log_to_github(row_dict, secrets):
    """
    Appends a row to today's CSV file on GitHub.
    Expects secrets to contain: GITHUB_LOG_TOKEN, GITHUB_LOG_REPO
    """
    try:
        token = secrets["GITHUB_LOG_TOKEN"]
        repo = secrets["GITHUB_LOG_REPO"]
    except KeyError:
        return "Missing GitHub secrets"

    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    file_path = f"logs/{date_str}_nifty_log.csv"
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = _get_github_headers(token)

    # 1. Try to get existing file to append
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

    # 2. Append new row
    existing_rows.append(row_dict)

    # 3. Create new CSV content
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(existing_rows)
    new_content = out.getvalue()

    # 4. Push back to GitHub
    payload = {
        "message": f"Log update for {date_str}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    r_put = requests.put(url, headers=headers, json=payload)
    if r_put.status_code in (200, 201):
        return "Success"
    else:
        return f"GitHub write error: {r_put.status_code}"
