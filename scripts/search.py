#!/usr/bin/env python3
"""Meta-search across scholarly sources with transparent scoring,
dedupe and saturation measurement. The agent orchestrates rounds;
this script executes ONE round deterministically.

Usage:
  python3 search.py -q "kv cache compression" -q "attention architectures" \
      --effort medium --since 2024 --seen .sdr/seen.json --out round1.json

  # expansion (high/xhigh/ultra): follow the citation graph
  python3 search.py --cited-by W4390000000 --references W4390000000 \
      --effort high --out round2.json

Output JSON: {items: [...], novelty_rate, total_found, new_found, saturated}
Items are sorted by score (desc) and filtered to score >= min_score.
Already-seen items are excluded from `items` but counted for novelty.
The --seen file is updated in place (created if missing).
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import profiles  # noqa: E402
from sources import arxiv, github, huggingface, openalex, common  # noqa: E402

SOURCES = {
    "arxiv": arxiv.search,
    "openalex": openalex.search,
    "github": github.search,
    "huggingface": huggingface.search,
}

# Top-tier ML/AI venues get a reliability bonus. Community-tunable.
TOP_VENUES = re.compile(
    r"neurips|icml|iclr|acl\b|emnlp|cvpr|iccv|eccv|aaai|nature|science\b|jmlr|tmlr",
    re.IGNORECASE,
)


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:80]


def dedupe_key(item: dict) -> str:
    if item.get("doi"):
        return f"doi:{item['doi']}"
    if item["id"].startswith("arxiv:"):
        return item["id"]
    nt = norm_title(item.get("title", ""))
    return f"title:{nt}" if nt else item["id"]


def score(item: dict, this_year: int) -> float:
    """Transparent seriousness/relevance score. Tune via PR, not prompt."""
    s = 0.0
    cit = item.get("citations")
    if cit is not None:
        # log-scale impact; stars/likes use the same scale (they are noisier
        # but comparable in spirit)
        s += 2.0 * math.log10(1 + cit)
    year = item.get("year")
    if year:
        age = max(0, this_year - year)
        s += max(0.0, 3.0 - age)  # freshness bonus, fades over 3 years
    if TOP_VENUES.search(item.get("venue") or ""):
        s += 2.0
    if item.get("pdf_url") or item.get("clone_url"):
        s += 1.0  # actually fetchable
    if item["source"] in ("arxiv", "openalex"):
        s += 1.0  # peer-adjacent scholarly source
    # "small lab with potential": recent + low citations but already noticed
    if year and this_year - year <= 1 and cit is not None and 5 <= cit <= 100:
        s += 1.5
    return round(s, 2)


def merge(a: dict, b: dict) -> dict:
    """Merge duplicate records; prefer filled fields, keep max citations."""
    out = dict(a)
    for k, v in b.items():
        if not out.get(k) and v:
            out[k] = v
    if (b.get("citations") or 0) > (out.get("citations") or 0):
        out["citations"] = b["citations"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--query", action="append", default=[],
                    help="sub-query; repeatable")
    ap.add_argument("--cited-by", action="append", default=[],
                    help="OpenAlex work ID — find works citing it (expansion)")
    ap.add_argument("--references", action="append", default=[],
                    help="OpenAlex work ID — fetch its bibliography (expansion)")
    ap.add_argument("--effort", default="medium", choices=list(profiles.PROFILES))
    ap.add_argument("--since", default=None, help="YYYY or YYYY-MM-DD time filter")
    ap.add_argument("--sources", default=None,
                    help="comma list; default = effort profile's sources")
    ap.add_argument("--seen", default=None,
                    help="JSON file of already-seen keys; updated in place")
    ap.add_argument("--out", default=None, help="write result JSON here (default stdout)")
    args = ap.parse_args()

    prof = profiles.get(args.effort)
    per_query = prof["results_per_query"]
    active = (args.sources.split(",") if args.sources else prof["sources"])

    seen: set[str] = set()
    seen_path = Path(args.seen) if args.seen else None
    if seen_path and seen_path.exists():
        seen = set(json.loads(seen_path.read_text()))

    found: dict[str, dict] = {}

    def add(item: dict, query: str):
        item["query"] = item.get("query") or query
        key = dedupe_key(item)
        item["dedupe_key"] = key
        found[key] = merge(found[key], item) if key in found else item

    for q in args.query:
        for src in active:
            try:
                for item in SOURCES[src](q, per_query, args.since):
                    add(item, q)
                common.warn(f"round: '{q}' via {src}: ok")
            except Exception as e:
                common.warn(f"'{q}' via {src} FAILED: {e}")

    for wid in args.cited_by:
        for item in openalex.cited_by(wid, per_query):
            add(item, f"cited-by:{wid}")
    for wid in args.references:
        for item in openalex.references(wid, per_query):
            add(item, f"references:{wid}")

    this_year = date.today().year
    for item in found.values():
        item["score"] = score(item, this_year)

    total = len(found)
    fresh = {k: v for k, v in found.items() if k not in seen}
    novelty = (len(fresh) / total) if total else 0.0

    items = sorted(
        (v for v in fresh.values() if v["score"] >= prof["min_score"]),
        key=lambda x: -x["score"],
    )

    if seen_path:
        seen |= set(found.keys())
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(sorted(seen)))

    result = {
        "effort": args.effort,
        "queries": args.query,
        "total_found": total,
        "new_found": len(fresh),
        "novelty_rate": round(novelty, 3),
        "saturated": total > 0 and novelty < prof["saturation_threshold"],
        "items": items,
    }
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(out)
        common.warn(
            f"{len(items)} new items (of {total} found, novelty {novelty:.0%}) -> {args.out}"
        )
    else:
        print(out)


if __name__ == "__main__":
    main()
