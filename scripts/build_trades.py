"""
Turn the raw activity log (data/processed/activities.csv) into a closed-trade
ledger: FIFO-matched buy/sell pairs with realized P&L and holding period.

Usage:
    .venv/bin/python scripts/build_trades.py

Writes:
    data/processed/trades.csv   - one row per closed (fully or partially matched) lot
    data/processed/open_positions.csv - unmatched buy lots still open
"""
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"


def load_trade_activities() -> pd.DataFrame:
    path = PROCESSED_DIR / "activities.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run fetch_data.py first")
    df = pd.read_csv(path)
    df = df[df["side"].isin(["BUY", "SELL"])].copy()
    df["occurredAt"] = pd.to_datetime(df["occurredAt"])
    df = df.sort_values("occurredAt")
    return df


def fifo_match(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    group_key = "accountId" if "accountId" in df.columns else None
    closed_rows = []
    open_lots: dict[tuple, deque] = defaultdict(deque)

    for _, row in df.iterrows():
        # Match by securityId, not the display symbol - two different option
        # contracts on the same underlying can share a symbol but are
        # different instruments, while securityId is unique per instrument.
        key = (row.get(group_key) if group_key else None, row.get("securityId"), row["symbol"])
        qty = float(row["assetQuantity"])
        price = float(row["price_per_share"])
        date = row["occurredAt"]
        is_crypto = str(row.get("type", "")).startswith("CRYPTO")

        if row["side"] == "BUY":
            open_lots[key].append({"qty": qty, "price": price, "date": date, "is_crypto": is_crypto})
            continue

        # SELL: consume open lots FIFO
        remaining = qty
        while remaining > 1e-9 and open_lots[key]:
            lot = open_lots[key][0]
            matched_qty = min(remaining, lot["qty"])
            pnl = (price - lot["price"]) * matched_qty
            cost = lot["price"] * matched_qty
            closed_rows.append({
                "account_id": key[0],
                "symbol": row["symbol"],
                "is_crypto": is_crypto,
                "buy_date": lot["date"],
                "sell_date": date,
                "quantity": matched_qty,
                "buy_price": lot["price"],
                "sell_price": price,
                "realized_pnl": pnl,
                "realized_pnl_pct": (pnl / cost * 100) if cost else None,
                "holding_days": (date - lot["date"]).days,
            })
            lot["qty"] -= matched_qty
            remaining -= matched_qty
            if lot["qty"] <= 1e-9:
                open_lots[key].popleft()
        if remaining > 1e-9:
            # Sold more than we have buy history for (data starts mid-position) -
            # record it with no matched buy so it's visible, not silently dropped.
            closed_rows.append({
                "account_id": key[0],
                "symbol": row["symbol"],
                "is_crypto": is_crypto,
                "buy_date": None,
                "sell_date": date,
                "quantity": remaining,
                "buy_price": None,
                "sell_price": price,
                "realized_pnl": None,
                "realized_pnl_pct": None,
                "holding_days": None,
                "note": "sold with no matching buy in fetched history",
            })

    open_rows = []
    for key, lots in open_lots.items():
        for lot in lots:
            if lot["qty"] > 1e-9:
                open_rows.append({
                    "account_id": key[0],
                    "symbol": key[2],
                    "is_crypto": lot["is_crypto"],
                    "buy_date": lot["date"],
                    "quantity": lot["qty"],
                    "buy_price": lot["price"],
                })

    return pd.DataFrame(closed_rows), pd.DataFrame(open_rows)


def main():
    df = load_trade_activities()
    if df.empty:
        print("No BUY/SELL activities found yet.")
        return
    closed, open_positions = fifo_match(df)
    closed.to_csv(PROCESSED_DIR / "trades.csv", index=False)
    open_positions.to_csv(PROCESSED_DIR / "open_positions.csv", index=False)
    print(f"trades.csv: {len(closed)} closed lots")
    print(f"open_positions.csv: {len(open_positions)} open lots")


if __name__ == "__main__":
    main()
