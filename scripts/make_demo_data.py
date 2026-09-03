"""
Generate a synthetic dashboard snapshot so the dashboard can be shown off
without exposing anyone's real holdings.

Every number here is invented by a seeded RNG. No account is ever contacted,
no credentials are needed, and nothing under data/ is read. The output matches
the schema build_dashboard_snapshot.py produces, so the same template renders
it unchanged.

Usage:
    .venv/bin/python scripts/make_demo_data.py
    .venv/bin/python scripts/render_dashboard_html.py --data dashboard/demo_data.json \
                                                      --out  dashboard/demo.html
"""
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "dashboard" / "demo_data.json"

SEED = 20240724
START = date(2023, 6, 7)
WEEKS = 110

# Real tickers, invented positions. Using well-known symbols keeps the
# valuation bands and earnings tables looking like the real thing.
#
# The third column is a relative weight, not a dollar amount: actual market
# values are derived from wherever the simulated equity curve happens to end,
# so the holdings always sum to the headline total instead of contradicting it.
HOLDINGS = [
    ("VTI",  "Vanguard Total Stock Market ETF",  16800, 14.2, 1),
    ("MSFT", "Microsoft Corporation",            11400, 21.6, 2),
    ("GOOG", "Alphabet Inc.",                     9250, 33.1, 1),
    ("AMZN", "Amazon.com, Inc.",                  8100, -4.8, 2),
    ("NVDA", "NVIDIA Corporation",                7300, 48.9, 1),
    ("COST", "Costco Wholesale Corporation",      5600,  9.4, 1),
    ("JPM",  "JPMorgan Chase & Co.",              4950, 12.7, 1),
    ("V",    "Visa Inc.",                         3800,  6.1, 1),
    ("SCHD", "Schwab US Dividend Equity ETF",     3150,  2.3, 1),
    ("TSM",  "Taiwan Semiconductor Manufacturing",2400, 27.5, 1),
    ("DIS",  "The Walt Disney Company",           1750, -11.9, 1),
]

WATCH_ONLY = [
    ("AAPL", "Apple Inc.",                 "Technology"),
    ("LLY",  "Eli Lilly and Company",      "Healthcare"),
    ("UNH",  "UnitedHealth Group Inc.",    "Healthcare"),
    ("ASML", "ASML Holding N.V.",          "Technology"),
    ("SHOP", "Shopify Inc.",               "Technology"),
    ("ISRG", "Intuitive Surgical, Inc.",   "Healthcare"),
]

SECTORS = {
    "MSFT": "Technology", "GOOG": "Communication Services",
    "AMZN": "Consumer Cyclical", "NVDA": "Technology",
    "COST": "Consumer Defensive", "JPM": "Financial Services",
    "V": "Financial Services", "TSM": "Technology",
    "DIS": "Communication Services",
}

FUNDS = {"VTI", "SCHD"}  # no earnings-based P/E, by design


def build_series(rng):
    """A weekly value/deposit series that grows by contributions plus drift."""
    perf, twr, drawdown = [], [], []
    deposits = 500.0
    value = 500.0
    idx = 100.0
    bench = 100.0
    peak = 100.0

    for w in range(WEEKS):
        d = START + timedelta(weeks=w)

        # Contributions: a steady biweekly habit with occasional lump sums.
        if w and w % 2 == 0:
            add = rng.choice([250, 300, 400, 500])
            deposits += add
            value += add
        if w and w % 29 == 0:
            add = rng.choice([3000, 4000, 6000])
            deposits += add
            value += add

        r = rng.gauss(0.0022, 0.021)          # portfolio weekly return
        b = r * 0.72 + rng.gauss(0.0009, 0.011)  # benchmark, correlated but calmer
        value *= 1 + r
        idx *= 1 + r
        bench *= 1 + b
        peak = max(peak, idx)

        perf.append({"date": d.isoformat(), "value": round(value, 2),
                     "deposits": round(deposits, 2)})
        twr.append({"date": d.isoformat(), "portfolio": round(idx, 2),
                    "benchmark": round(bench, 2)})
        drawdown.append({"date": d.isoformat(),
                         "drawdown_pct": round((idx / peak - 1) * 100, 2)})

    return perf, twr, drawdown


def build_monthly(rng, perf):
    months = sorted({p["date"][:7] for p in perf})[-16:]
    return [{"month": m, "realized_pnl": round(rng.gauss(180, 620), 2)} for m in months]


def build_watchlist(rng):
    rows = []
    for sym, name, mv, pnl_pct, _ in HOLDINGS:
        rows.append(_wl_row(rng, sym, name, SECTORS.get(sym), held=True))
    for sym, name, sector in WATCH_ONLY:
        rows.append(_wl_row(rng, sym, name, sector, held=False))
    return rows


def _wl_row(rng, sym, name, sector, held):
    is_fund = sym in FUNDS
    price = round(rng.uniform(40, 620), 2)
    row = {
        "symbol": sym, "name": name, "sector": sector, "held": held,
        "price": price,
        "pct_from_52w_high": round(-rng.uniform(0.5, 34), 1),
        "pct_above_52w_low": round(rng.uniform(6, 90), 1),
        "vs_ma50_pct": round(rng.gauss(1.5, 7), 1),
        "vs_ma200_pct": round(rng.gauss(5, 12), 1),
        "trailing_pe": None if is_fund else round(rng.uniform(14, 62), 1),
        "forward_pe": None if is_fund else round(rng.uniform(12, 40), 1),
        "peg": None if is_fund else round(rng.uniform(0.6, 3.2), 2),
        "price_to_book": None if is_fund else round(rng.uniform(2, 26), 1),
        "dividend_yield_pct": round(rng.uniform(0, 2.6), 2),
        "revenue_growth_pct": None if is_fund else round(rng.uniform(2, 34), 1),
        "earnings_growth_pct": None if is_fund else round(rng.gauss(18, 30), 1),
        "profit_margin_pct": None if is_fund else round(rng.uniform(6, 46), 1),
        "market_cap": None if is_fund else round(rng.uniform(60e9, 3.2e12)),
        "analyst_target": None if is_fund else round(price * rng.uniform(0.95, 1.35), 2),
    }
    if is_fund:
        row.update({"pe_percentile": None, "pe_low": None, "pe_high": None,
                    "pe_median": None, "pe_used": None,
                    "valuation_label": "no P/E history", "analyst_upside_pct": None})
        return row

    lo = round(rng.uniform(11, 30), 1)
    hi = round(lo + rng.uniform(9, 60), 1)
    used = round(rng.uniform(lo, hi), 1)
    pctile = round((used - lo) / (hi - lo) * 100, 1)
    row.update({
        "pe_percentile": pctile, "pe_low": lo, "pe_high": hi,
        "pe_median": round((lo + hi) / 2, 1), "pe_used": used,
        "valuation_label": _label(pctile),
        "analyst_upside_pct": round((row["analyst_target"] / price - 1) * 100, 1),
    })
    return row


def _label(p):
    if p < 20:
        return "near its cheapest"
    if p < 40:
        return "below its usual"
    if p < 60:
        return "around its usual"
    if p < 80:
        return "above its usual"
    return "near its priciest"


def build_earnings(rng, today):
    syms = [h[0] for h in HOLDINGS if h[0] not in FUNDS] + [w[0] for w in WATCH_ONLY]
    upcoming = []
    for i, s in enumerate(sorted(syms)):
        upcoming.append({
            "symbol": s,
            "date": (today + timedelta(days=12 + i * 3)).isoformat(),
            "upcoming": True,
            "eps_estimate": round(rng.uniform(0.4, 9.5), 2),
            "reported_eps": None, "surprise_pct": None,
        })
    surprises = []
    for i, s in enumerate(sorted(syms)):
        est = round(rng.uniform(0.4, 8.0), 2)
        surp = round(rng.gauss(4, 12), 1)
        surprises.append({
            "symbol": s, "beats": rng.randint(1, 4), "of": 4,
            "last_date": (today - timedelta(days=20 + i * 4)).isoformat(),
            "last_surprise_pct": surp,
            "last_reported_eps": round(est * (1 + surp / 100), 2),
            "last_estimate": est,
        })
    return {"upcoming": upcoming[:18], "recent_surprises": surprises}


def build_dips(rng, today):
    def dip(sym, months_ago, depth, activity, recovered=True):
        low = today - timedelta(days=months_ago * 30)
        return {
            "symbol": sym,
            "dip_start": (low - timedelta(days=rng.randint(20, 90))).isoformat(),
            "dip_low_date": low.isoformat(),
            "dip_low_pct": depth,
            "recovered_date": (low + timedelta(days=rng.randint(30, 120))).isoformat()
                              if recovered else None,
            "your_activity": activity,
        }

    return {
        "benchmarks": [
            dip("^GSPC", 14, -17.4, "no trades during this dip"),
            dip("^GSPTSE", 14, -11.9, "no trades during this dip"),
        ],
        "dips_with_activity": [
            dip("NVDA", 11, -34.2, "BUY 6.0 on 2024-11-04; BUY 4.0 on 2024-10-28"),
            dip("AMZN", 9, -28.7, "BUY 12.0 on 2025-01-16"),
            dip("DIS", 7, -24.1, "SELL 20.0 on 2025-03-11", recovered=False),
            dip("MSFT", 5, -19.6, "BUY 3.0 on 2025-05-19; BUY 2.0 on 2025-05-12"),
            dip("TSM", 3, -15.2, "BUY 8.0 on 2025-07-22", recovered=False),
        ],
        "notable_dips_missed": [
            dip("AAPL", 13, -26.3, "no trades during this dip"),
            dip("ISRG", 10, -22.8, "no trades during this dip"),
            dip("SHOP", 6, -31.5, "no trades during this dip", recovered=False),
        ],
        # These five buckets partition the dips - they must sum to dips_total.
        "dips_bought": 9,
        "dips_sold_into": 4,
        "dips_both": 2,
        "dips_recovery_only": 7,
        "dips_sat_out": 29,
        "dips_total": 51,
    }


def main():
    rng = random.Random(SEED)
    today = START + timedelta(weeks=WEEKS - 1)

    perf, twr, drawdown = build_series(rng)
    last = perf[-1]
    total = last["value"]
    cash = {"CAD": 812.44, "USD": 1265.09}
    securities = round(total - sum(cash.values()), 2)

    weight_sum = sum(h[2] for h in HOLDINGS)
    holdings = []
    for s, n, w, p, c in HOLDINGS:
        mv = round(securities * w / weight_sum, 2)
        holdings.append({
            "symbol": s, "name": n, "market_value": mv,
            "unrealized_pnl": round(mv - mv / (1 + p / 100), 2),
            "unrealized_pnl_pct": p,
            "pct_of_portfolio": round(mv / securities * 100, 1),
            "position_count": c,
        })
    unrealized = round(sum(h["unrealized_pnl"] for h in holdings), 2)

    by_sec = sorted(
        [{"symbol": s, "realized_pnl": round(rng.gauss(320, 900), 2)}
         for s, *_ in HOLDINGS + [(w[0],) for w in WATCH_ONLY]],
        key=lambda r: -r["realized_pnl"])

    data = {
        "demo_notice": "Demo data — every figure on this page is randomly "
                       "generated, not a real portfolio.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": [
            {"label": "TFSA", "currency": "CAD"},
            {"label": "RRSP", "currency": "CAD"},
            {"label": "Non-registered", "currency": "CAD"},
            {"label": "Cash (USD)", "currency": "USD"},
        ],
        "portfolio_summary": {
            "total_value": total,
            "as_of": last["date"],
            "net_deposits": last["deposits"],
            "total_gain": round(total - last["deposits"], 2),
            "total_gain_pct": round((total / last["deposits"] - 1) * 100, 1),
            "securities_value": securities,
            "total_unrealized_pnl": unrealized,
            "first_invested": START.isoformat(),
            "cash": cash,
        },
        "performance": perf,
        "twr": {"series": twr, "benchmark_label": "S&P 500"},
        "drawdown": drawdown,
        "monthly_realized": build_monthly(rng, perf),
        "holdings": holdings,
        "realized": {"total": round(sum(r["realized_pnl"] for r in by_sec), 2),
                     "by_security": by_sec},
        "win_rate": {"closed_trades": 48, "wins": 31, "losses": 17,
                     "win_rate_pct": 64.6, "avg_win": 288.15,
                     "avg_loss": -164.02, "avg_holding_days": 97.3},
        "bad_trades": [
            {"account_id": "demo-account-1", "symbol": "DIS",
             "buy_date": "2024-08-19", "sell_date": "2025-03-11",
             "realized_pnl": -412.60, "realized_pnl_pct": -21.4,
             "flags": "big_loss: -21.4% realized loss; bad_entry: DIS dropped "
                      "-15.2% in the 30d after you bought",
             "roundtrips": None, "window_start": None, "window_end": None},
            {"account_id": "demo-account-1", "symbol": "NVDA",
             "buy_date": "2024-10-28", "sell_date": "2025-01-06",
             "realized_pnl": 604.20, "realized_pnl_pct": 38.9,
             "flags": "sold_too_early: NVDA rose 41.3% in the 30d after you sold",
             "roundtrips": None, "window_start": None, "window_end": None},
            {"account_id": "demo-account-2", "symbol": "TSM",
             "buy_date": "2025-02-03", "sell_date": "2025-02-24",
             "realized_pnl": -138.75, "realized_pnl_pct": -8.1,
             "flags": "quick_loss: closed at -8.1% after only 21 days",
             "roundtrips": None, "window_start": None, "window_end": None},
            {"account_id": "demo-account-2", "symbol": "AMZN",
             "buy_date": None, "sell_date": None,
             "realized_pnl": None, "realized_pnl_pct": None,
             "flags": "overtrading: 5 round-trips in 22d",
             "roundtrips": 5.0, "window_start": "2025-04-02",
             "window_end": "2025-04-24"},
        ],
        "dips": build_dips(rng, today),
        "watchlist": build_watchlist(rng),
        "earnings": build_earnings(rng, today),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2))
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print(f"  {len(perf)} weekly points, {len(holdings)} holdings, "
          f"{len(data['watchlist'])} screened symbols")
    print(f"  demo total ${total:,.0f} (synthetic)")


if __name__ == "__main__":
    main()
