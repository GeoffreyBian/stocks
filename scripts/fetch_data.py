"""
Pull a fresh snapshot from Wealthsimple and update the local data files.

Usage:
    .venv/bin/python scripts/fetch_data.py

Writes:
    data/raw/<timestamp>.json       - full raw API responses for this run (audit trail)
    data/processed/accounts.csv     - overwritten each run (small, current state)
    data/processed/activities.csv   - appended + deduped by canonicalId (full history)
    data/processed/positions.csv    - appended, one snapshot per run (time series)
    data/processed/realized_returns.csv  - overwritten each run
    data/processed/dividends.csv    - overwritten each run

All of data/ is gitignored - nothing here should ever be committed.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from auth import get_api

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CURRENCY = "CAD"


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


TRADE_TYPES = {
    "DIY_BUY", "DIY_SELL", "MANAGED_BUY", "MANAGED_SELL",
    "CRYPTO_BUY", "CRYPTO_SELL", "NEW_ISSUE_BUY",
}


def _enrich_activities_with_symbols(api, activities: list) -> None:
    """Add a resolved ticker symbol + per-share price to each trade activity,
    since raw activities only carry an opaque securityId + total dollar amount."""
    symbol_cache: dict[str, str] = {}
    for act in activities:
        security_id = act.get("securityId")
        if not security_id:
            continue
        if security_id not in symbol_cache:
            try:
                symbol_cache[security_id] = api.security_id_to_symbol(security_id)
            except Exception:
                symbol_cache[security_id] = None
        act["symbol"] = symbol_cache[security_id]

        if act.get("type") in TRADE_TYPES:
            qty = act.get("assetQuantity")
            amount = act.get("amount")
            if qty and amount:
                act["side"] = "BUY" if act["type"].endswith("_BUY") else "SELL"
                act["price_per_share"] = float(amount) / float(qty)


def fetch_raw(api) -> dict:
    accounts = api.get_accounts()
    account_ids = [a["id"] for a in accounts]

    raw = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
        "balances": {},
        "unrealized_pnl": {},
        "activities": [],
        "positions": None,
        "realized_returns": None,
        "dividends": None,
        "identity_historical_financials": None,
    }

    for acct in accounts:
        aid = acct["id"]
        try:
            raw["balances"][aid] = api.get_account_balances(aid)
        except Exception as e:
            print(f"  ! balances failed for {acct.get('description')}: {e}")
        try:
            raw["unrealized_pnl"][aid] = api.get_account_unrealized_pnl(aid, CURRENCY)
        except Exception as e:
            print(f"  ! unrealized pnl failed for {acct.get('description')}: {e}")

    try:
        raw["activities"] = api.get_activities(account_ids, load_all=True)
        _enrich_activities_with_symbols(api, raw["activities"])
    except Exception as e:
        print(f"  ! activities failed: {e}")

    try:
        raw["positions"] = api.get_identity_positions(None, CURRENCY)
    except Exception as e:
        print(f"  ! positions failed: {e}")

    try:
        raw["realized_returns"] = api.get_identity_realized_returns(CURRENCY)
    except Exception as e:
        print(f"  ! realized returns failed: {e}")

    try:
        raw["dividends"] = api.get_dividends(CURRENCY)
    except Exception as e:
        print(f"  ! dividends failed: {e}")

    try:
        raw["identity_historical_financials"] = api.get_identity_historical_financials(
            currency=CURRENCY, resolution="WEEKLY"
        ) if hasattr(api, "get_identity_historical_financials") else None
    except Exception as e:
        print(f"  ! historical financials failed: {e}")

    return raw


def save_raw(raw: dict) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{ts}.json"
    path.write_text(json.dumps(raw, indent=2, default=_json_default))
    return path


def update_processed(raw: dict) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()

    # accounts.csv - overwritten, small
    accounts_df = pd.json_normalize(raw["accounts"])
    accounts_df.to_csv(PROCESSED_DIR / "accounts.csv", index=False)

    # activities.csv - append + dedup on canonicalId (the API's stable txn id)
    if raw["activities"]:
        new_activities = pd.json_normalize(raw["activities"])
        act_path = PROCESSED_DIR / "activities.csv"
        if act_path.exists():
            existing = pd.read_csv(act_path)
            combined = pd.concat([existing, new_activities], ignore_index=True)
            key = "canonicalId" if "canonicalId" in combined.columns else None
            if key:
                combined = combined.drop_duplicates(subset=[key], keep="last")
        else:
            combined = new_activities
        combined.to_csv(act_path, index=False)
        print(f"  activities.csv: {len(combined)} total rows")

    # positions.csv - append one dated snapshot per run (time series of holdings)
    if raw["positions"]:
        pos_df = pd.json_normalize(raw["positions"])
        pos_df["snapshot_date"] = today
        pos_path = PROCESSED_DIR / "positions.csv"
        if pos_path.exists():
            existing = pd.read_csv(pos_path)
            combined = pd.concat([existing, pos_df], ignore_index=True)
        else:
            combined = pos_df
        combined.to_csv(pos_path, index=False)
        print(f"  positions.csv: snapshot for {today} added")

    # realized_returns.csv / dividends.csv - overwritten, current view
    if raw["realized_returns"]:
        pd.json_normalize(raw["realized_returns"]).to_csv(
            PROCESSED_DIR / "realized_returns.csv", index=False
        )
    if raw["dividends"]:
        pd.json_normalize(raw["dividends"]).to_csv(
            PROCESSED_DIR / "dividends.csv", index=False
        )


def main():
    print("Logging in...")
    api = get_api()
    print("Fetching data from Wealthsimple...")
    raw = fetch_raw(api)
    raw_path = save_raw(raw)
    print(f"Raw snapshot saved: {raw_path.relative_to(ROOT)}")
    update_processed(raw)
    print("Done.")


if __name__ == "__main__":
    main()
