# Nifty Ecosystem

A layered Nifty trading-decision system.

## Architecture

| Layer | Purpose |
|---|---|
| L0 — Freshness | Never treat stale data as zero |
| L1 — Regime    | VIX + crude band + INR decide ALLOW / CAUTION / VETO |
| L2 — Direction | OI directional score + volume gate |
| L3 — Confluence| Merge layers, output final action + position cap |
| L4 — Shadow    | Log every alert; evaluate 5/10/15-min outcomes |

**Key rule:** macro factors (crude, INR) can only VETO. They never flip direction.

## Deployment

1. Push this repo to GitHub (public).
2. Streamlit Cloud → New app → connect this repo → **Advanced settings → Secrets** → paste your real tokens there.
3. Never commit `secrets.toml` to this repo — it is gitignored.
