# stocks

Pull your own Wealthsimple trading data to your machine, work out what your
trades actually did, and roll it all into a single self-contained dashboard
page.

It answers the questions a brokerage app tends not to: *am I actually beating
the index once my deposits are stripped out? which of my exits look bad in
hindsight? when a stock I own fell 30%, did I buy, sell, or sit there? is this
company expensive compared to how the market usually prices it?*

**[See the dashboard with demo data →](dashboard/demo.html)**
(every figure on that page is randomly generated — see
[Demo mode](#demo-mode))

> Read-only and local. The OAuth scope is `invest.read trade.read tax.read`,
> so nothing here can place a trade or move money, and no financial data is
> ever committed — see [Privacy](#privacy).

## What it gives you

| Section | What it shows |
|---|---|
| **Growth** | Portfolio value against money invested, so the gap is your actual gain rather than your deposit habit |
| **Return vs benchmark** | Time-weighted return against the S&P 500, both indexed to 100 at your first deposit |
| **Drawdown** | How far performance sat below its best point, computed off the TWR index |
| **Valuation screener** | Where each stock's P/E sits inside *its own* 5-year range, plus % off 52-week high and moving averages |
| **Earnings** | Upcoming report dates with EPS estimates, and a recent beat/miss record |
| **Holdings & allocation** | Positions by market value with unrealized P&L, grouped across accounts |
| **Realized P&L** | By month and by security, from FIFO-matched closed trades |
| **Flagged trades** | Closed trades that tripped a heuristic: big loss, quick loss, bad entry, sold too early, overtrading |
| **Market dips** | Every ≥10% fall from a trailing 1-year high in something you own, and what you did during it |

## Setup

Requires Python 3.11+ and a Wealthsimple account.

```bash
git clone https://github.com/GeoffreyBian/stocks.git
cd stocks
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/auth.py     # interactive: email, password, 2FA code
```

`auth.py` is the only script that ever asks for credentials. Your password and
2FA code are typed at the terminal, used once, and never written to disk — only
the resulting session token is stored, in the macOS Keychain under the service
name `wealthsimple-stocks-folder`.

This uses [ws-api](https://github.com/gboudreau/ws-api-python), an
**unofficial** Wealthsimple client. It is not affiliated with, endorsed by, or
sanctioned by Wealthsimple, and the private API it talks to can change without
warning.

## Usage

```bash
.venv/bin/python scripts/check_auth.py    # is the session still valid? (never prompts)
.venv/bin/python scripts/refresh_all.py   # the whole pipeline in one command
```

`refresh_all.py` runs fetch → trades → flagged trades → dips → screener →
snapshot → render, checking auth up front so it stops with instructions rather
than hanging on a password prompt halfway through. Pass `--skip-watchlist` to
skip the valuation screener, which is the slow part (~2-4 minutes, one Yahoo
Finance round trip per symbol).

The result is `dashboard/dashboard.html` — one self-contained file with the
data inlined. Open it in a browser, or publish it wherever you like.

<details>
<summary>Running the steps individually</summary>

```bash
.venv/bin/python scripts/fetch_data.py               # Wealthsimple -> data/raw + data/processed
.venv/bin/python scripts/build_trades.py             # FIFO-match buys/sells into closed trades
.venv/bin/python scripts/detect_bad_trades.py        # flag quick/big losses, bad timing, overtrading
.venv/bin/python scripts/detect_dips.py              # find dips, cross-reference your activity
.venv/bin/python scripts/build_watchlist.py          # valuation percentiles, dips, earnings
.venv/bin/python scripts/build_dashboard_snapshot.py # aggregate -> dashboard/dashboard_data.json
.venv/bin/python scripts/render_dashboard_html.py    # template + data -> dashboard/dashboard.html
```
</details>

## Demo mode

To see the dashboard without connecting an account:

```bash
.venv/bin/python scripts/make_demo_data.py
.venv/bin/python scripts/render_dashboard_html.py \
    --data dashboard/demo_data.json --out dashboard/demo.html
```

`make_demo_data.py` invents an entire portfolio with a seeded RNG — a simulated
equity curve, holdings, flagged trades, dips and screener rows. It never
contacts an API, needs no credentials, and reads nothing under `data/`. Pages
built this way carry a banner saying so, so a demo can't be mistaken for a real
account.

## The valuation screener

An absolute P/E is close to meaningless across companies, and a market-wide
average is worse. So the screener is deliberately **self-referential**: it
scores today's P/E as a percentile of that same company's own 5-year P/E range.
0% means the cheapest it has been on that measure; 100% the priciest.

Today's P/E is recomputed on the *same earnings basis* as the history it's
scored against — price ÷ a TTM EPS series reconstructed from reported
quarterlies. Scoring a GAAP `trailingPE` against an adjusted-EPS history is a
subtle way to make everything look cheap, and it produced badly wrong answers
before it was fixed.

ETFs and unprofitable companies have no earnings-based P/E and are labelled
"no P/E history" rather than being scored.

**Labels are descriptive, never directive** — "near its cheapest", "above its
usual". This is a data tool, not advice. It reports where a multiple sits in
its own history; what to do about that is your call.

## Privacy

`.gitignore` keeps every file that could contain a real figure out of git:

```
data/raw/                       # timestamped full API snapshots
data/processed/                 # every derived CSV
dashboard/dashboard_data.json   # the generated snapshot
dashboard/dashboard.html        # the rendered page, data inlined
```

What *is* tracked: the scripts, the empty dashboard template, `watchlist.txt`,
your journal notes, and the synthetic demo. Cloning this repo gets you the
tooling and a fake portfolio — never anyone's holdings.

If you fork this and publish it, note that `journal/notes.md` **is** tracked.
It's meant for trade rationale, so either keep it free of figures or add it to
your own `.gitignore`.

## How it's structured

```
scripts/
  auth.py                      # interactive login (the only credential prompt)
  check_auth.py                # is the session valid? exit 0/1, never prompts
  refresh_all.py               # the whole pipeline, one command
  fetch_data.py                # Wealthsimple -> data/raw + data/processed
  market_data.py               # Yahoo symbol resolver (TSX suffixes, crypto -USD)
  build_trades.py              # activities -> FIFO-matched closed trades
  detect_bad_trades.py         # trades -> bad_trade_flags.csv
  detect_dips.py               # benchmarks + held symbols -> dip_events.csv
  build_watchlist.py           # valuation percentiles, dips, earnings
  build_dashboard_snapshot.py  # everything -> dashboard_data.json
  render_dashboard_html.py     # template + data -> a self-contained page
  make_demo_data.py            # synthetic snapshot, no account needed
dashboard/
  dashboard_template.html      # page shell + CSS/JS, contains no data
watchlist.txt                  # symbols to screen but not own
journal/notes.md               # freeform trade rationale
```

Some notes for anyone extending this, including the API gotchas that cost the
most time to find, live in
[`.claude/skills/stocks/SKILL.md`](.claude/skills/stocks/SKILL.md). That file
is a [Claude Code](https://claude.com/claude-code) skill — it's what lets
Claude drive this repo conversationally ("refresh my dashboard", "why was that
trade flagged?") — but it reads perfectly well as plain developer
documentation.

## License

MIT — see [LICENSE](LICENSE).

Not financial advice. Verify anything here against your brokerage's own figures
before acting on it.
