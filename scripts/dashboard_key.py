"""
Set the passphrase that encrypts the web-published dashboard.

Run this yourself, in your own terminal - not through Claude:

    .venv/bin/python scripts/dashboard_key.py

The passphrase is stored in the macOS Keychain and never touches this repo,
git, or a conversation. Losing it just means running this again and
republishing; there is nothing to recover.

On strength: the encrypted blob is served from a public URL, so anyone who
wants it can copy it once and then guess offline, forever, at whatever rate
their hardware allows. No server is there to rate-limit them. That makes the
passphrase the entire security model, which is why this generates one for you
instead of trusting a phrase you invent.
"""
import secrets
import sys
from getpass import getpass
from math import log2

import keyring

KEYRING_SERVICE = "wealthsimple-stocks-folder"
KEY_ACCOUNT = "dashboard-passphrase"

WORDLIST = "/usr/share/dict/words"
N_WORDS = 6


def _pool() -> list[str]:
    """Short, plain-ASCII words from the system dictionary.

    Capping length at 7 keeps the phrase typeable on a phone; the pool stays
    big enough (~10k+) that six words clear 75 bits regardless.
    """
    with open(WORDLIST) as fh:
        words = {w.strip().lower() for w in fh}
    return sorted(w for w in words if 4 <= len(w) <= 7 and w.isalpha() and w.isascii())


def generate() -> tuple[str, float]:
    """Return (passphrase, bits of entropy)."""
    try:
        pool = _pool()
    except OSError:
        pool = []
    if len(pool) < 4096:
        # No usable dictionary - fall back to raw randomness over memorability.
        return secrets.token_urlsafe(24), 24 * 8 * 0.75
    phrase = "-".join(secrets.choice(pool) for _ in range(N_WORDS))
    return phrase, N_WORDS * log2(len(pool))


def get_key() -> str:
    """Fetch the passphrase, or exit with instructions if it isn't set yet."""
    key = keyring.get_password(KEYRING_SERVICE, KEY_ACCOUNT)
    if not key:
        sys.exit(
            "No dashboard passphrase set yet. Run this in your own terminal:\n"
            "    .venv/bin/python scripts/dashboard_key.py"
        )
    return key


def main() -> None:
    if keyring.get_password(KEYRING_SERVICE, KEY_ACCOUNT):
        print("A passphrase is already set.")
        print("Replacing it is fine - the next publish force-pushes a fresh blob,")
        print("so the old ciphertext stops existing rather than lingering in history.")
        if input("Replace it? [y/N] ").strip().lower() != "y":
            print("Left unchanged.")
            return

    suggestion, bits = generate()
    print()
    print("Suggested passphrase (save it to your password manager now):")
    print(f"\n    {suggestion}\n")
    print(f"That's about {bits:.0f} bits of entropy.")
    print("Press Enter to use it, or type your own instead.")
    print()

    chosen = getpass("Passphrase [Enter for the suggestion]: ")
    if not chosen:
        chosen = suggestion
    else:
        if len(chosen) < 12:
            sys.exit("Too short. Offline guessing is unlimited here - use 12+ characters.")
        if getpass("Confirm: ") != chosen:
            sys.exit("Those didn't match. Nothing was saved.")

    keyring.set_password(KEYRING_SERVICE, KEY_ACCOUNT, chosen)
    print("\nSaved to the Keychain.")
    print("Next: .venv/bin/python scripts/publish_web_dashboard.py")


if __name__ == "__main__":
    main()
