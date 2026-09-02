"""
Flag closed trades (data/processed/trades.csv) that look like mistakes, using
a few simple, explainable heuristics rather than a black-box score. Each flag
says what happened and why it's worth a second look - none of them are a
verdict, they're prompts for the trade journal.

Heuristics:
  - quick_loss:     sold at a loss within a short holding window (impulse exit)
  - big_loss:       realized loss beyond a threshold % (no stop-loss discipline?)
  - sold_too_early: the stock kept running well after you sold (left money on the table)
  - bad_entry:      bought right before a sharp drop in the following days
  - overtrading:    same symbol/account round-tripped many times in a short span

Usage:
    .venv/bin/python scripts/detect_bad_trades.py

Writes:
    data/processed/bad_trade_flags.csv
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

from market_data import resolve_yf_symbol

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"

QUICK_LOSS_DAYS = 5
BIG_LOSS_PCT = -15.0
POST_SALE_REGRET_PCT = 15.0   # stock rose this much in the window after you sold
POST_BUY_DROP_PCT = -10.0     # stock fell this much in the window after you bought
LOOKAHEAD_DAYS = 30
OVERTRADING_WINDOW_DAYS = 30
OVERTRADING_MIN_ROUNDTRIPS = 4


def load_trades() -> pd.DataFrame:
    path = PROCESSED_DIR / "trades.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run build_trades.py first")
    df = pd.read_csv(path, parse_dates=["buy_date", "sell_date"])
    return df.dropna(subset=["buy_date", "sell_date"])  # need both ends to flag


def _price_change_pct(symbol: str, start, days: int, is_crypto: bool = False) -> float | None:
    yf_symbol = resolve_yf_symbol(symbol, is_crypto=is_crypto)
    if not yf_symbol:
        return None
    try:
        hist = yf.Ticker(yf_symbol).history(
            start=start.date(), end=(start + pd.Timedelta(days=days + 3)).date()
        )
        if hist.empty:
            return None
        p0 = hist["Close"].iloc[0]
        p1 = hist["Close"].iloc[min(days, len(hist) - 1)]
        return (p1 - p0) / p0 * 100
    except Exception:
        return None


def flag_trades(trades: pd.DataFrame) -> pd.DataFrame:
    flags = []
    for _, t in trades.iterrows():
        reasons = []

        if t["realized_pnl"] is not None and t["realized_pnl"] < 0:
            if t["holding_days"] <= QUICK_LOSS_DAYS:
                reasons.append(f"quick_loss: exited at a loss after only {t['holding_days']}d")
            if t["realized_pnl_pct"] is not None and t["realized_pnl_pct"] <= BIG_LOSS_PCT:
                reasons.append(f"big_loss: {t['realized_pnl_pct']:.1f}% realized loss")

        is_crypto = bool(t.get("is_crypto", False))
        post_sale = _price_change_pct(t["symbol"], t["sell_date"], LOOKAHEAD_DAYS, is_crypto)
        if post_sale is not None and post_sale >= POST_SALE_REGRET_PCT:
            reasons.append(f"sold_too_early: {t['symbol']} rose {post_sale:.1f}% in the {LOOKAHEAD_DAYS}d after you sold")

        post_buy = _price_change_pct(t["symbol"], t["buy_date"], LOOKAHEAD_DAYS, is_crypto)
        if post_buy is not None and post_buy <= POST_BUY_DROP_PCT:
            reasons.append(f"bad_entry: {t['symbol']} dropped {post_buy:.1f}% in the {LOOKAHEAD_DAYS}d after you bought")

        if reasons:
            flags.append({
                "account_id": t.get("account_id"),
                "symbol": t["symbol"],
                "buy_date": t["buy_date"].date(),
                "sell_date": t["sell_date"].date(),
                "realized_pnl": t["realized_pnl"],
                "realized_pnl_pct": t["realized_pnl_pct"],
                "flags": "; ".join(reasons),
            })
    return pd.DataFrame(flags)


def flag_overtrading(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (account, symbol), grp in trades.groupby(["account_id", "symbol"]):
        grp = grp.sort_values("sell_date")
        for i in range(len(grp) - OVERTRADING_MIN_ROUNDTRIPS + 1):
            window = grp.iloc[i:i + OVERTRADING_MIN_ROUNDTRIPS]
            span_days = (window["sell_date"].iloc[-1] - window["buy_date"].iloc[0]).days
            if span_days <= OVERTRADING_WINDOW_DAYS:
                rows.append({
                    "account_id": account,
                    "symbol": symbol,
                    "roundtrips": OVERTRADING_MIN_ROUNDTRIPS,
                    "window_start": window["buy_date"].iloc[0].date(),
                    "window_end": window["sell_date"].iloc[-1].date(),
                    "flags": f"overtrading: {OVERTRADING_MIN_ROUNDTRIPS} round-trips in {span_days}d",
                })
                break  # one flag per symbol/account is enough signal
    return pd.DataFrame(rows)


def main():
    trades = load_trades()
    if trades.empty:
        print("No closed trades with both a buy and sell date yet.")
        return

    print(f"Checking {len(trades)} closed trades against market data (this hits yfinance per trade)...")
    flagged = flag_trades(trades)
    overtrading = flag_overtrading(trades)
    combined = pd.concat([flagged, overtrading], ignore_index=True)
    combined.to_csv(PROCESSED_DIR / "bad_trade_flags.csv", index=False)
    print(f"bad_trade_flags.csv: {len(combined)} flagged trades/patterns out of {len(trades)} closed trades")


if __name__ == "__main__":
    main()
