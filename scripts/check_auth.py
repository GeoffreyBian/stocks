"""
Is the saved Wealthsimple session still usable?

Exits 0 if yes, 1 if the user needs to re-authenticate. Crucially this NEVER
prompts for anything - it's safe to run non-interactively (e.g. by Claude via
a tool call), which is the whole point: it answers "do I need to ask the user
to log in?" without itself blocking on stdin.

Usage:
    .venv/bin/python scripts/check_auth.py
"""
import sys

import keyring
from ws_api import WealthsimpleAPI, WSAPISession

from auth import KEYRING_SERVICE, _USERNAME_KEY, _make_persist_fct

NEEDS_AUTH = 1
OK = 0


def main() -> int:
    username = keyring.get_password(KEYRING_SERVICE, _USERNAME_KEY)
    if not username:
        print("NEEDS_AUTH: no saved account - first-time login required.")
        return NEEDS_AUTH

    saved = keyring.get_password(KEYRING_SERVICE, username)
    if not saved:
        print("NEEDS_AUTH: no saved session in the Keychain.")
        return NEEDS_AUTH

    try:
        session = WSAPISession.from_json(saved)
        api = WealthsimpleAPI.from_token(
            session, persist_session_fct=_make_persist_fct(username), username=username
        )
        accounts = api.get_accounts()
    except Exception as e:
        print(f"NEEDS_AUTH: saved session rejected ({type(e).__name__}: {e})")
        return NEEDS_AUTH

    print(f"OK: session valid, {len(accounts)} accounts reachable.")
    return OK


if __name__ == "__main__":
    sys.exit(main())
