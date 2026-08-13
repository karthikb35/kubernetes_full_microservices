"""
Builds k8s-architecture.pdf from all markdown files in docs/, concatenated in
filename order. Re-run after editing any chapter.

Usage:
    python build_pdf.py
"""
import io
from pathlib import Path

import markdown
from xhtml2pdf import pisa

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
OUTPUT = ROOT / "k8s-architecture.pdf"

CSS = """
<style>
    @page {
        size: A4;
        margin: 2cm 1.8cm 2.2cm 1.8cm;
        @frame footer_frame {
            -pdf-frame-content: footer_content;
            bottom: 0.6cm; margin-left: 1.8cm; margin-right: 1.8cm; height: 1cm;
        }
    }
    body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #232323; }

    h1 { font-size: 26pt; color: #0b3d91; border-bottom: 3px solid #f0a500;
         padding-bottom: 10px; margin-top: 0; margin-bottom: 14px; }
    h2 { font-size: 16pt; color: #ffffff; background-color: #0b3d91;
         padding: 9px 12px; margin-top: 22px; margin-bottom: 12px; page-break-before: always; }
    h3 { font-size: 13pt; color: #0b3d91; margin-top: 18px; margin-bottom: 6px;
         border-bottom: 1px solid #dfe6f2; padding-bottom: 3px; }
    h4 { font-size: 11.5pt; color: #16325c; margin-top: 12px; margin-bottom: 4px; }

    p { margin: 7px 0; text-align: justify; }
    strong { color: #12325c; }
    code { font-family: Courier, monospace; background-color: #eef1f6; color: #9c1f4a;
           padding: 1px 4px; font-size: 9pt; }
    pre { font-family: Courier, monospace; background-color: #f6f8fa; color: #1a2a4a;
          padding: 10px 12px; font-size: 8.5pt; border: 1px solid #e2e6ee;
          border-left: 4px solid #f0a500;
          white-space: pre; line-height: 1.35; margin: 10px 0; }
    pre code { background-color: #f6f8fa; color: #1a2a4a; padding: 0; }

    table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 9pt; }
    th { background-color: #0b3d91; color: white; padding: 6px 8px; text-align: left; }
    td { border: 0.5px solid #c4ccd8; padding: 6px 8px; vertical-align: top; }
    tr:nth-child(even) td { background-color: #f2f5fa; }

    blockquote { background-color: #eef3fb; border-left: 4px solid #0b3d91;
                 margin: 10px 0; padding: 8px 12px; color: #2a3f5f; }

    hr { border: none; border-top: 1px solid #d5dbe5; margin: 16px 0; }
    a { color: #0b3d91; text-decoration: none; }
    ul, ol { margin: 6px 0; }
    li { margin: 4px 0; }
    img { max-width: 100%; margin: 12px auto; display: block;
          border: 1px solid #dfe6f2; padding: 4px; background-color: #ffffff; }

    /* ---- Textbook callout boxes (admonition extension) ---- */
    .admonition { margin: 12px 0; padding: 8px 12px; border-left: 5px solid #0b3d91;
                  background-color: #eef3fb; page-break-inside: avoid; }
    .admonition-title { font-weight: bold; font-size: 10.5pt; color: #0b3d91;
                        margin: 0 0 5px 0; padding-bottom: 3px;
                        border-bottom: 0.5px solid #cdd8ea; }
    .admonition p { margin: 5px 0; text-align: left; }
    .admonition ol, .admonition ul { margin: 4px 0; }

    .example  { background-color: #eef8f1; border-left-color: #1b7a3d; }
    .tip      { background-color: #e8f6fb; border-left-color: #0e6b8a; }
    .note     { background-color: #eef3fb; border-left-color: #0b3d91; }
    .warning  { background-color: #fff6e6; border-left-color: #a5670a; }
    .key      { background-color: #fdeef0; border-left-color: #a61b1b; }
    .mental   { background-color: #f0edfb; border-left-color: #5b3fa0; }
    .question { background-color: #f4f0fb; border-left-color: #6a3fb0; }
    .success  { background-color: #eaf7ef; border-left-color: #1b7a3d; }

    .example  .admonition-title { color: #1b7a3d; border-bottom-color: #c3e6d1; }
    .tip      .admonition-title { color: #0e6b8a; border-bottom-color: #bfe3ef; }
    .warning  .admonition-title { color: #a5670a; border-bottom-color: #ecd9b0; }
    .key      .admonition-title { color: #a61b1b; border-bottom-color: #efc4c9; }
    .mental   .admonition-title { color: #5b3fa0; border-bottom-color: #d5cbee; }
    .question .admonition-title { color: #6a3fb0; border-bottom-color: #d9cceb; }
    .success  .admonition-title { color: #1b7a3d; border-bottom-color: #c3e6d1; }

    #footer_content { font-size: 8pt; color: #888; text-align: center; }
</style>
"""

FOOTER = '<div id="footer_content">TicketHub — Kubernetes Cluster Architecture — page <pdf:pagenumber/> of <pdf:pagecount/></div>'


def build() -> None:
    md_files = sorted(DOCS.glob("*.md"))
    if not md_files:
        raise SystemExit(f"No markdown files found in {DOCS}")

    combined_md = "\n\n".join(f.read_text(encoding="utf-8") for f in md_files)

    html_body = markdown.markdown(
        combined_md,
        extensions=["extra", "tables", "fenced_code", "toc", "sane_lists", "admonition"],
    )

    full_html = f"<html><head>{CSS}</head><body>{html_body}{FOOTER}</body></html>"

    with open(OUTPUT, "wb") as f:
        result = pisa.CreatePDF(io.StringIO(full_html), dest=f, path=str(ROOT))

    if result.err:
        raise SystemExit(f"PDF generation failed with {result.err} error(s)")

    print(f"Built {OUTPUT} from {len(md_files)} chapter file(s):")
    for f in md_files:
        print(f"  - {f.name}")


if __name__ == "__main__":
    build()
