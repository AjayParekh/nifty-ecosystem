"""
config/settings.py

Single source of truth for every numeric threshold in the Nifty ecosystem.
Never hardcode a number in a logic file — put it here and import it.
"""

# ============================================================
# 1. TIMING
# ============================================================
IST_TZ = "Asia/Kolkata"
MARKET_OPEN = (9, 15)          # 09:15 IST
MARKET_CLOSE = (15, 30)        # 15:30 IST
AVOID_OPENING_MIN = 15         # no trade in the first 15 minutes
AVOID_CLOSING_MIN = 30         # no trade in the last 30 minutes

# ============================================================
# 2. UPSTOX INSTRUMENTS
# ============================================================
NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"
NIFTY_FUT_KEY   = "NSE_FO|NIFTY"
INDIA_VIX_KEY   = "NSE_INDEX|India VIX"

# ============================================================
# 3. DATA FRESHNESS (L0 layer)
# ============================================================
SPOT_STALE_SEC   = 20          # spot older than this = STALE
OI_STALE_SEC     = 30          # change-OI older than this = STALE
VOLUME_STALE_SEC = 30          # volume snapshot older than this = STALE
SPOT_BUFFER_MIN  = 90          # keep this many minutes of spot samples

# ============================================================
# 4. OI DIRECTIONAL SCORE (L2 — keep your existing formula)
# ============================================================
OI_TOP_STRIKES      = 5
OI_ITM_COUNT        = 3
OI_STRIKE_WINDOW    = 20
OI_MIN_LIQUIDITY    = 500
OI_MIN_NET_CHG      = 100
OI_DELTA_BAND       = (0.15, 0.75)
OI_MIN_DOMINANCE    = 1.3

# ============================================================
# 5. VOLUME GATE (L2)
# ============================================================
VOL_LOOKBACK_SNAPSHOTS = 12
VOL_BASELINE_MIN_SNAP  = 6
VOL_RATIO_PASS         = 1.5
VOL_RATIO_WEAK         = 1.0
VOL_OI_CHANGE_MIN      = 0.02
VOL_OI_CHANGE_FLAT     = 0.01

# ============================================================
# 6. REGIME LAYER (L1) — VIX
# ============================================================
VIX_COMPLACENT_MAX = 14.0
VIX_NORMAL_MAX     = 20.0
VIX_PANIC_MAX      = 28.0
VIX_SPIKE_PCT      = 8.0       # intraday % rise that flags "panic shift"
VIX_EASING_PCT     = -5.0      # intraday % fall that flags "panic easing"

# ============================================================
# 7. REGIME LAYER (L1) — CRUDE OIL BAND
# ============================================================
CRUDE_LOW_BAND  = 80.0         # below = positive for India
CRUDE_HIGH_BAND = 100.0        # above = negative for India
CRUDE_HARD_VETO = 110.0        # crude this high = hard veto bullish Nifty
CRUDE_INR_COUPLING = 0.7       # ~70% of a simultaneous MCX move is "INR-driven"

# ============================================================
# 8. REGIME LAYER (L1) — USD/INR
# ============================================================
INR_STRONG_PCT = -0.15
INR_WEAK_PCT   =  0.15
INR_PANIC_PCT  =  0.35

# ============================================================
# 9. POSITION CAP TABLE (L3 confluence output)
# ============================================================
POSITION_CAP_FULL = 1.0
POSITION_CAP_HALF = 0.5
POSITION_CAP_NONE = 0.0

# ============================================================
# 10. FINAL DECISION THRESHOLDS (L3)
# ============================================================
CONFIRM_MIN_RAW_SCORE = 0.25
WATCH_MIN_RAW_SCORE   = 0.10

# ============================================================
# 11. SHADOW LOG (L4)
# ============================================================
LOG_DIR              = "logs"
LOG_RETENTION_DAYS   = 30
SHADOW_MODE          = True    # flip to False after 3 shadow days
GITHUB_PUSH_INTERVAL = 60
OUTCOME_HORIZONS_MIN = (5, 10, 15)

# ============================================================
# 12. STREAMLIT UI
# ============================================================
UI_REFRESH_SEC    = 15
UI_TABLE_TOP_N    = 20
UI_STRIKE_DISPLAY = 15
