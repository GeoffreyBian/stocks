"""Shared yfinance symbol resolution.

Wealthsimple activity data gives plain tickers (e.g. "VFV", "QQC", "BTC")
with no exchange info. Yahoo Finance needs an exchange suffix for anything
not on a US exchange (e.g. "VFV.TO" for the TSX), and a completely different
scheme for crypto ("BTC-USD", not "BTC"). Try candidates in order and cache
whichever one actually has data so we're not guessing on every call.

IMPORTANT: for crypto, always pass is_crypto=True. A bare crypto ticker like
"BTC" can silently match an unrelated equity on Yahoo Finance (there's a real
stock ticker "BTC" trading around $30-40, nothing to do with Bitcoin) - that
false match returns real-looking price history for the wrong instrument
entirely, which is worse than returning nothing. Do not add more equity
suffixes ahead of the crypto path or that collision comes back.
"""
import yfinance as yf

_EQUITY_SUFFIXES = ["", ".TO", ".V", ".NE"]
_CRYPTO_SUFFIXES = ["-USD"]
_resolved_cache: dict[tuple[str, bool], str | None] = {}


def resolve_yf_symbol(symbol: str, is_crypto: bool = False) -> str | None:
    cache_key = (symbol, is_crypto)
    if cache_key in _resolved_cache:
        return _resolved_cache[cache_key]

    resolved = None
    for suffix in (_CRYPTO_SUFFIXES if is_crypto else _EQUITY_SUFFIXES):
        candidate = f"{symbol}{suffix}"
        try:
            hist = yf.Ticker(candidate).history(period="5d")
        except Exception:
            continue
        if not hist.empty:
            resolved = candidate
            break

    _resolved_cache[cache_key] = resolved
    return resolved
