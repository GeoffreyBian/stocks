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
    "OPTIONS_BUY", "OPTIONS_SELL",
}


def _enrich_activities_with_symbols(activities: list) -> None:
    """Add a plain ticker symbol + per-share price to each trade activity.

    Raw trade activities already carry `assetSymbol` (a real ticker, e.g.
    "NVDA") directly from Wealthsimple - no extra API calls needed. (An
    earlier version of this tried resolving `securityId` via
    `api.security_id_to_symbol()`, but that call is case-sensitive and
    Wealthsimple's activity feed returns securityId in a different case than
    the lookup expects, so it silently failed for every security. Don't
    reintroduce that path - assetSymbol is simpler and already correct.)
    """
    for act in activities:
        if act.get("type") not in TRADE_TYPES:
            continue
        act["symbol"] = act.get("assetSymbol")
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
        _enrich_activities_with_symbols(raw["activities"])
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
        # account_ids is required in practice - calling this without it returns
        # an empty list rather than erroring, which silently costs you the
        # entire portfolio-value time series.
        #
        # end_date is required too, for a subtler reason: the endpoint always
        # downsamples a multi-year range to ~110 points (weekly), and with no
        # end_date it anchors that last point to the previous completed week.
        # That left the headline total up to 7 days stale - it read $207,310
        # (Aug 26) while the app showed $209,802 (Sep 2). Passing end_date=now
        # keeps the same weekly resolution but ends the series on today.
        raw["identity_historical_financials"] = api.get_identity_historical_financials(
            account_ids=account_ids,
            currency=CURRENCY,
            end_date=datetime.now(),
        )
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

    # positions.csv - ONE snapshot per calendar day. Rerunning on the same day
    # replaces that day's rows rather than appending a second copy: appending
    # would double-count every holding for anyone summing the latest snapshot.
    if raw["positions"]:
        pos_df = pd.json_normalize(raw["positions"])
        pos_df["snapshot_date"] = today
        pos_path = PROCESSED_DIR / "positions.csv"
        if pos_path.exists():
            existing = pd.read_csv(pos_path)
            existing = existing[existing["snapshot_date"] != today]
            combined = pd.concat([existing, pos_df], ignore_index=True)
        else:
            combined = pos_df
        combined.to_csv(pos_path, index=False)
        print(f"  positions.csv: snapshot for {today} ({len(pos_df)} positions)")

    # performance.csv - the portfolio value time series (weekly), overwritten.
    # netLiquidationValue is the authoritative total portfolio value; netDeposits
    # is money you put in, so the gap between them is your actual gain.
    hist = raw.get("identity_historical_financials") or []
    if hist:
        perf = pd.DataFrame([{
            "date": h["date"],
            "net_liquidation_value": float(h["netLiquidationValueV2"]["amount"]),
            "net_deposits": float(h["netDepositsV2"]["amount"]),
        } for h in hist]).sort_values("date")
        perf.to_csv(PROCESSED_DIR / "performance.csv", index=False)
        print(f"  performance.csv: {len(perf)} points, latest "
              f"${perf.iloc[-1]['net_liquidation_value']:,.0f}")

    # cash.csv - cash balances per account (positions cover securities only)
    cash_rows = []
    for aid, bal in (raw.get("balances") or {}).items():
        if not isinstance(bal, dict):
            continue
        for key, amount in bal.items():
            if key.startswith("sec-c-"):  # sec-c-cad / sec-c-usd are cash
                cash_rows.append({
                    "account_id": aid,
                    "currency": key.replace("sec-c-", "").upper(),
                    "amount": float(amount),
                })
    if cash_rows:
        pd.DataFrame(cash_rows).to_csv(PROCESSED_DIR / "cash.csv", index=False)
        print(f"  cash.csv: {len(cash_rows)} balances")

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
