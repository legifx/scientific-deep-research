#!/usr/bin/env python3
"""Meta-search across scholarly sources with transparent scoring,
dedupe, relevance measurement and saturation detection. The agent
orchestrates rounds; this script executes ONE round deterministically.

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

Relevance (C01): every item carries a `relevance` value — the IDF-weighted
share of query content terms found in its title (double weight) or abstract.
Items from a text query with no content term at all are dropped (lenient
floor). Expansion results (--cited-by/--references) are measured for ranking
but are never dropped by the floor, because a cited work need not repeat the
query wording.
Conflicts (C02): when two sources disagree about one work, the merge is
flagged with both variants instead of resolving silently.
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

# --------------------------------------------------------------- C01 -----
# Function words carry no topical meaning, so they are never content terms.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "do", "does", "for", "from", "how", "in", "into", "is", "it", "its",
    "of", "on", "or", "over", "that", "the", "their", "them", "then",
    "there", "these", "this", "to", "under", "use", "used", "using", "via",
    "was", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "within",
    "der", "die", "das", "und", "oder", "fur", "mit", "von", "zu", "im",
    "den", "dem", "des", "ein", "eine", "auf", "eine",
}

# Score mix. Calibrate against the fixtures in tests/, not by guessing.
WEIGHTS = {"relevance": 0.45, "impact": 0.30, "freshness": 0.15, "bonus": 0.10}
# Used when relevance cannot be measured at all: neither rewards nor penalises.
NEUTRAL_RELEVANCE = 0.5

# --------------------------------------------------------------- C02 -----
# Below this token-Jaccard similarity two abstracts count as a conflict.
# Deliberately high: a legitimate pair (publisher abstract vs arXiv abstract
# of the same paper) shares most words and stays comfortably above it.
CONFLICT_THRESHOLD = 0.50
# Lower number wins when sources disagree about a field.
AUTHORITY = {"arxiv": 0, "openalex": 1, "github": 2, "huggingface": 2}


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:80]


# --------------------------------------------------------------- C07 -----
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.([0-9]{4}\.[0-9]{4,5})$")
# Extensible table of equivalent DOI spellings mapping onto one key.
DOI_ALIASES: dict = {}


def dedupe_key(item: dict) -> str:
    """Collapse equivalent records onto a single key.

    Order (Jev, 0.97 conf): DOI alias -> arXiv id -> OpenAlex id ->
    repo name without owner -> normalised title + year.
    """
    doi = (item.get("doi") or "").strip().lower().replace("https://doi.org/", "")
    if doi:
        m = _ARXIV_DOI.match(doi)
        if m:
            return "arxiv:" + m.group(1)
        return "doi:" + DOI_ALIASES.get(doi, doi)
    if item["id"].startswith("arxiv:"):
        return item["id"]
    oa = (item.get("openalex_id") or "").replace("https://openalex.org/", "")
    if oa:
        return "openalex:" + oa
    if item.get("clone_url"):
        # "Alpha-Park/x" and "alphaparkinc/x" are the same project
        name = item["title"].split("/")[-1].lower()
        return "repo:" + re.sub(r"[^a-z0-9]", "", name)
    nt = norm_title(item.get("title", ""))
    return f"title:{nt}:{item.get('year') or ''}" if nt else item["id"]


def content_terms(query: str) -> list:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-]{1,}", (query or "").lower())
            if t not in STOPWORDS]


def _haystack(item: dict) -> str:
    return ((item.get("title") or "") + " " + (item.get("abstract") or "")).lower()


def build_idf(items: list, terms: list) -> dict:
    """Inverse document frequency over this round's result set.

    A term that appears in nearly every result (e.g. "attention" for a broad
    topic) gets a weight near zero and can no longer carry an off-topic paper
    into the top ranks.
    """
    n = len(items)
    idf = {}
    for t in terms:
        df = sum(1 for it in items if t in _haystack(it))
        idf[t] = max(0.0, math.log((n + 1) / (df + 1)))
    return idf


def relevance_of(item: dict, terms: list, idf: dict):
    """IDF-weighted share of content terms present. None if unmeasurable."""
    if not terms:
        return None
    total = sum(idf.get(t, 0.0) for t in terms)
    if total <= 0:
        return None
    title = (item.get("title") or "").lower()
    abstract = (item.get("abstract") or "").lower()
    got = 0.0
    for t in terms:
        w = idf.get(t, 0.0)
        if t in title:
            got += w * 2.0      # a title hit counts double
        elif t in abstract:
            got += w * 1.0
    # Normalised against the all-terms-in-title maximum, so the result is
    # always within 0..1.
    return round(got / (2.0 * total), 4)


def score(item: dict, this_year: int, relevance=None) -> float:
    """Transparent seriousness score. Tune via PR, not prompt."""
    rel = NEUTRAL_RELEVANCE if relevance is None else relevance
    cit = item.get("citations")
    impact = 2.0 * math.log10(1 + cit) if cit is not None else 0.0
    year = item.get("year")
    freshness = max(0.0, 3.0 - max(0, this_year - year)) if year else 0.0
    bonus = 0.0
    if TOP_VENUES.search(item.get("venue") or ""):
        bonus += 2.0
    if item.get("pdf_url") or item.get("clone_url"):
        bonus += 1.0            # actually fetchable
    if item["source"] in ("arxiv", "openalex"):
        bonus += 1.0            # peer-adjacent scholarly source
    if year and this_year - year <= 1 and cit is not None and 5 <= cit <= 100:
        bonus += 1.5            # "small lab with potential"
    return round(
        WEIGHTS["relevance"] * rel * 10.0
        + WEIGHTS["impact"] * impact
        + WEIGHTS["freshness"] * freshness
        + WEIGHTS["bonus"] * bonus,
        2,
    )


def legacy_score(item: dict, this_year: int) -> float:
    """The pre-C01 score, kept so new runs can be compared against old ones."""
    s = 0.0
    cit = item.get("citations")
    if cit is not None:
        s += 2.0 * math.log10(1 + cit)
    year = item.get("year")
    if year:
        s += max(0.0, 3.0 - max(0, this_year - year))
    if TOP_VENUES.search(item.get("venue") or ""):
        s += 2.0
    if item.get("pdf_url") or item.get("clone_url"):
        s += 1.0
    if item["source"] in ("arxiv", "openalex"):
        s += 1.0
    if year and this_year - year <= 1 and cit is not None and 5 <= cit <= 100:
        s += 1.5
    return round(s, 2)


def _authority(item: dict) -> int:
    return AUTHORITY.get(item.get("source"), 9)


def merge(a: dict, b: dict):
    """Merge duplicate records; prefer filled fields, keep max citations.

    Returns None when the records are probably NOT the same work (their
    titles diverge below CONFLICT_THRESHOLD). The caller then keeps them
    apart instead of mixing their fields (C02).
    """
    jt = common.jaccard(a.get("title") or "", b.get("title") or "")
    if jt is not None and jt < CONFLICT_THRESHOLD:
        return None

    keep = a if _authority(a) <= _authority(b) else b
    other = b if keep is a else a
    out = dict(keep)
    for k, v in other.items():
        if not out.get(k) and v:
            out[k] = v
    if (other.get("citations") or 0) > (out.get("citations") or 0):
        out["citations"] = other["citations"]

    ja = common.jaccard(keep.get("abstract") or "", other.get("abstract") or "")
    if ja is not None and ja < CONFLICT_THRESHOLD:
        out["conflict"] = True
        out["conflict_fields"] = ["abstract"]
        out["conflict_detail"] = {
            "abstract": {
                "similarity": round(ja, 4),
                "used": {"source": keep.get("source"),
                         "value": (keep.get("abstract") or "")[:2000]},
                "rejected": {"source": other.get("source"),
                             "value": (other.get("abstract") or "")[:2000]},
            }
        }
    return out


def _suggest(queries: list) -> list:
    """Narrower query candidates for the abort message."""
    out = []
    for q in queries:
        words = [w for w in re.findall(r"[A-Za-z0-9\-]{3,}", q)
                 if w.lower() not in STOPWORDS]
        if len(words) > 2:
            out.append(" ".join(words[:2]))
        out.extend(words)
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq[:8]


def _write_result(out_path, text):
    """Write the round JSON, creating its directory if needed."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _write_report(out_path, result, total, new_found):
    sdr_dir = Path(out_path).parent
    diag = result.get("diagnostics") or {}
    common.update_report(
        sdr_dir,
        candidates=total,
        new_found=new_found,
        relevant=len(result["items"]),
        offtopic_dropped=diag.get("offtopic_dropped", result.get("offtopic_dropped", 0)),
        conflicts=diag.get("conflicts", 0),
        aborted=bool(result.get("aborted")),
        last_novelty=result.get("novelty_rate", 0.0),
        last_saturated=bool(result.get("saturated")),
    )


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

    seen: set = set()
    seen_path = Path(args.seen) if args.seen else None
    if seen_path and seen_path.exists():
        seen = set(json.loads(seen_path.read_text()))

    found: dict = {}

    def add(item: dict, query: str):
        item["query"] = item.get("query") or query
        key = dedupe_key(item)
        item["dedupe_key"] = key
        if key not in found:
            found[key] = item
            return
        merged = merge(found[key], item)
        if merged is None:
            # Same key, but the titles disagree: a different work. Keep both.
            alt = key + "#" + (item.get("openalex_id") or item["id"])
            item["dedupe_key"] = alt
            found[alt] = item
        else:
            merged["dedupe_key"] = key
            found[key] = merged

    for q in args.query:
        for src in active:
            try:
                for item in SOURCES[src](q, per_query, args.since):
                    add(item, q)
                common.warn(f"round: '{q}' via {src}: ok")
            except Exception as e:
                common.warn(f"'{q}' via {src} FAILED: {e}")

    for wid in args.cited_by:
        for item in openalex.cited_by(wid, per_query, args.since):
            add(item, f"cited-by:{wid}")
    for wid in args.references:
        for item in openalex.references(wid, per_query, args.since):
            add(item, f"references:{wid}")

    this_year = date.today().year

    # ---- C01: relevance --------------------------------------------------
    terms_by_query = {q: content_terms(q) for q in args.query}
    round_terms = sorted({t for ts in terms_by_query.values() for t in ts})
    idf = build_idf(list(found.values()), round_terms)

    for item in found.values():
        own = terms_by_query.get(item.get("query") or "")
        if own:
            rel = relevance_of(item, own, idf)
        elif round_terms:
            # expansion result: measured against the round's terms
            rel = relevance_of(item, round_terms, idf)
        else:
            rel = None
        item["relevance"] = rel
        if rel is not None and rel <= 0.0:
            item["_offtopic"] = True
        item["legacy_score"] = legacy_score(item, this_year)
        item["score"] = score(item, this_year, rel)

    total = len(found)
    fresh = {k: v for k, v in found.items() if k not in seen}

    # ---- C09: refuse to build a library with nothing relevant ------------
    passing = [v for v in fresh.values()
               if not v.get("_offtopic") and v["score"] >= prof["min_score"]]
    offtopic = sum(1 for v in fresh.values() if v.get("_offtopic"))
    conflicts = sum(1 for v in found.values() if v.get("conflict"))

    if fresh and not passing:
        result = {
            "aborted": True,
            "reason": "no_relevant_results",
            "effort": args.effort,
            "queries": args.query,
            "total_found": total,
            "new_found": len(fresh),
            "offtopic_dropped": offtopic,
            "novelty_rate": 0.0,
            "saturated": True,
            "items": [],
            "message": ("Kein Treffer enthaelt einen Inhaltsterm der Query. "
                        "Ursache meist: zu breite oder falsche Formulierung "
                        "fuer dieses Feld."),
            "query_suggestions": _suggest(args.query),
        }
        if seen_path:
            seen |= set(found.keys())
            seen_path.parent.mkdir(parents=True, exist_ok=True)
            seen_path.write_text(json.dumps(sorted(seen)))
        out = json.dumps(result, indent=2, ensure_ascii=False)
        if args.out:
            _write_result(args.out, out)
            _write_report(args.out, result, total, len(fresh))
            common.warn("no relevant results — aborted (see query_suggestions)")
        else:
            print(out)
        return

    # Novelty counts only what survives both filters.
    novelty = (len(passing) / total) if total else 0.0
    items = sorted(passing, key=lambda x: -x["score"])

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
        "aborted": False,
        "items": items,
        "diagnostics": {
            "offtopic_dropped": offtopic,
            "conflicts": conflicts,
            "content_terms": round_terms,
        },
    }
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        _write_result(args.out, out)
        _write_report(args.out, result, total, len(fresh))
        common.warn(f"{len(items)} new items (of {total} found, novelty {novelty:.0%})"
                    f" — {offtopic} off-topic verworfen, {conflicts} Konflikte -> {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
