# Stocks

Personal Wealthsimple trading data: pulled locally, analyzed for bad trades
and market dips, and rolled up into a dashboard. See
`~/dev/.claude/skills/stocks/SKILL.md` for how Claude drives this folder.

## Setup (one-time)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/auth.py   # interactive login, prompts for email/password/2FA
```

This uses [ws-api](https://github.com/gboudreau/ws-api-python), an
**unofficial** Wealthsimple client — not affiliated with or sanctioned by
Wealthsimple. Your password and 2FA code are typed at the terminal and never
written to disk; only the resulting session token is saved, in the macOS
Keychain (service name `wealthsimple-stocks-folder`), not in this repo.

## Workflow

```bash
.venv/bin/python scripts/fetch_data.py               # pull latest data from Wealthsimple
.venv/bin/python scripts/build_trades.py             # FIFO-match buys/sells into closed trades
.venv/bin/python scripts/detect_bad_trades.py        # flag quick losses, big losses, bad timing, overtrading
.venv/bin/python scripts/detect_dips.py              # find market/holding dips, check if you traded them
.venv/bin/python scripts/build_dashboard_snapshot.py # aggregate everything into dashboard/dashboard_data.json
.venv/bin/python scripts/render_dashboard_html.py    # inject that JSON into dashboard/dashboard.html
```

Then publish `dashboard/dashboard.html` via Claude's Artifact tool (ask Claude
to do this - it redeploys to the same URL on repeat runs).

## Data layout

```
data/
  raw/          # timestamped full API snapshots (JSON) - gitignored
  processed/    # derived CSVs - gitignored, all financial data lives here
    accounts.csv
    activities.csv        # full transaction history, deduped by canonicalId
    positions.csv         # dated snapshots of holdings
    realized_returns.csv
    dividends.csv
    trades.csv             # closed (buy+sell matched) trades with realized P&L
    open_positions.csv     # still-open lots
    bad_trade_flags.csv    # output of detect_bad_trades.py
    dip_events.csv         # output of detect_dips.py
journal/
  notes.md      # freeform trade rationale notes
dashboard/
  dashboard_template.html  # static template with a data placeholder - tracked in git
  dashboard_data.json      # snapshot embedded into the published dashboard - gitignored
  dashboard.html            # template + snapshot merged, ready to publish - gitignored
```

**Nothing under `data/` or `dashboard/dashboard_data.json` is committed to
git** — see `.gitignore`. This repo is local-only (not pushed anywhere); it
tracks the analysis code and journal notes, not the numbers.
