"""Deterministic paper-text extraction for light mode. Stdlib only.

Light mode stores papers as Markdown/plain text instead of PDFs
(10–50x smaller, faster for agents to read). The text is extracted
verbatim by code — NEVER retyped or summarized by the LLM — so the
anti-hallucination guarantee holds.

Extraction chain (first that yields substantial text wins):
  1. arXiv HTML rendering (arxiv.org/html, fallback ar5iv) -> Markdown
  2. pdftotext (poppler-utils), if installed -> plain text
  3. metadata + abstract only (marked as such)
"""
from __future__ import annotations
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from . import common

_SKIP = {"script", "style", "svg", "nav", "button", "select", "option"}
_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####",
             "h5": "#####", "h6": "######"}
_BLOCK = {"p", "div", "section", "article", "li", "tr", "figure",
          "figcaption", "blockquote", "pre", "table", "ul", "ol", "br"}


class _HTML2MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0
        self._math_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "math":
            self._math_depth += 1
            self.out.append(" [formula] ")
        elif tag in _HEADINGS:
            self.out.append(f"\n\n{_HEADINGS[tag]} ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "math" and self._math_depth:
            self._math_depth -= 1
        elif tag in _HEADINGS or tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip_depth and not self._math_depth:
            self.out.append(data)


def html_to_markdown(html: str) -> str:
    p = _HTML2MD()
    p.feed(html)
    text = "".join(p.out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def from_arxiv_html(arxiv_id: str) -> str | None:
    for url in (f"https://arxiv.org/html/{arxiv_id}",
                f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"):
        try:
            raw = common.http_get(url, timeout=60).decode("utf-8", "replace")
        except Exception:
            continue
        text = html_to_markdown(raw)
        if len(text) > 3000:  # substantial body, not an error page
            return text
    return None


def from_pdf_url(pdf_url: str) -> str | None:
    if not shutil.which("pdftotext"):
        return None
    try:
        data = common.http_get(pdf_url, timeout=60)
    except Exception:
        return None
    if not data.startswith(b"%PDF"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        r = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(tmp_path), "-"],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            return None
        text = r.stdout.decode("utf-8", "replace").strip()
        return text if len(text) > 1000 else None
    except Exception:
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


# C12: a PDF is marked unverified when this share of the title's tokens is
# missing from its first two pages (Jev: below 0.70, conf. 0.73).
VERIFY_THRESHOLD = 0.70


def verify_pdf_against_title(data: bytes, title: str):
    """C12: does this PDF belong to the record it is filed under?

    One-sided token coverage — the share of the title's tokens that appear
    in the first two pages. Coverage rather than Jaccard, because a short
    title against two pages of body text is hopelessly length-asymmetric:
    a perfect match would score about 0.01 Jaccard (Jev: 0.90, conf. 0.87).

    Returns a float, or None when it cannot be checked, which is never
    treated as a failure.
    """
    if not shutil.which("pdftotext") or not data.startswith(b"%PDF"):
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            r = subprocess.run(
                ["pdftotext", "-f", "1", "-l", "2", "-enc", "UTF-8",
                 str(tmp_path), "-"],
                capture_output=True, timeout=120,
            )
            if r.returncode != 0:
                return None
            text = r.stdout.decode("utf-8", "replace")
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception:
        return None
    if len(text.strip()) < 200:
        return None
    want = common.tokens(title)
    if not want:
        return None
    have = common.tokens(text)
    return round(len(want & have) / len(want), 4)


def extract(item: dict) -> tuple[str, str]:
    """Return (text, method). Always succeeds — worst case abstract-only."""
    if item["id"].startswith("arxiv:"):
        text = from_arxiv_html(item["id"].split(":", 1)[1])
        if text:
            return text, "arxiv-html"
    if item.get("pdf_url"):
        text = from_pdf_url(item["pdf_url"])
        if text:
            return text, "pdftotext"
    return (item.get("abstract") or "(no abstract available)",
            "abstract-only")


def to_markdown_doc(item: dict, text: str, method: str) -> str:
    authors = ", ".join(item.get("authors") or [])
    note = ("full text could not be extracted — abstract only; "
            "fetch the PDF via the source link for the complete paper"
            if method == "abstract-only" else
            "verbatim automated extraction; formulas/figures may be "
            "degraded — the source link has the authoritative version")
    return "\n".join([
        "---",
        f"title: \"{(item.get('title') or '').replace(chr(34), chr(39))}\"",
        f"authors: \"{authors.replace(chr(34), chr(39))}\"",
        f"year: {item.get('year') or 'unknown'}",
        f"venue: \"{item.get('venue') or ''}\"",
        f"source: {item.get('url')}",
        f"doi: {item.get('doi') or ''}",
        f"extraction: {method}",
        f"note: {note}",
        "---",
        "",
        text,
        "",
    ])
