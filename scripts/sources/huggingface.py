"""Hugging Face adapter — models, datasets and daily papers. Keyless."""
from __future__ import annotations
from . import common

BASE = "https://huggingface.co/api"


def _hub(kind: str, query: str, max_results: int, since: str | None) -> list[dict]:
    url = f"{BASE}/{kind}?" + common.qs({
        "search": query, "limit": min(max_results, 50),
        "sort": "likes", "direction": -1,
    })
    try:
        data = common.get_json(url)
    except Exception as e:
        common.warn(f"huggingface {kind} search failed ({e}); skipping")
        return []
    since_key = (since or "")[:10]
    items = []
    for m in data:
        mid = m.get("id") or m.get("modelId")
        created = (m.get("createdAt") or "")[:10]
        if since_key and created and created < since_key:
            continue
        items.append({
            "id": f"hf:{kind}:{mid}",
            "source": "huggingface",
            "type": "model" if kind == "models" else "dataset",
            "title": mid,
            "authors": [mid.split("/")[0]] if "/" in mid else [],
            "date": created,
            "year": int(created[:4]) if created[:4].isdigit() else None,
            "abstract": ", ".join(m.get("tags", [])[:10]),
            "url": f"https://huggingface.co/{'datasets/' if kind == 'datasets' else ''}{mid}",
            "pdf_url": None,
            "doi": None,
            "venue": "HuggingFace",
            "citations": m.get("likes", 0),  # likes stand in for citations
            "downloads": m.get("downloads"),
        })
    return items


def search(query: str, max_results: int = 15, since: str | None = None) -> list[dict]:
    half = max(max_results // 2, 5)
    return _hub("models", query, half, since) + _hub("datasets", query, half, since)
