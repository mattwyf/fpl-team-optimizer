"""Build criterion_c_development.pdf from the markdown source.

Pipeline: markdown -> styled HTML (docs/criterion_c_development.html)
          -> headless Chrome --print-to-pdf.
Run:  .venv/bin/python docs/build_pdf.py
"""

import re
from pathlib import Path

import markdown

DOCS = Path(__file__).parent
SRC = DOCS / "criterion_c_development.md"
OUT_HTML = DOCS / "criterion_c_development.html"

CSS = """
@page { size: A4; margin: 22mm 18mm; }
* { box-sizing: border-box; }
body {
    font-family: "Times New Roman", Georgia, serif;
    font-size: 11.5pt;
    line-height: 1.5;
    color: #1a1a1a;
    max-width: 100%;
    margin: 0;
}
h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 15pt; margin-top: 1.6em; border-bottom: 1px solid #999; padding-bottom: 3px; }
h3 { font-size: 12.5pt; margin-top: 1.4em; }
h1, h2, h3 { font-family: Helvetica, Arial, sans-serif; page-break-after: avoid; }
p, li { text-align: justify; }
code {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 9.5pt;
    background: #f2f2f2;
    padding: 1px 3px;
    border-radius: 3px;
}
pre {
    background: #f7f7f7;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px 12px;
    overflow-x: hidden;
    white-space: pre-wrap;
    word-wrap: break-word;
    page-break-inside: avoid;
    line-height: 1.35;
}
pre code { background: none; padding: 0; font-size: 8.8pt; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; margin: 0.8em 0; }
th, td { border: 1px solid #bbb; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #ececec; font-family: Helvetica, Arial, sans-serif; }
tr { page-break-inside: avoid; }
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 12px auto;
    page-break-inside: avoid;
    border: 1px solid #e0e0e0;
    padding: 6px;
    background: #fff;
}
/* Tall flowcharts: cap height so heading + caption + image share one page */
img[src*="fig3"], img[src*="fig4"], img[src*="fig5"], img[src*="fig6"] {
    max-height: 195mm;
    width: auto;
    max-width: 92%;
}
blockquote {
    border-left: 4px solid #888;
    margin: 1em 0;
    padding: 6px 14px;
    background: #f6f6f6;
    color: #333;
}
hr { border: none; border-top: 1px solid #bbb; margin: 1.6em 0; }
strong { font-weight: 700; }
.codehilite .k, .codehilite .kn, .codehilite .ow { color: #00699e; font-weight: 600; }
.codehilite .s, .codehilite .s1, .codehilite .s2, .codehilite .sd { color: #986801; }
.codehilite .c, .codehilite .c1, .codehilite .cm { color: #7a7a7a; font-style: italic; }
.codehilite .mi, .codehilite .mf { color: #9d3fd3; }
"""

MATHJAX = """
<script>
window.MathJax = {
  tex: { inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']] },
  svg: { fontCache: 'global' }
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
"""


def main() -> None:
    md_text = SRC.read_text(encoding="utf-8")

    # Shield LaTeX from the markdown parser (it strips the \[ \( escapes),
    # then restore verbatim into the HTML for MathJax to typeset.
    math_chunks: list[str] = []

    def shield(match: re.Match) -> str:
        math_chunks.append(match.group(0))
        return f"MATHCHUNK{len(math_chunks) - 1}ENDMATH"

    md_text = re.sub(r"\\\[.*?\\\]|\\\(.*?\\\)", shield, md_text, flags=re.S)

    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False, "noclasses": False}},
    )

    for i, chunk in enumerate(math_chunks):
        body = body.replace(f"MATHCHUNK{i}ENDMATH", chunk)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Criterion C — Development — FPL Team Optimizer</title>
<style>{CSS}</style>
{MATHJAX}
</head>
<body>
{body}
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")


if __name__ == "__main__":
    main()
