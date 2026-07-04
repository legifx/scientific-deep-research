# Example session: researching how to train your own local LLM

The use case this skill was built for: before letting an agent implement a
project, collect the actual literature locally so it codes against real
papers instead of vibes.

**User:**

```
/sdr I want to design and train my own local LLM — how do context windows,
token speed and model architectures actually work? Focus on the newest work
(2026+), both the big revolutionary papers and small labs with potential.
```

**Agent intake (one round):**

- Folder → `./research/local-llm-training/`
- Effort → `high` (~25 min, ≤3 rounds, citation chasing, ~2 GB)
- Time filter → `--since 2026`
- Sources → papers + repos + models

**Agent search plan (sub-queries):**

1. transformer architecture efficient attention
2. long context window extension LLM
3. KV cache inference speed optimization
4. small language model training recipe
5. scaling laws data mixture
6. mixture of experts architecture
7. LLM training survey

**Rounds:**

```bash
python3 scripts/search.py -q "..." ×7 --effort high --since 2026 \
  --seen research/local-llm-training/.sdr/seen.json --out .../round1.json
# round 1: 142 found, novelty 100% → curate, fetch top items
python3 scripts/search.py --cited-by W49... --cited-by W48... \
  -q "grouped query attention" -q "rotary position embedding long context" \
  --effort high --seen .../seen.json --out .../round2.json
# round 2: 96 found, novelty 31% → fetch
# round 3: novelty 8% → saturated, stop
python3 scripts/fetch.py --in .../roundN.json --dest research/local-llm-training \
  --max-mb 2000 --top 30
python3 scripts/manifest.py --dest research/local-llm-training \
  --topic "training a local LLM" --effort high --stats .../stats.json
```

**Result:** ~60 papers as validated PDFs grouped by sub-topic, ~10 reference
repos shallow-cloned, models linked in `INDEX.md`, all citable via
`manifest.json`.

**Then, in the implementation session:**

```
Build the training pipeline. Use research/local-llm-training/manifest.json
as your source of truth — cite local_path for every design decision, and do
not use sources outside that list.
```
