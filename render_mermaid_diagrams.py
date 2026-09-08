"""
Renders every Mermaid source (mermaid/*.mmd) to a PNG in assets/diagrams/ using
the public mermaid.ink rendering service. Re-run after editing any .mmd file,
then rebuild the site (`make html`) and the PDF (`python build_pdf.py`).

The generated PNGs are committed to the repo, so building the site/PDF does not
require network access — only re-rendering does.

Usage:
    python render_mermaid_diagrams.py
"""
import base64
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "mermaid"
OUT = ROOT / "assets" / "diagrams"
BASE = "https://mermaid.ink/img"
PARAMS = "type=png&bgColor=ffffff"


def render_one(src_text: str) -> bytes:
    enc = base64.urlsafe_b64encode(src_text.encode("utf-8")).decode("ascii")
    url = f"{BASE}/{enc}?{PARAMS}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=90).read()


def render() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sources = sorted(SRC.glob("*.mmd"))
    if not sources:
        raise SystemExit(f"No .mmd files found in {SRC}")

    for mmd in sources:
        png = OUT / f"{mmd.stem}.png"
        print(f"Rendering {mmd.name} -> assets/diagrams/{png.name}")
        text = mmd.read_text(encoding="utf-8")
        for attempt in range(1, 4):
            try:
                data = render_one(text)
                if data[:4] != b"\x89PNG":
                    raise ValueError(f"unexpected content (not PNG): {data[:16]!r}")
                png.write_bytes(data)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
                if attempt == 3:
                    raise SystemExit(f"Render failed for {mmd.name}: {exc}")
                time.sleep(2 * attempt)

    print(f"Rendered {len(sources)} diagram(s) into {OUT}")


if __name__ == "__main__":
    render()
    sys.exit(0)
