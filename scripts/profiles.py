#!/usr/bin/env python3
"""Effort budget profiles for scientific-deep-research.

An effort level is NOT a document count. It is a budget across four
dimensions (duration, rounds, breadth, volume). The actual number of
documents *emerges* from the budget and the topic size.

The quality bar (MIN_SCORE) is orthogonal: low effort does not mean
worse sources, only less digging.

Usage:
    python3 profiles.py            # print all profiles as JSON
    python3 profiles.py ultra      # print one profile as JSON
"""
from __future__ import annotations
import json
import sys

# Saturation: if a search round yields < this fraction of never-seen-before
# items, the topic is considered saturated and the loop should stop early.
SATURATION_THRESHOLD = 0.10

# Quality bar applied at every effort level (see search.py scoring).
MIN_SCORE = 2.0

PROFILES = {
    "low": {
        "duration_min": 2,            # guideline, not a hard cutoff
        "max_rounds": 1,
        "sources": ["arxiv", "openalex"],
        "expansion": "none",          # no citation chasing
        "volume_mb": 100,
        "results_per_query": 10,
    },
    "medium": {
        "duration_min": 10,
        "max_rounds": 2,
        "sources": ["arxiv", "openalex", "github", "huggingface"],
        "expansion": "none",
        "volume_mb": 500,
        "results_per_query": 15,
    },
    "high": {
        "duration_min": 25,
        "max_rounds": 3,
        "sources": ["arxiv", "openalex", "github", "huggingface"],
        "expansion": "citations",     # follow who cites the top papers
        "volume_mb": 2000,
        "results_per_query": 25,
    },
    "xhigh": {
        "duration_min": 45,
        "max_rounds": 5,
        "sources": ["arxiv", "openalex", "github", "huggingface"],
        "expansion": "references",    # citations + bibliographies of top papers
        "volume_mb": 5000,
        "results_per_query": 40,
    },
    "ultra": {
        "duration_min": None,         # open-ended: loop until dry
        "max_rounds": None,           # stop only when 2 consecutive rounds are dry
        "sources": ["arxiv", "openalex", "github", "huggingface"],
        "expansion": "snowball",      # full citation-graph snowball, all angles
        "volume_mb": None,            # unlimited — REQUIRES explicit user confirmation
        "results_per_query": 100,
    },
}


def get(effort: str) -> dict:
    if effort not in PROFILES:
        raise KeyError(f"unknown effort '{effort}', choose from {list(PROFILES)}")
    p = dict(PROFILES[effort])
    p["effort"] = effort
    p["saturation_threshold"] = SATURATION_THRESHOLD
    p["min_score"] = MIN_SCORE
    return p


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(get(sys.argv[1]), indent=2))
    else:
        print(json.dumps({k: get(k) for k in PROFILES}, indent=2))
