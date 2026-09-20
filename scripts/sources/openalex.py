"""OpenAlex adapter — 250M+ scholarly works, no key required.

Docs: https://docs.openalex.org
Provides citation counts, venues, open-access PDF links and the
citation graph (used for expansion / snowballing).
"""
from __future__ import annotations
import re

from . import common

API = "https://api.openalex.org/works"


def _reconstruct_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    positions = {}
    for word, idxs in inv.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))[:2000]


def _to_item(w: dict) -> dict:
    doi = (w.get("doi") or "").replace("https://doi.org/", "").lower() or None
    best_oa = w.get("best_oa_location") or {}
    primary = w.get("primary_location") or {}
    venue = ((primary.get("source") or {}).get("display_name")) or ""
    pdf_url = best_oa.get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
    arxiv_m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", pdf_url or "")
    return {
        "id": f"arxiv:{arxiv_m.group(1)}" if arxiv_m else w["id"].replace("https://openalex.org/", "openalex:"),
        "openalex_id": w["id"].replace("https://openalex.org/", ""),
        "source": "openalex",
        "type": "paper",
        "title": w.get("display_name") or "",
        "authors": [a["author"]["display_name"]
                    for a in (w.get("authorships") or [])[:12]],
        "date": w.get("publication_date"),
        "year": w.get("publication_year"),
        "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
        "url": w.get("doi") or w["id"],
        "pdf_url": pdf_url,
        "doi": doi,
        "venue": venue,
        "citations": w.get("cited_by_count", 0),
    }


_FIELDS = ("id,doi,display_name,authorships,publication_year,publication_date,"
           "cited_by_count,primary_location,best_oa_location,open_access,"
           "abstract_inverted_index")


def search(query: str, max_results: int = 15, since: str | None = None) -> list[dict]:
    filters = ["type:article|preprint"]
    if since:
        d = since if len(since) > 4 else f"{since}-01-01"
        filters.append(f"from_publication_date:{d}")
    url = f"{API}?" + common.qs({
        "search": query,
        "per-page": min(max_results, 100),
        "filter": ",".join(filters),
        "select": _FIELDS,
    })
    data = common.get_json(url)
    return [_to_item(w) for w in data.get("results", [])]


def _date_filter(since: str | None) -> str | None:
    if not since:
        return None
    return f"from_publication_date:{since if len(since) > 4 else since + '-01-01'}"


def cited_by(openalex_id: str, max_results: int = 25, since: str | None = None) -> list[dict]:
    """Works that cite the given work — 'who built on this?' (expansion).

    OpenAlex filter names run against intuition: `cites:X` returns works that
    cite X (newer works); `cited_by:X` returns the works X cites (its
    bibliography). Verified against the live API.
    """
    filters = [f"cites:{openalex_id}"]
    d = _date_filter(since)
    if d:
        filters.append(d)
    url = f"{API}?" + common.qs({
        "filter": ",".join(filters),
        "per-page": min(max_results, 100),
        "sort": "cited_by_count:desc",
        "select": _FIELDS,
    })
    return [_to_item(w) for w in common.get_json(url).get("results", [])]


def references(openalex_id: str, max_results: int = 25, since: str | None = None) -> list[dict]:
    """Works the given work cites — its bibliography (xhigh/ultra expansion)."""
    filters = [f"cited_by:{openalex_id}"]
    d = _date_filter(since)
    if d:
        filters.append(d)
    url = f"{API}?" + common.qs({
        "filter": ",".join(filters),
        "per-page": min(max_results, 100),
        "sort": "cited_by_count:desc",
        "select": _FIELDS,
    })
    return [_to_item(w) for w in common.get_json(url).get("results", [])]
