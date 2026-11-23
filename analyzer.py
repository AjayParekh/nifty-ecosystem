import pandas as pd
import requests
import io

LOT_SIZE = 65
TARGET_POINTS = 40
STOP_LOSS_POINTS = 20

def fetch_logs_from_github(secrets):
    token = secrets.get("GITHUB_LOG_TOKEN")
    repo = secrets.get("GITHUB_LOG_REPO")
    if not token or not repo:
        return pd.DataFrame()

    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.github.com/repos/{repo}/contents/logs"
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return pd.DataFrame()
            
        files = [f for f in res.json() if f["name"].endswith(".csv")]
        dfs = []
        
        for f in files:
            f_res = requests.get(f["download_url"], timeout=10)
            if f_res.status_code == 200:
                temp_df = pd.read_csv(io.StringIO(f_res.text))
                if "trade_action" in temp_df.columns and "pnl_points" in temp_df.columns:
                    dfs.append(temp_df)
                
        if not dfs:
            return pd.DataFrame()
            
        df = pd.concat(dfs, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return pd.DataFrame()

def analyze_trades(df):
    if df.empty or "trade_action" not in df.columns:
        return None, None, None

    active_df = df[df["trade_action"] == "ACTIVE"].copy()
    if active_df.empty:
        return None, None, None

    active_df["trade_id"] = (active_df["trade_strike"] != active_df["trade_strike"].shift()) | \
                            (active_df["trade_type"] != active_df["trade_type"].shift()) | \
                            (active_df["timestamp"].diff().dt.total_seconds() > 300)
    active_df["trade_id"] = active_df["trade_id"].cumsum()

    trades_summary = []
    
    for trade_id, group in active_df.groupby("trade_id"):
        entry_time = group["timestamp"].iloc[0]
        strike = group["trade_strike"].iloc[0]
        t_type = group["trade_type"].iloc[0]
        entry_prem = group["entry_premium"].iloc[0]
        
        delta = abs(group["atm_ce_delta"].iloc[0]) if t_type == "CE" else abs(group["atm_pe_delta"].iloc[0])
        iv = group["atm_ce_iv"].iloc[0] if t_type == "CE" else group["atm_pe_iv"].iloc[0]
        gap = group["external_gap"].iloc[0]
        
        max_pnl = group["pnl_points"].max()
        min_pnl = group["pnl_points"].min()
        
        hit_target = max_pnl >= TARGET_POINTS
        hit_sl = min_pnl <= -STOP_LOSS_POINTS
        
        outcome = "NEUTRAL"
        realized_pnl = group["pnl_points"].iloc[-1]
        
        if hit_target and not hit_sl:
            outcome = "WIN"
            realized_pnl = TARGET_POINTS
        elif hit_sl and not hit_target:
            outcome = "LOSS"
            realized_pnl = -STOP_LOSS_POINTS
        elif hit_target and hit_sl:
            idx_max = group["pnl_points"].idxmax()
            idx_min = group["pnl_points"].idxmin()
            if idx_max < idx_min:
                outcome = "WIN"
                realized_pnl = TARGET_POINTS
            else:
                outcome = "LOSS"
                realized_pnl = -STOP_LOSS_POINTS
                
        trades_summary.append({
            "Date": entry_time.strftime("%Y-%m-%d"),
            "Time": entry_time.strftime("%H:%M"),
            "Hour": entry_time.hour,
            "Type": t_type,
            "Strike": strike,
            "Entry Premium": entry_prem,
            "Outcome": outcome,
            "P&L (INR)": realized_pnl * LOT_SIZE,
            "Entry Delta": delta,
            "Entry IV": iv,
            "Entry Gap": gap
        })

    trades_df = pd.DataFrame(trades_summary)
    
    # Summary
    wins = len(trades_df[trades_df["Outcome"] == "WIN"])
    losses = len(trades_df[trades_df["Outcome"] == "LOSS"])
    win_rate = (wins / len(trades_df)) * 100 if len(trades_df) > 0 else 0
    total_pnl = trades_df["P&L (INR)"].sum()
    
    summary = {
        "total_trades": len(trades_df),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl
    }
    
    # --- PREDICTIVE EDGE ANALYSIS ---
    edges = {}
    
    if len(trades_df) > 1:
        # 1. Time of Day Edge
        trades_df["Time_Block"] = pd.cut(trades_df["Hour"], 
                                         bins=[0, 10, 12, 14, 24], 
                                         labels=["Morning (9-10)", "Midday (10-12)", "Afternoon (12-2)", "Late (2-4)"])
        time_edge = trades_df.groupby("Time_Block", observed=True).apply(
            lambda x: pd.Series({
                "Trades": len(x), 
                "Win Rate": (len(x[x["Outcome"] == "WIN"]) / len(x)) * 100 if len(x) > 0 else 0,
                "P&L (INR)": x["P&L (INR)"].sum()
            })
        ).reset_index()
        edges["time"] = time_edge

        # 2. Gap Size Edge
        trades_df["Gap_Block"] = pd.cut(trades_df["Entry Gap"].abs(), 
                                        bins=[0, 0.5, 1.0, 100], 
                                        labels=["< 0.5%", "0.5% - 1.0%", "> 1.0%"])
        gap_edge = trades_df.groupby("Gap_Block", observed=True).apply(
            lambda x: pd.Series({
                "Trades": len(x), 
                "Win Rate": (len(x[x["Outcome"] == "WIN"]) / len(x)) * 100 if len(x) > 0 else 0,
                "P&L (INR)": x["P&L (INR)"].sum()
            })
        ).reset_index()
        edges["gap"] = gap_edge

        # 3. Delta Edge
        trades_df["Delta_Block"] = pd.cut(trades_df["Entry Delta"], 
                                          bins=[0, 0.4, 0.55, 1.0], 
                                          labels=["< 0.40 (OTM)", "0.40 - 0.55 (ATM)", "> 0.55 (ITM)"])
        delta_edge = trades_df.groupby("Delta_Block", observed=True).apply(
            lambda x: pd.Series({
                "Trades": len(x), 
                "Win Rate": (len(x[x["Outcome"] == "WIN"]) / len(x)) * 100 if len(x) > 0 else 0,
                "P&L (INR)": x["P&L (INR)"].sum()
            })
        ).reset_index()
        edges["delta"] = delta_edge

    return trades_df, summary, edges
