# Scientific Deep Research (`/sdr`)

**An agent skill that turns any topic into a local, citable research library** —
real papers (PDFs), repos and models, downloaded into a folder with a
machine-readable manifest, so your coding agent works from ground truth
instead of hallucinating sources.

Works with **Claude Code, Codex, Antigravity, Gemini CLI, Hermes** and any
agent CLI that can read a Markdown skill and run Python. No dependencies —
stdlib-only Python 3.8+, no API keys required.

```
/sdr how do modern LLMs handle long context — architectures, KV cache, inference speed
```

The agent asks four things (folder, effort, time filter, source types),
then searches **arXiv, OpenAlex, GitHub and Hugging Face**, curates by a
transparent seriousness score, downloads validated PDFs and shallow repo
clones under a hard volume cap, and writes:

```
research/long-context-llms/
├── INDEX.md            # human-readable, grouped by sub-topic, with scores & links
├── manifest.json       # machine-readable ground truth for downstream agents
├── papers/<subtopic>/2026-....pdf
└── repos/<name>/
```

## Effort levels — budgets, not document counts

Inspired by effort dials in modern agent CLIs. Each level is a **budget
profile** across duration, search rounds, breadth and volume — the number
of documents *emerges* from the budget and the topic size. The quality bar
is identical everywhere: low effort digs less, it never accepts worse sources.

| Effort | Duration guide | Rounds | Expansion | Volume guide |
|---|---|---|---|---|
| `low` | ~2 min | 1 | — | ~100 MB |
| `medium` | ~10 min | ≤2 | — | ~500 MB |
| `high` | ~25 min | ≤3 | citation chasing | ~2 GB |
| `xhigh` | ~45 min | ≤5 | + bibliographies | ~5 GB |
| `ultra` | open-ended | until dry | full citation snowball | unlimited* |

*ultra requires explicit confirmation and loops until two consecutive
rounds find nothing new (saturation < 10 % novelty), then runs a
completeness pass ("which survey's references are uncovered?").

Searches measure their own **saturation**: if a topic is exhausted early,
the run stops below budget; if it isn't, the agent tells you a higher
effort would find substantially more.

## Full vs. Light version

Two storage modes, same skill, same search — chosen in the intake (or say
"light" in your request):

| | `full` (default) | `light` (`--light`) |
|---|---|---|
| Papers | original PDFs | verbatim text as Markdown (frontmatter: source, extraction method) |
| Repos | shallow clone | README only |
| Size | GBs | **10–50x smaller** (a whole research run in a few MB) |
| Best for | archival, exact figures/formulas | tight disk space, **agent brains** — agents read MD/TXT much faster than PDFs |

Light-mode extraction is deterministic code, never the LLM retyping text:
arXiv HTML rendering → `pdftotext` (if installed) → abstract-only fallback,
with the method recorded in every file so you know what you have.

## Anti-hallucination by construction

- The **scripts** search and download (live API results); the **agent**
  only orchestrates and curates. No source ever comes from model memory.
- PDFs are validated by magic bytes — HTML error pages never end up as "papers".
- `manifest.json` lists every document with its `local_path`; downstream
  agents are instructed to cite only from this list.
- The seriousness score (citations, freshness, venue, fetchability, a
  "small lab with potential" bonus) lives in
  [`scripts/search.py`](scripts/search.py) as reviewable code — tune it
  via PR, not via prompt.

## Install

```bash
git clone https://github.com/legifx/scientific-deep-research
cd scientific-deep-research && ./install.sh
```

The installer copies the skill to `~/.agents/skills/scientific-deep-research`
(or a dir you pass as `$1`) and offers to symlink it for Claude Code
(`~/.claude/skills/`) and append a trigger note to a project `AGENTS.md`
for CLIs without native skill support.

Manual: copy this folder anywhere your agent reads skills from, or just
tell your agent: *"Read SKILL.md in <path> and follow it for: <topic>"*.

## Scripts (usable standalone)

```bash
python3 scripts/search.py -q "kv cache compression" --effort medium --since 2025 --out r1.json
python3 scripts/fetch.py --in r1.json --dest ./research/kv-cache --max-mb 500 --top 20
python3 scripts/manifest.py --dest ./research/kv-cache --topic "KV cache" --effort medium
```

Optional env: `GITHUB_TOKEN` (higher rate limits), `SDR_CONTACT_EMAIL`
(polite-pool User-Agent for OpenAlex).

## Sources

| Source | What | Key needed |
|---|---|---|
| [arXiv](https://arxiv.org) | preprints, direct PDFs | no |
| [OpenAlex](https://openalex.org) | 250M+ works, citations, venues, OA links, citation graph | no |
| [GitHub](https://github.com) | implementations (stars ≈ adoption) | optional |
| [Hugging Face](https://huggingface.co) | models & datasets (link-only by default) | no |

Only official APIs and open-access locations are used — no scraping, no
paywall circumvention.

## License

MIT
