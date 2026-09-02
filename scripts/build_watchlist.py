"""
Screen your holdings + watchlist for valuation and dips.

The core idea (borrowed from how Qualtrim / FactorsToday present valuation):
an absolute P/E of 28 means nothing on its own - it's cheap for one company
and expensive for another. What's informative is where today's multiple sits
inside *that company's own* history. So this builds a real trailing-P/E time
series per symbol (daily price / TTM EPS reconstructed from reported quarterly
earnings) and reports today's percentile within it.

This is a data tool, not advice. It reports what the numbers are; deciding
what to do about them is yours.

Usage:
    .venv/bin/python scripts/build_watchlist.py

Writes:
    data/processed/watchlist.csv
    data/processed/earnings_calendar.csv
"""
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from market_data import resolve_yf_symbol

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
WATCHLIST_FILE = ROOT / "watchlist.txt"

PE_HISTORY_YEARS = 5
EARNINGS_QUARTERS = 40


def read_watchlist() -> list[str]:
    if not WATCHLIST_FILE.exists():
        return []
    lines = WATCHLIST_FILE.read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def held_symbols() -> list[str]:
    """Symbols currently held, from the latest positions snapshot."""
    path = PROCESSED_DIR / "positions.csv"
    act_path = PROCESSED_DIR / "activities.csv"
    if not path.exists() or not act_path.exists():
        return []
    pos = pd.read_csv(path)
    pos = pos[pos["snapshot_date"] == pos["snapshot_date"].max()]
    held_ids = {str(s).strip().lower() for s in pos["security.id"].dropna()}

    act = pd.read_csv(act_path).dropna(subset=["securityId", "symbol"])
    act["sid"] = act["securityId"].astype(str).str.strip().str.lower()
    matched = act[act["sid"].isin(held_ids)]
    return sorted(matched["symbol"].dropna().unique().tolist())


def ttm_eps_series(ticker: yf.Ticker) -> pd.Series | None:
    """Trailing-twelve-month EPS as of each earnings report date."""
    try:
        ed = ticker.get_earnings_dates(limit=EARNINGS_QUARTERS)
    except Exception:
        return None
    if ed is None or ed.empty or "Reported EPS" not in ed.columns:
        return None

    rep = ed[ed["Reported EPS"].notna()].sort_index()
    if len(rep) < 4:
        return None

    eps = rep["Reported EPS"].astype(float)
    ttm = eps.rolling(4).sum().dropna()
    ttm.index = pd.to_datetime(ttm.index).tz_localize(None)
    return ttm


def pe_percentile(ticker: yf.Ticker, price: float | None) -> dict:
    """Where today's trailing P/E sits within its own multi-year range.

    0% = cheapest it has been on this window, 100% = most expensive.

    IMPORTANT: today's P/E is recomputed here as price / (my reconstructed TTM
    EPS) rather than taken from yfinance's `trailingPE`. Those two use
    different earnings definitions - yfinance's trailing EPS is GAAP, while
    `get_earnings_dates` reports the adjusted figure companies guide to (NVDA:
    7.91 vs 7.01, a ~13% gap). Scoring a GAAP-based P/E against an
    adjusted-based history systematically understates the percentile and makes
    everything look cheaper than it is. Both sides must use one basis.
    """
    out = {"pe_percentile": None, "pe_low": None, "pe_high": None,
           "pe_median": None, "pe_used": None}
    if not price:
        return out

    ttm = ttm_eps_series(ticker)
    if ttm is None or ttm.empty or ttm.iloc[-1] <= 0:
        return out

    current_pe = float(price) / float(ttm.iloc[-1])
    out["pe_used"] = round(current_pe, 1)

    try:
        hist = ticker.history(period=f"{PE_HISTORY_YEARS}y")
    except Exception:
        return out
    if hist.empty:
        return out

    closes = hist["Close"].copy()
    closes.index = pd.to_datetime(closes.index).tz_localize(None)

    # For each trading day, the TTM EPS in effect is the most recent report
    # at or before that day.
    eps_aligned = ttm.reindex(ttm.index.union(closes.index)).ffill().reindex(closes.index)
    pe_series = (closes / eps_aligned).replace([float("inf"), float("-inf")], pd.NA).dropna()
    pe_series = pe_series[pe_series > 0]
    if len(pe_series) < 60:
        return out

    out["pe_percentile"] = round(float((pe_series < current_pe).mean() * 100), 1)
    out["pe_low"] = round(float(pe_series.quantile(0.05)), 1)
    out["pe_high"] = round(float(pe_series.quantile(0.95)), 1)
    out["pe_median"] = round(float(pe_series.median()), 1)
    return out


def valuation_label(pct: float | None) -> str:
    """Descriptive label for where the multiple sits in its own range.

    Deliberately descriptive, not directive - this says what the number is,
    not what to do about it.
    """
    if pct is None:
        return "no P/E history"
    if pct < 20:
        return "near its cheapest"
    if pct < 40:
        return "below its usual"
    if pct < 60:
        return "around its usual"
    if pct < 80:
        return "above its usual"
    return "near its priciest"


def screen_symbol(symbol: str, held: bool) -> dict | None:
    yf_symbol = resolve_yf_symbol(symbol)
    if not yf_symbol:
        return None
    t = yf.Ticker(yf_symbol)
    try:
        info = t.info
    except Exception:
        return None
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        return None

    high52 = info.get("fiftyTwoWeekHigh")
    low52 = info.get("fiftyTwoWeekLow")
    trailing_pe = info.get("trailingPE")

    try:
        hist = t.history(period="1y")
        ma50 = float(hist["Close"].tail(50).mean()) if len(hist) >= 50 else None
        ma200 = float(hist["Close"].tail(200).mean()) if len(hist) >= 200 else None
    except Exception:
        ma50 = ma200 = None

    pe_ctx = pe_percentile(t, price)

    row = {
        "symbol": symbol,
        "name": info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "held": held,
        "price": round(float(price), 2),
        "pct_from_52w_high": round((price - high52) / high52 * 100, 1) if high52 else None,
        "pct_above_52w_low": round((price - low52) / low52 * 100, 1) if low52 else None,
        "vs_ma50_pct": round((price - ma50) / ma50 * 100, 1) if ma50 else None,
        "vs_ma200_pct": round((price - ma200) / ma200 * 100, 1) if ma200 else None,
        "trailing_pe": round(float(trailing_pe), 1) if trailing_pe else None,
        "forward_pe": round(float(info["forwardPE"]), 1) if info.get("forwardPE") else None,
        "peg": round(float(info["pegRatio"]), 2) if info.get("pegRatio") else None,
        "price_to_book": round(float(info["priceToBook"]), 1) if info.get("priceToBook") else None,
        "dividend_yield_pct": round(float(info["dividendYield"]), 2) if info.get("dividendYield") else None,
        "revenue_growth_pct": round(float(info["revenueGrowth"]) * 100, 1) if info.get("revenueGrowth") is not None else None,
        "earnings_growth_pct": round(float(info["earningsGrowth"]) * 100, 1) if info.get("earningsGrowth") is not None else None,
        "profit_margin_pct": round(float(info["profitMargins"]) * 100, 1) if info.get("profitMargins") is not None else None,
        "market_cap": info.get("marketCap"),
        "analyst_target": round(float(info["targetMeanPrice"]), 2) if info.get("targetMeanPrice") else None,
        **pe_ctx,
    }
    row["valuation_label"] = valuation_label(row["pe_percentile"])
    row["analyst_upside_pct"] = (
        round((row["analyst_target"] - row["price"]) / row["price"] * 100, 1)
        if row["analyst_target"] else None
    )
    return row


def earnings_rows(symbol: str) -> list[dict]:
    yf_symbol = resolve_yf_symbol(symbol)
    if not yf_symbol:
        return []
    try:
        ed = yf.Ticker(yf_symbol).get_earnings_dates(limit=12)
    except Exception:
        return []
    if ed is None or ed.empty:
        return []

    out = []
    now = pd.Timestamp.now(tz=ed.index.tz) if ed.index.tz else pd.Timestamp.now()
    for date, row in ed.iterrows():
        out.append({
            "symbol": symbol,
            "date": date.date().isoformat(),
            "upcoming": bool(date > now),
            "eps_estimate": None if pd.isna(row.get("EPS Estimate")) else round(float(row["EPS Estimate"]), 2),
            "reported_eps": None if pd.isna(row.get("Reported EPS")) else round(float(row["Reported EPS"]), 2),
            "surprise_pct": None if pd.isna(row.get("Surprise(%)")) else round(float(row["Surprise(%)"]), 1),
        })
    return out


def main():
    held = held_symbols()
    watch = read_watchlist()
    universe = [(s, True) for s in held] + [(s, False) for s in watch if s not in held]
    print(f"Screening {len(universe)} symbols ({len(held)} held, {len(universe) - len(held)} watched)...")

    rows, earnings = [], []
    for i, (symbol, is_held) in enumerate(universe, 1):
        print(f"  [{i}/{len(universe)}] {symbol}", flush=True)
        try:
            row = screen_symbol(symbol, is_held)
            if row:
                rows.append(row)
                earnings.extend(earnings_rows(symbol))
        except Exception as e:
            print(f"    ! {symbol} failed: {e}")
        time.sleep(0.2)  # be polite to the data source

    if rows:
        pd.DataFrame(rows).to_csv(PROCESSED_DIR / "watchlist.csv", index=False)
        print(f"watchlist.csv: {len(rows)} symbols")
    if earnings:
        pd.DataFrame(earnings).to_csv(PROCESSED_DIR / "earnings_calendar.csv", index=False)
        print(f"earnings_calendar.csv: {len(earnings)} rows")


if __name__ == "__main__":
    main()
