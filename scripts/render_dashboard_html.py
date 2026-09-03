"""
Inject a dashboard snapshot JSON into dashboard/dashboard_template.html to
produce a self-contained HTML page, ready to publish via the Artifact tool.

Usage:
    .venv/bin/python scripts/render_dashboard_html.py
    .venv/bin/python scripts/render_dashboard_html.py --data dashboard/demo_data.json \
                                                      --out  dashboard/demo.html
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"
TEMPLATE_PATH = DASHBOARD_DIR / "dashboard_template.html"


def render(data_path: Path, out_path: Path) -> None:
    data_path = data_path.resolve()
    out_path = out_path.resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} not found - run build_dashboard_snapshot.py first")
    template = TEMPLATE_PATH.read_text()
    data = data_path.read_text().replace("</script>", "<\\/script>")
    out = template.replace("__DASHBOARD_DATA_JSON__", data)
    out_path.write_text(out)
    try:
        shown = out_path.relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"Wrote {shown} ({len(out)} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=DASHBOARD_DIR / "dashboard_data.json",
                    help="snapshot JSON to embed (default: dashboard/dashboard_data.json)")
    ap.add_argument("--out", type=Path, default=DASHBOARD_DIR / "dashboard.html",
                    help="HTML file to write (default: dashboard/dashboard.html)")
    args = ap.parse_args()
    render(args.data, args.out)


if __name__ == "__main__":
    main()
