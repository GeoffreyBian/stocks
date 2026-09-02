"""
Inject dashboard/dashboard_data.json into dashboard/dashboard_template.html
to produce dashboard/dashboard.html, ready to publish via the Artifact tool.

Usage:
    .venv/bin/python scripts/render_dashboard_html.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"
TEMPLATE_PATH = DASHBOARD_DIR / "dashboard_template.html"
DATA_PATH = DASHBOARD_DIR / "dashboard_data.json"
OUT_PATH = DASHBOARD_DIR / "dashboard.html"


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"{DATA_PATH} not found - run build_dashboard_snapshot.py first")
    template = TEMPLATE_PATH.read_text()
    data = DATA_PATH.read_text().replace("</script>", "<\\/script>")
    out = template.replace("__DASHBOARD_DATA_JSON__", data)
    OUT_PATH.write_text(out)
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
