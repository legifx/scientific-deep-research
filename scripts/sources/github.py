"""GitHub adapter — repository search. Keyless (10 req/min) or via GITHUB_TOKEN."""
from __future__ import annotations
import os

from . import common

API = "https://api.github.com/search/repositories"


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def search(query: str, max_results: int = 15, since: str | None = None) -> list[dict]:
    q = query
    if since:
        q += f" pushed:>={since if len(since) > 4 else since + '-01-01'}"
    url = f"{API}?" + common.qs({
        "q": q, "sort": "stars", "order": "desc",
        "per_page": min(max_results, 50),
    })
    try:
        data = common.get_json(url, headers=_headers())
    except Exception as e:
        common.warn(f"github search failed ({e}); skipping source")
        return []
    items = []
    for r in data.get("items", []):
        items.append({
            "id": f"github:{r['full_name']}",
            "source": "github",
            "type": "repo",
            "title": r["full_name"],
            "authors": [r["owner"]["login"]],
            "date": (r.get("pushed_at") or "")[:10],
            "year": int(r["created_at"][:4]) if r.get("created_at") else None,
            "abstract": r.get("description") or "",
            "url": r["html_url"],
            "clone_url": r["clone_url"],
            "pdf_url": None,
            "doi": None,
            "venue": "GitHub",
            "citations": r.get("stargazers_count", 0),  # stars stand in for citations
            "size_kb": r.get("size", 0),
        })
    return items
