---
name: stocks
description: Tracks the user's Wealthsimple portfolio - refreshing trading data, rebuilding the trade ledger, flagging bad trades, finding market dips, screening stocks for valuation/earnings, and publishing the portfolio dashboard. Use when the user mentions Wealthsimple, their portfolio, holdings, trades, wants fresh data or the dashboard refreshed/reloaded, asks whether a stock is cheap or expensive, asks about dips, earnings, or their watchlist.
---

# Stocks / Portfolio Tracking

Everything lives in `~/dev/stocks/`, a local-only git repo (never pushed).
Data comes from Wealthsimple via the unofficial `ws-api` library
(github.com/gboudreau/ws-api-python), read-only scope. Market data and
fundamentals come from Yahoo Finance via `yfinance`.

If you publish the dashboard as an artifact, record its URL and always
redeploy to that same URL rather than creating a new one.

## Refreshing the dashboard — the main workflow

**Always start by checking the session, and prompt the user to authenticate
if it's expired.** Never try to log in on their behalf.

1. Check whether the saved session still works. This never prompts, so it's
   safe to run yourself:

   ```bash
   cd ~/dev/stocks && .venv/bin/python scripts/check_auth.py
   ```

2. **If it exits non-zero (`NEEDS_AUTH`)**, stop and ask the user to
   authenticate in their own terminal. Give them this exact line and wait for
   them to confirm — the `!` prefix runs it in their terminal so the password
   and 2FA code never pass through the conversation:

   ```
   ! cd ~/dev/stocks && .venv/bin/python scripts/auth.py
   ```

   Tell them it will ask for their Wealthsimple email, password, and 2FA
   code. Don't proceed until they say it's done.

3. Once the session is valid, run the whole pipeline yourself:

   ```bash
   cd ~/dev/stocks && .venv/bin/python scripts/refresh_all.py
   ```

   It re-checks auth first, then runs fetch → trades → bad trades → dips →
   watchlist → snapshot → render. Add `--skip-watchlist` when the user only
   wants portfolio numbers refreshed; the screener is the slow part (~2-4 min,
   one Yahoo Finance round trip per symbol).

4. Publish `dashboard/dashboard.html` with the Artifact tool, passing the
   artifact URL from project memory so it updates in place.

5. Tell the user what actually changed — new flagged trades, valuation moves,
   upcoming earnings — not just "done."

## Credentials — hard rule

**Never ask for the user's Wealthsimple password, 2FA code, or TOTP secret in
chat, and never type one on their behalf.** Only the session token is stored,
in the macOS Keychain (service `wealthsimple-stocks-folder`), and only by the
user running `auth.py` themselves. If a session expires mid-task, stop and
ask them to re-run it — never attempt a workaround.

The OAuth scope is read-only (`invest.read trade.read tax.read`). Keep it
that way: nothing here should ever be able to place a trade or move money.

## Data layout

```
stocks/
  watchlist.txt   # symbols to screen but not own - user-editable, tracked in git
  scripts/
    auth.py                      # interactive login (USER runs this, not you)
    check_auth.py                 # is the session valid? exit 0/1, never prompts
    refresh_all.py                # the whole pipeline, one command
    fetch_data.py                 # Wealthsimple -> data/raw + data/processed
    market_data.py                # shared Yahoo symbol resolver (TSX suffixes, crypto -USD)
    build_trades.py               # activities -> FIFO-matched closed trades
    detect_bad_trades.py          # trades -> bad_trade_flags.csv
    detect_dips.py                # benchmarks + held symbols -> dip_events.csv
    build_watchlist.py            # valuation percentiles, dips, earnings
    build_dashboard_snapshot.py   # everything -> dashboard/dashboard_data.json
    render_dashboard_html.py      # template + data -> dashboard/dashboard.html
  data/raw/         # timestamped raw API snapshots - gitignored
  data/processed/   # derived CSVs - gitignored
  journal/notes.md  # freeform trade rationale, newest on top
  dashboard/
    dashboard_template.html  # page shell + CSS/JS - tracked, contains no data
    dashboard_data.json      # generated snapshot - gitignored
    dashboard.html            # merged, ready to publish - gitignored
```

`data/` and anything with real dollar figures is gitignored. Never suggest
committing or pushing it.

## Other workflows

- **Bad trades review**: read `data/processed/bad_trade_flags.csv`, explain
  each flag in plain language, and offer to record the reasoning in
  `journal/notes.md`. Flags are prompts, not verdicts — `sold_too_early` just
  means the stock kept running, not that selling was wrong.
- **Dips review**: `data/processed/dip_events.csv`, with the `your_activity`
  column showing whether they bought in, sold, or sat it out.
- **Watchlist changes**: edit `watchlist.txt` (one ticker per line, `#`
  comments), then re-run `build_watchlist.py` and rebuild the dashboard.
- **Design changes**: load the `dataviz` skill first, then edit
  `dashboard_template.html`. Never hand-edit `dashboard_data.json` — it's
  fully generated.

## Valuation screener — hard rules

- **You are not a licensed financial advisor and must not give personalized
  investment advice.** The screener is a data tool: it reports where a
  multiple sits in its own history, how far a price is off its high, and what
  earnings did. Keep labels descriptive ("near its cheapest", "above its
  usual") — never directive ("buy", "undervalued", "a good entry"). If asked
  what to buy, give the data and say the call is theirs.
- The cheap/expensive signal is **self-referential by design**: today's P/E as
  a percentile of that same company's own 5-year P/E range. Absolute P/E
  across companies is close to meaningless; a market-wide average is worse.
- **Both sides of that comparison must use the same earnings basis.** Today's
  P/E is recomputed in `pe_percentile()` as price ÷ reconstructed TTM EPS —
  do NOT score yfinance's `info['trailingPE']` (GAAP) against a history built
  from `get_earnings_dates` (adjusted). That error put ServiceNow at the 87th
  percentile ("priciest") when it was really 11th, and flipped BRK-B from 0th
  to 38th. It biases everything toward looking cheap.
- ETFs and unprofitable companies legitimately have no earnings-based P/E —
  show "no P/E history", never "cheap".

## Standing rules & hard-won gotchas

- Real personal financial data. Never fabricate a number. If a script errors
  or a CSV is missing, show the error — don't fill the gap with a plausible
  figure.
- **Never total the portfolio by summing position rows.** The authoritative
  number is `net_liquidation_value` from `performance.csv` (Wealthsimple's own
  figure). Summing positions once shipped a 3x-inflated total, because
  `fetch_data.py` had appended three same-day snapshots and "latest snapshot"
  filtered on date, not run. Both ends are fixed now, but the rule stands:
  positions are for composition, `performance.csv` is for totals.
- `get_identity_historical_financials` **requires `account_ids`** — with only
  `currency` it returns an empty list instead of erroring, silently costing
  the entire portfolio-value time series.
- The same call also **requires `end_date`**, for a different reason. Despite
  the `historicalDaily` path it always downsamples a multi-year range to ~110
  points (weekly), and with no `end_date` it anchors the last point to the
  previous completed week — so the headline total ran up to 7 days stale. The
  user caught this: the dashboard reported the previous week's closing value
  while the Wealthsimple app showed the current one. Passing
  `end_date=datetime.now()`
  keeps the same weekly resolution but ends the series on today. If you ever
  need true daily points, pass `start_date` too and keep the window short —
  a ~1-month range comes back genuinely daily.
- When the user says a number looks wrong, check the API call before assuming
  the display is just stale. Twice now the bug has been in `fetch_data.py`.
- Benchmark comparisons must use **time-weighted return**, never raw value —
  raw value grows just from depositing money. Drawdown is computed off the TWR
  index for the same reason: on raw value a mid-sized withdrawal read as a
  -69% "crash" when real performance drawdown was about -11%.
- Dips are filtered to those bottoming on/after the first-funded date — the
  user explicitly does not want dips from before they started investing.
- Trade `symbol` comes from the activity's `assetSymbol`, not
  `api.security_id_to_symbol()` — that call is case-sensitive against a
  differently-cased `securityId` and silently returns a `[securityId]`
  placeholder for everything.
- `market_data.py`'s crypto path (`-USD`) exists because a bare `BTC` matches
  an unrelated real equity on Yahoo Finance. Always pass `is_crypto=True` for
  `CRYPTO_*` activity types.
- `build_trades.py` FIFO-matches per `(account_id, securityId)`, not display
  symbol — two option contracts, or a US listing and its CAD CDR, can share a
  ticker but are different instruments.
- `positions.csv` is one row per `(account, security)`. Group by symbol before
  presenting holdings or you'll double-count.
- API field shapes were verified against the installed `ws-api` source, not
  its docs. If `pip install --upgrade ws-api` breaks something, re-check the
  package's actual method signatures rather than guessing.
