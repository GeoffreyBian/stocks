"""
Find market dips (benchmark + your traded symbols) and check whether your
trade history bought into them, sold into them, or sat them out.

A "dip" here is a drawdown of at least DIP_THRESHOLD_PCT from a trailing
LOOKBACK_DAYS high, ending when price recovers back to within RECOVERY_PCT of
that high (or the data runs out).

Usage:
    .venv/bin/python scripts/detect_dips.py

Writes:
    data/processed/dip_events.csv
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"

BENCHMARKS = {"^GSPC": "S&P 500", "^GSPTSE": "TSX Composite"}
LOOKBACK_DAYS = 252  # ~1 trading year, for the rolling high
DIP_THRESHOLD_PCT = -10.0
RECOVERY_PCT = -2.0  # "recovered" once within 2% of the prior high
HISTORY_PERIOD = "5y"


def traded_symbols() -> set[str]:
    path = PROCESSED_DIR / "activities.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    if "symbol" not in df.columns:
        return set()
    return set(df["symbol"].dropna().unique())


def find_dips(symbol: str) -> pd.DataFrame:
    hist = yf.Ticker(symbol).history(period=HISTORY_PERIOD)
    if hist.empty:
        return pd.DataFrame()

    hist["rolling_high"] = hist["Close"].rolling(LOOKBACK_DAYS, min_periods=20).max()
    hist["drawdown_pct"] = (hist["Close"] - hist["rolling_high"]) / hist["rolling_high"] * 100

    events = []
    in_dip = False
    dip_start = None
    dip_low = None
    dip_low_date = None

    for date, row in hist.iterrows():
        dd = row["drawdown_pct"]
        if pd.isna(dd):
            continue
        if not in_dip and dd <= DIP_THRESHOLD_PCT:
            in_dip = True
            dip_start = date
            dip_low = dd
            dip_low_date = date
        elif in_dip:
            if dd < dip_low:
                dip_low = dd
                dip_low_date = date
            if dd >= RECOVERY_PCT:
                events.append({
                    "symbol": symbol,
                    "dip_start": dip_start.date(),
                    "dip_low_date": dip_low_date.date(),
                    "dip_low_pct": round(dip_low, 1),
                    "recovered_date": date.date(),
                })
                in_dip = False

    if in_dip:
        events.append({
            "symbol": symbol,
            "dip_start": dip_start.date(),
            "dip_low_date": dip_low_date.date(),
            "dip_low_pct": round(dip_low, 1),
            "recovered_date": None,  # still ongoing / hasn't recovered
        })

    return pd.DataFrame(events)


def cross_reference_with_trades(dips: pd.DataFrame) -> pd.DataFrame:
    trades_path = PROCESSED_DIR / "activities.csv"
    if not trades_path.exists() or dips.empty:
        dips["your_activity"] = None
        return dips

    trades = pd.read_csv(trades_path)
    trades = trades[trades["side"].isin(["BUY", "SELL"])].copy()
    trades["occurredAt"] = pd.to_datetime(trades["occurredAt"]).dt.date

    activity_notes = []
    for _, dip in dips.iterrows():
        symbol = dip["symbol"]
        start, end = dip["dip_start"], dip["dip_low_date"]
        window_trades = trades[
            (trades["symbol"] == symbol)
            & (trades["occurredAt"] >= start)
            & (trades["occurredAt"] <= (dip["recovered_date"] or pd.Timestamp.now().date()))
        ]
        if window_trades.empty:
            activity_notes.append("no trades during this dip")
        else:
            parts = [f"{r['side']} {r['assetQuantity']} on {r['occurredAt']}" for _, r in window_trades.iterrows()]
            activity_notes.append("; ".join(parts))
    dips["your_activity"] = activity_notes
    return dips


def main():
    symbols = BENCHMARKS.keys() | traded_symbols()
    all_dips = []
    for symbol in symbols:
        print(f"Scanning {symbol} for dips...")
        d = find_dips(symbol)
        if not d.empty:
            all_dips.append(d)

    if not all_dips:
        print("No dips found.")
        return

    combined = pd.concat(all_dips, ignore_index=True)
    combined = cross_reference_with_trades(combined)
    combined.to_csv(PROCESSED_DIR / "dip_events.csv", index=False)
    print(f"dip_events.csv: {len(combined)} dip events across {len(symbols)} symbols")


if __name__ == "__main__":
    main()
