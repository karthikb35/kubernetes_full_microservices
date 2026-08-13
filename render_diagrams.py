"""
Local Mermaid -> PNG renderer for the K8s Architecture textbook.

Reuses the PARENT repo's node_modules (@mermaid-js/mermaid-cli) and system
Chrome (via ../puppeteer-config.json) so nothing new needs installing.

Usage:
  python render_diagrams.py            # render all diagrams
  python render_diagrams.py 03         # render only keys starting with '03'
"""
import os
import pathlib
import subprocess
import sys
import tempfile

from diagrams import DIAGRAMS

HERE = pathlib.Path(__file__).parent
PARENT = HERE.parent
OUT_DIR = HERE / "assets" / "diagrams"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CLI = PARENT / "node_modules" / "@mermaid-js" / "mermaid-cli" / "src" / "cli.js"
PUPPETEER_CFG = PARENT / "puppeteer-config.json"


def render(name: str, mermaid_src: str) -> bool:
    out_path = OUT_DIR / f"{name}.png"
    with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(mermaid_src.strip())
        src_path = fh.name
    try:
        proc = subprocess.run(
            ["node", str(CLI), "-i", src_path, "-o", str(out_path),
             "-p", str(PUPPETEER_CFG), "-b", "white", "-w", "1600"],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"},
        )
        if out_path.exists() and out_path.stat().st_size > 500:
            print(f"  OK   {name}.png ({out_path.stat().st_size} bytes)")
            return True
        print(f"  FAIL {name}: {proc.stderr.strip()[:400]}")
        return False
    except Exception as exc:
        print(f"  FAIL {name}: {exc}")
        return False
    finally:
        pathlib.Path(src_path).unlink(missing_ok=True)


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    items = {k: v for k, v in DIAGRAMS.items()
             if (only is None or k.startswith(only))}
    print(f"Rendering {len(items)} diagram(s) via mermaid-cli...")
    failures = 0
    for name, src in items.items():
        if not render(name, src):
            failures += 1
    print(f"Done. {len(items) - failures} ok, {failures} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
