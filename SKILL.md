---
name: scientific-deep-research
description: >
  Scientific Deep Research — build a local, citable library of real papers,
  repos and models on any topic, so downstream agents work from ground truth
  instead of hallucinating sources. Trigger on /sdr <topic>, or when the user
  asks for a deep research with downloaded papers/PDFs, a local research
  dataset, "scientific deep research", or wants to collect arXiv/GitHub/
  HuggingFace sources into a folder before starting a project.
---

# Scientific Deep Research (`/sdr`)

Turn a topic into a **local research folder**: real PDFs, shallow-cloned
repos and an `INDEX.md` + `manifest.json` that downstream agents must treat
as ground truth. Never invent a source — everything comes from live API
results produced by the scripts in `scripts/`.

**Golden rule:** you (the agent) curate and orchestrate; the scripts search
and download. Do not write paper titles, authors or links from memory —
only relay what `search.py` returned.

All scripts are stdlib-only Python 3.8+. Run them from this skill's
directory (`SKILL_DIR` below means the folder containing this file).

## Phase 0 — Intake (ONE question round)

Parse the user's request: topic, and optionally `--effort <level>`,
`--since <YYYY>`, a target folder. Ask ONE bundled question round
(use AskUserQuestion if available, otherwise plain text) for whatever
is still missing:

1. **Target folder** — default `./research/<topic-slug>/`
2. **Effort** — budget profile, not a document count (see table below);
   default `medium`
3. **Time filter** — all time / last 2 years / custom `--since`
4. **Source types** — papers / repos / models+datasets (multi-select,
   default: all)
5. **Storage mode** — `full` (original PDFs + repo clones, default) or
   `light` (extracted text as Markdown + repo READMEs only; 10–50x
   smaller, faster for agent brains). If the user says "light", mentions
   disk space, or wants MD/TXT for an agent brain, pick light without
   asking.

| Effort | Duration guide | Rounds | Expansion | Volume guide |
|---|---|---|---|---|
| low | ~2 min | 1 | none | ~100 MB |
| medium | ~10 min | up to 2 | none | ~500 MB |
| high | ~25 min | up to 3 | citations of top papers | ~2 GB |
| xhigh | ~45 min | up to 5 | + bibliographies (references) | ~5 GB |
| ultra | open-ended | until dry | full citation snowball, all angles | unlimited |

These are guidelines, not hard cutoffs: decide at ROUND boundaries whether
the budget justifies another round. The only hard limit is the volume cap
passed to `fetch.py`. The quality bar is identical at every level — low
effort means less digging, never worse sources.

**Ultra requires explicit confirmation:** warn that it can take a long
time and many GB ("ultra läuft ohne Limits — kann 30+ Minuten und mehrere
GB bedeuten, ok?"). If the user declines, fall back to xhigh with a cap.

Read the exact numeric budgets with:
```bash
python3 SKILL_DIR/scripts/profiles.py <effort>
```

## Phase 1 — Search plan

Decompose the topic into 5–10 sub-queries covering distinct angles
(concepts, architectures/methods, benchmarks/evaluation, surveys, tooling).
Show the plan briefly, then proceed — do not wait for approval.

## Phase 2 — Search rounds

Each round is ONE deterministic call (the `--seen` file makes rounds
cumulative and measures novelty):

```bash
python3 SKILL_DIR/scripts/search.py \
  -q "sub-query 1" -q "sub-query 2" ... \
  --effort <effort> [--since YYYY] [--sources arxiv,openalex,github,huggingface] \
  --seen <dest>/.sdr/seen.json --out <dest>/.sdr/round<N>.json
```

The result reports `novelty_rate` and `saturated`. Loop logic:

- **Round 2+ queries** come from what round 1 found: recurring terms in
  abstracts, named methods, follow-up ideas. For high+: add
  `--cited-by <OPENALEX_ID>` for the 3–5 top-scored papers; for xhigh+ also
  `--references <OPENALEX_ID>` (their bibliographies).
- **Stop early** when `saturated: true` (novelty < 10%) — even below the
  round budget. Note it for the report.
- **ultra:** keep looping (new angles: by author/lab names seen in results,
  by venue, by adjacent terminology) until **2 consecutive rounds** are
  saturated. Before finishing, run one completeness pass: ask yourself
  "which survey's references are uncovered? which known lab has zero hits?"
  and turn the answer into a final round.
- If a round budget is exhausted but novelty was still high, finish anyway
  and tell the user: "topic is larger — rerun with higher effort for more."

## Phase 3 — Curate & fetch

Review each round's `items` (already scored & sorted; scoring is transparent
in `search.py` — citations, freshness, venue, fetchability). Drop only
clearly off-topic or unreliable entries; at ultra, drop nothing except
off-topic/unreliable — quantity is not a reason to cut.

```bash
python3 SKILL_DIR/scripts/fetch.py \
  --in <dest>/.sdr/round<N>.json --dest <dest> \
  --max-mb <volume budget> \
  [--top N | --ids id1,id2 | --all] [--min-score X] [--light]
```

**Light mode (`--light`):** papers are stored as Markdown with the text
extracted deterministically by `textextract.py` (arXiv HTML → pdftotext →
abstract-only fallback, method recorded in the file's frontmatter); repos
as README-only. NEVER extract or retype paper content yourself — only the
script's verbatim extraction keeps the anti-hallucination guarantee.
Volume guides shrink accordingly (light rarely exceeds a few MB).

Volume is enforced cumulatively across all fetch calls. HF models/datasets
are recorded as links only (weights are huge). Failed downloads are fine —
they stay in the index as link-only entries via search results you re-add
with `--ids`.

## Phase 4 — Manifest (the anti-hallucination layer)

```bash
# optional: write round stats first
echo '{"rounds": 3, "duration_min": 22, "saturated": true, "novelty_last": 0.06}' \
  > <dest>/.sdr/stats.json
python3 SKILL_DIR/scripts/manifest.py --dest <dest> \
  --topic "<topic>" --effort <effort> --stats <dest>/.sdr/stats.json
```

## Phase 5 — Report

Tell the user, briefly: what was collected (counts by type), volume used,
rounds run, saturation status (exhausted vs. "more exists at higher
effort"), the folder path, and that downstream agents should be pointed
at `<dest>/manifest.json` / `INDEX.md` as their source of truth.

## Environment variables (all optional)

- `GITHUB_TOKEN` — raises GitHub search rate limits
- `SDR_CONTACT_EMAIL` — used in the API User-Agent (polite pool for OpenAlex)
