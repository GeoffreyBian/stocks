"""
Authentication for the Wealthsimple unofficial API (ws-api).

Nothing secret ever touches disk in this repo. The session token (issued
*after* password + 2FA succeed) is stored in the macOS Keychain via `keyring`,
never in a file. Your password and TOTP code are typed interactively at the
terminal and only ever live in process memory.

Run this file directly to do the first-time interactive login:
    .venv/bin/python scripts/auth.py

Other scripts import `get_api()` to reuse the saved session silently.
"""
import getpass

import keyring
from ws_api import OTPRequiredException, WealthsimpleAPI, WSAPISession

KEYRING_SERVICE = "wealthsimple-stocks-folder"
# The email isn't secret, but storing it lets later runs (including
# non-interactive ones, e.g. Claude running fetch_data.py on your behalf
# once a session already exists) reuse a saved session without prompting.
_USERNAME_KEY = "_default_username"


def _load_username() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, _USERNAME_KEY)


def _save_username(username: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _USERNAME_KEY, username)


def _load_session(username: str) -> str | None:
    return keyring.get_password(KEYRING_SERVICE, username)


def _make_persist_fct(username: str):
    # ws-api calls this with either (session_json, username) or just
    # (session_json,) depending on the code path, so absorb both.
    def _persist(session_json: str, *_ignored) -> None:
        keyring.set_password(KEYRING_SERVICE, username, session_json)

    return _persist


def get_api(username: str | None = None) -> WealthsimpleAPI:
    """Return an authenticated WealthsimpleAPI client, prompting interactively
    only if there's no valid saved session."""
    if username is None:
        username = _load_username()
    if username is None:
        username = input("Wealthsimple email: ").strip()
    _save_username(username)

    persist = _make_persist_fct(username)

    saved = _load_session(username)
    if saved:
        try:
            session = WSAPISession.from_json(saved)
            return WealthsimpleAPI.from_token(
                session, persist_session_fct=persist, username=username
            )
        except Exception:
            print("Saved session is no longer valid, logging in again.")

    password = getpass.getpass("Wealthsimple password: ")
    try:
        session = WealthsimpleAPI.login(
            username, password, persist_session_fct=persist
        )
    except OTPRequiredException:
        otp = input("2FA code: ").strip()
        session = WealthsimpleAPI.login(
            username, password, otp_answer=otp, persist_session_fct=persist
        )
    return WealthsimpleAPI.from_token(
        session, persist_session_fct=persist, username=username
    )


if __name__ == "__main__":
    api = get_api()
    accounts = api.get_accounts()
    print(f"Logged in. {len(accounts)} account(s) found:")
    for acct in accounts:
        print(f"  - {acct.get('description')} ({acct.get('number')})")
    print("\nSession saved to macOS Keychain. Future scripts won't prompt again"
          " unless the session expires.")
