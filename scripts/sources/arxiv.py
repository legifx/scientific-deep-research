"""arXiv adapter — official Atom API, no key required.

Docs: https://info.arxiv.org/help/api/user-manual.html
Rate limit etiquette: 1 request / 3 seconds.
"""
from __future__ import annotations
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from . import common

API = "http://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_last_call = [0.0]


def _polite():
    wait = 3.0 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def arxiv_id_from_url(url: str) -> str | None:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", url or "")
    return m.group(1) if m else None


def search(query: str, max_results: int = 15, since: str | None = None) -> list[dict]:
    """since: 'YYYY' or 'YYYY-MM-DD' — filtered client-side (API has no date filter)."""
    _polite()
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        # over-fetch when filtering by date so the cutoff doesn't starve results
        "max_results": max_results * 3 if since else max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    raw = common.http_get(f"{API}?{urllib.parse.urlencode(params)}")
    root = ET.fromstring(raw)
    since_key = (since or "")[:10]
    items = []
    for entry in root.findall("atom:entry", NS):
        published = (entry.findtext("atom:published", "", NS) or "")[:10]
        if since_key and published < since_key:
            continue
        abs_url = entry.findtext("atom:id", "", NS)
        aid = arxiv_id_from_url(abs_url) or abs_url
        pdf_url = next(
            (l.get("href") for l in entry.findall("atom:link", NS)
             if l.get("title") == "pdf"),
            f"https://arxiv.org/pdf/{aid}",
        )
        doi = entry.findtext("arxiv:doi", None, NS)
        items.append({
            "id": f"arxiv:{aid}",
            "source": "arxiv",
            "type": "paper",
            "title": " ".join((entry.findtext("atom:title", "", NS) or "").split()),
            "authors": [a.findtext("atom:name", "", NS)
                        for a in entry.findall("atom:author", NS)][:12],
            "date": published,
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "abstract": " ".join((entry.findtext("atom:summary", "", NS) or "").split()),
            "url": abs_url,
            "pdf_url": pdf_url,
            "doi": doi.lower() if doi else None,
            "venue": "arXiv",
            "citations": None,  # arXiv doesn't expose citation counts; OpenAlex fills this via dedupe-merge
        })
        if len(items) >= max_results:
            break
    return items
