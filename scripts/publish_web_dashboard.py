"""
Encrypt the dashboard snapshot and publish it to geoffreybian.github.io.

    .venv/bin/python scripts/publish_web_dashboard.py
    .venv/bin/python scripts/publish_web_dashboard.py --no-push   # build only

Two things come out of this:

  1. website/portfolio.html - a standalone page with no data in it at all.
     It asks for a passphrase and decrypts in the browser via Web Crypto.
     Written locally; commit it yourself (it only changes when the template does).
  2. An AES-256-GCM blob, force-pushed to the `portfolio-data` branch of the
     website repo as a fresh orphan commit, replacing whatever was there.

The orphan commit is the point. GitHub Pages has no access control and the
website repo is public, so anything committed the normal way is public
forever - deleting it later does nothing, because the old commit is still
reachable. Force-pushing a single-commit branch means only today's ciphertext
exists. That is what makes rotating the passphrase actually work: the blob
encrypted under the old key is gone, rather than sitting in history waiting
for someone who eventually cracks it.
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_key import get_key

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "dashboard_template.html"
SNAPSHOT = ROOT / "dashboard" / "dashboard_data.json"
BLOB_OUT = ROOT / "dashboard" / "portfolio.enc.json"

WEBSITE = Path.home() / "dev" / "website"
PAGE_OUT = WEBSITE / "portfolio.html"

REPO = "GeoffreyBian/geoffreybian.github.io"
REMOTE = f"git@github.com:{REPO}.git"
DATA_BRANCH = "portfolio-data"
BLOB_NAME = "portfolio.enc.json"
BLOB_URL = f"https://raw.githubusercontent.com/{REPO}/{DATA_BRANCH}/{BLOB_NAME}"

# OWASP's current floor for PBKDF2-SHA256. Costs ~1s in the browser, which is
# a fine price once per visit and a brutal multiplier against offline guessing.
ITERATIONS = 600_000


def encrypt(plaintext: bytes, passphrase: str) -> dict:
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, ITERATIONS, dklen=32)
    # AESGCM.encrypt appends the 16-byte tag, which is exactly the layout
    # SubtleCrypto.decrypt expects. Don't split them apart.
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "cipher": "AES-256-GCM",
        "salt": b64(salt),
        "iv": b64(iv),
        "ciphertext": b64(ciphertext),
    }


def build_page() -> str:
    """Wrap the shared template in a full HTML document for Jekyll.

    The template targets the Artifact runtime, which supplies its own
    <head> and a small reset. Standing alone on the website it needs both.
    """
    template = TEMPLATE.read_text()
    if "</style>" not in template:
        raise SystemExit("template has no </style> - can't split head from body")
    head, body = template.split("</style>", 1)
    head += "</style>"

    body = body.replace("__DASHBOARD_DATA_JSON__", "")
    body = body.replace("__ENCRYPTED_DATA_URL__", BLOB_URL)

    return f"""---
layout: none
permalink: /portfolio/
sitemap: false
---
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Encrypted, but there is no reason to be in anyone's index. -->
<meta name="robots" content="noindex, nofollow">
<style>
  body {{ margin: 0; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
{head}
</head>
<body>
{body}
</body>
</html>
"""


def force_push(blob_path: Path) -> None:
    """Replace the data branch with a single commit holding just this blob."""
    def git(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    name = subprocess.run(["git", "-C", str(WEBSITE), "config", "user.name"],
                          capture_output=True, text=True).stdout.strip() or "Geoffrey Bian"
    email = subprocess.run(["git", "-C", str(WEBSITE), "config", "user.email"],
                           capture_output=True, text=True).stdout.strip() or "geoffreybian100@gmail.com"

    with tempfile.TemporaryDirectory() as td:
        git("init", "-q", "-b", DATA_BRANCH, cwd=td)
        shutil.copy(blob_path, os.path.join(td, BLOB_NAME))
        git("add", BLOB_NAME, cwd=td)
        git("-c", f"user.name={name}", "-c", f"user.email={email}",
            "commit", "-q", "-m",
            f"Encrypted portfolio snapshot {datetime.now():%Y-%m-%d}", cwd=td)
        git("push", "-q", "--force", REMOTE, f"{DATA_BRANCH}:{DATA_BRANCH}", cwd=td)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-push", action="store_true",
                    help="build the page and blob locally, don't touch GitHub")
    args = ap.parse_args()

    if not SNAPSHOT.exists():
        raise SystemExit(f"{SNAPSHOT} not found - run refresh_all.py first")
    if not WEBSITE.is_dir():
        raise SystemExit(f"{WEBSITE} not found - is the website repo cloned?")

    passphrase = get_key()
    plaintext = SNAPSHOT.read_bytes()
    blob = encrypt(plaintext, passphrase)
    BLOB_OUT.write_text(json.dumps(blob))
    print(f"Encrypted {len(plaintext):,} bytes -> {len(BLOB_OUT.read_text()):,} bytes")

    PAGE_OUT.write_text(build_page())
    print(f"Wrote {PAGE_OUT}")

    if args.no_push:
        print("--no-push: nothing sent to GitHub.")
        return

    force_push(BLOB_OUT)
    print(f"Force-pushed {BLOB_NAME} to {REPO}@{DATA_BRANCH} (single orphan commit)")
    print("\nIf portfolio.html changed, commit it in ~/dev/website and push to master.")
    print("Live at https://geoffreybian.github.io/portfolio/")


if __name__ == "__main__":
    main()
