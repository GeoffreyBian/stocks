"""
Aggregate everything in data/processed/ into one small JSON snapshot to embed
in the published dashboard Artifact. Only aggregated/derived numbers go in -
no account numbers, no credentials.

Usage:
    .venv/bin/python scripts/build_dashboard_snapshot.py

Writes:
    dashboard/dashboard_data.json
"""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
DASHBOARD_DIR = ROOT / "dashboard"

ACCOUNT_TYPE_LABELS = {
    "SELF_DIRECTED_TFSA": "TFSA",
    "SELF_DIRECTED_FHSA": "FHSA",
    "SELF_DIRECTED_RRSP": "RRSP",
    "SELF_DIRECTED_NON_REGISTERED": "Non-registered",
    "SELF_DIRECTED_NON_REGISTERED_MARGIN": "Margin",
    "SELF_DIRECTED_CRYPTO": "Crypto",
    "CASH": "Cash (CAD)",
    "CASH_USD": "Cash (USD)",
}


def _sec_id_norm(s: str) -> str:
    return str(s).strip().lower()


def build_symbol_map() -> dict[str, dict]:
    """security.id (lowercased) -> {symbol, name} from realized_returns + activities."""
    mapping: dict[str, dict] = {}

    rr_path = PROCESSED_DIR / "realized_returns.csv"
    if rr_path.exists():
        rr = pd.read_csv(rr_path)
        if not rr.empty and "securityBreakdown.edges" in rr.columns:
            edges = ast.literal_eval(rr.iloc[0]["securityBreakdown.edges"])
            for edge in edges:
                sec = edge["node"]["security"]
                stock = sec.get("stock") or {}
                symbol = stock.get("symbol")
                if symbol:
                    mapping[_sec_id_norm(sec["id"])] = {
                        "symbol": symbol,
                        "name": stock.get("name") or symbol,
                    }

    act_path = PROCESSED_DIR / "activities.csv"
    if act_path.exists():
        act = pd.read_csv(act_path)
        act = act.dropna(subset=["securityId", "symbol"]) if "securityId" in act.columns else act.iloc[0:0]
        for _, row in act.iterrows():
            key = _sec_id_norm(row["securityId"])
            mapping.setdefault(key, {"symbol": row["symbol"], "name": row["symbol"]})

    return mapping


def build_holdings(symbol_map: dict) -> list[dict]:
    """positions.csv has one row per (account, security) - aggregate to one
    row per symbol across all accounts, since that's what "a holding" means
    for a portfolio-level dashboard."""
    path = PROCESSED_DIR / "positions.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if df.empty:
        return []
    latest_date = df["snapshot_date"].max()
    df = df[df["snapshot_date"] == latest_date].copy()

    df["symbol"] = df["security.id"].apply(
        lambda s: symbol_map.get(_sec_id_norm(s), {"symbol": _sec_id_norm(s)[:12]})["symbol"]
    )
    df["name"] = df["security.id"].apply(
        lambda s: symbol_map.get(_sec_id_norm(s), {"name": "Unknown"})["name"]
    )
    # Note: grouping by display symbol can combine genuinely different
    # securities that share a ticker string (e.g. a US listing and its CAD
    # CDR both show as "AMZN"), so position_count isn't literally an account
    # count - it's how many distinct position rows rolled into this symbol.
    grouped = df.groupby(["symbol", "name"], as_index=False).agg(
        market_value=("totalValue.amount", "sum"),
        unrealized_pnl=("unrealizedReturns.amount", "sum"),
        book_value=("bookValue.amount", "sum"),
        position_count=("security.id", "count"),
    )
    total_portfolio_value = grouped["market_value"].sum()

    holdings = []
    for _, row in grouped.iterrows():
        holdings.append({
            "symbol": row["symbol"],
            "name": row["name"],
            "market_value": round(float(row["market_value"]), 2),
            "unrealized_pnl": round(float(row["unrealized_pnl"]), 2),
            "unrealized_pnl_pct": round(float(row["unrealized_pnl"]) / float(row["book_value"]) * 100, 1)
                if row["book_value"] else None,
            "pct_of_portfolio": round(float(row["market_value"]) / total_portfolio_value * 100, 1)
                if total_portfolio_value else None,
            "position_count": int(row["position_count"]),
        })
    holdings.sort(key=lambda h: h["market_value"] or 0, reverse=True)
    return holdings


def build_realized_summary(symbol_map: dict) -> dict:
    path = PROCESSED_DIR / "realized_returns.csv"
    if not path.exists():
        return {"total": None, "by_security": []}
    df = pd.read_csv(path)
    if df.empty:
        return {"total": None, "by_security": []}
    total = float(df.iloc[0]["totalValue.amount"])
    edges = ast.literal_eval(df.iloc[0]["securityBreakdown.edges"])
    by_security = []
    for edge in edges:
        sec = edge["node"]["security"]
        stock = sec.get("stock") or {}
        symbol = stock.get("symbol") or sec.get("id")
        by_security.append({
            "symbol": symbol,
            "realized_pnl": round(float(edge["node"]["totalValue"]["amount"]), 2),
        })
    by_security.sort(key=lambda r: r["realized_pnl"], reverse=True)
    return {"total": round(total, 2), "by_security": by_security}


def build_win_rate() -> dict:
    path = PROCESSED_DIR / "trades.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path).dropna(subset=["realized_pnl"])
    if df.empty:
        return {}
    wins = int((df["realized_pnl"] > 0).sum())
    losses = int((df["realized_pnl"] < 0).sum())
    return {
        "closed_trades": len(df),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) else None,
        "avg_win": round(df.loc[df["realized_pnl"] > 0, "realized_pnl"].mean(), 2) if wins else None,
        "avg_loss": round(df.loc[df["realized_pnl"] < 0, "realized_pnl"].mean(), 2) if losses else None,
        "avg_holding_days": round(df["holding_days"].mean(), 1),
    }


def build_bad_trades() -> list[dict]:
    path = PROCESSED_DIR / "bad_trade_flags.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return json.loads(df.to_json(orient="records"))


def build_dip_summary(current_symbols: set[str]) -> dict:
    path = PROCESSED_DIR / "dip_events.csv"
    if not path.exists():
        return {"benchmarks": [], "dips_with_activity": [], "notable_dips_missed": []}
    df = pd.read_csv(path)
    if df.empty:
        return {"benchmarks": [], "dips_with_activity": [], "notable_dips_missed": []}

    benchmarks = df[df["symbol"].isin(["^GSPC", "^GSPTSE"])].copy()
    benchmarks = benchmarks.sort_values("dip_low_pct")
    bench_rows = json.loads(benchmarks.to_json(orient="records"))

    held = df[~df["symbol"].isin(["^GSPC", "^GSPTSE"])].copy()

    bought_count = int(held["your_activity"].str.contains("BUY", na=False).sum())
    sold_count = int(held["your_activity"].str.contains("SELL", na=False).sum())
    sat_out_count = int((held["your_activity"] == "no trades during this dip").sum())

    # The interesting rows for a dashboard: dips you actually traded during
    # (small, high-signal), plus the biggest dips you sat out - but only for
    # symbols still in the portfolio today, to avoid dredging up ancient
    # closed positions.
    with_activity = held[held["your_activity"] != "no trades during this dip"].copy()
    with_activity = with_activity.sort_values("dip_low_pct")

    missed = held[
        (held["your_activity"] == "no trades during this dip")
        & (held["symbol"].isin(current_symbols))
    ].copy()
    missed = missed.sort_values("dip_low_pct").head(10)

    return {
        "benchmarks": bench_rows,
        "dips_with_activity": json.loads(with_activity.to_json(orient="records")),
        "notable_dips_missed": json.loads(missed.to_json(orient="records")),
        "dips_bought": bought_count,
        "dips_sold_into": sold_count,
        "dips_sat_out": sat_out_count,
    }


def build_accounts() -> list[dict]:
    path = PROCESSED_DIR / "accounts.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    out = []
    for _, row in df.iterrows():
        acct_type = row.get("unifiedAccountType")
        out.append({
            "label": ACCOUNT_TYPE_LABELS.get(acct_type, acct_type),
            "currency": row.get("currency"),
        })
    return out


def main():
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    symbol_map = build_symbol_map()
    holdings = build_holdings(symbol_map)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": build_accounts(),
        "portfolio_summary": {
            "total_market_value": round(sum(h["market_value"] or 0 for h in holdings), 2),
            "total_unrealized_pnl": round(sum(h["unrealized_pnl"] or 0 for h in holdings), 2),
        },
        "holdings": holdings,
        "realized": build_realized_summary(symbol_map),
        "win_rate": build_win_rate(),
        "bad_trades": build_bad_trades(),
        "dips": build_dip_summary({h["symbol"] for h in holdings}),
    }

    out_path = DASHBOARD_DIR / "dashboard_data.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"Wrote {out_path.relative_to(ROOT)}")
    print(f"  holdings: {len(holdings)}")
    print(f"  bad_trades: {len(snapshot['bad_trades'])}")
    print(f"  benchmark dips: {len(snapshot['dips']['benchmarks'])}")
    print(f"  dips with your activity: {len(snapshot['dips']['dips_with_activity'])}")
    print(f"  notable dips missed: {len(snapshot['dips']['notable_dips_missed'])}")


if __name__ == "__main__":
    main()
