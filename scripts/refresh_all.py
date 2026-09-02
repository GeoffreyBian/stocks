"""
Refresh everything: pull from Wealthsimple, rebuild every derived view, and
regenerate the dashboard HTML ready to publish.

Checks the saved session FIRST and stops with a clear message if you need to
log in again, rather than getting halfway through and hanging on a password
prompt.

Usage:
    .venv/bin/python scripts/refresh_all.py
    .venv/bin/python scripts/refresh_all.py --skip-watchlist   # faster, skips the screener
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
SCRIPTS = ROOT / "scripts"

AUTH_HELP = """
────────────────────────────────────────────────────────────────────────
Your Wealthsimple session has expired (or was never created).

Run this yourself in your terminal - it will ask for your password and
2FA code, which must be typed by you, not passed through Claude:

    cd ~/dev/stocks && .venv/bin/python scripts/auth.py

In Claude Code you can run it inline by typing:

    ! cd ~/dev/stocks && .venv/bin/python scripts/auth.py

Then re-run this script.
────────────────────────────────────────────────────────────────────────
"""


def run(name: str, *args: str) -> None:
    print(f"\n▶ {name}")
    result = subprocess.run([str(PYTHON), str(SCRIPTS / name), *args])
    if result.returncode != 0:
        print(f"✗ {name} failed (exit {result.returncode})")
        sys.exit(result.returncode)


def main() -> int:
    skip_watchlist = "--skip-watchlist" in sys.argv

    print("▶ check_auth.py")
    auth = subprocess.run([str(PYTHON), str(SCRIPTS / "check_auth.py")],
                          capture_output=True, text=True)
    print(auth.stdout.strip())
    if auth.returncode != 0:
        print(AUTH_HELP)
        return 1

    run("fetch_data.py")
    run("build_trades.py")
    run("detect_bad_trades.py")
    run("detect_dips.py")
    if not skip_watchlist:
        run("build_watchlist.py")
    else:
        print("\n▶ build_watchlist.py (skipped)")
    run("build_dashboard_snapshot.py")
    run("render_dashboard_html.py")

    print("\n✓ Done. dashboard/dashboard.html is ready to publish.")
    print("  Ask Claude to publish it, or it will redeploy to the same artifact URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
