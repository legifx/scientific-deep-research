#!/usr/bin/env python3
"""Download curated items into the research folder, enforcing the volume budget.

- Papers: PDF via pdf_url (arXiv direct or open-access location), validated
  by magic bytes (%PDF) so HTML error pages never masquerade as papers.
- Repos: shallow git clone (--depth 1) into repos/.
- HF models/datasets: recorded as links only (weights are huge); pass
  --hf-download to actually snapshot them.
- Volume: running byte counter across ALL calls (persisted in .sdr/state.json);
  items that would exceed --max-mb are skipped and reported, never truncated.

Usage:
  python3 fetch.py --in round1.json --dest ~/research/llm-training \
      --max-mb 500 [--top 20 | --ids id1,id2 | --all] [--min-score 4]

Appends to <dest>/.sdr/fetched.json; run manifest.py afterwards.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sources import common, textextract  # noqa: E402


def slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].rstrip("-") or "untitled"


def load_state(dest: Path) -> dict:
    f = dest / ".sdr" / "state.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"bytes_used": 0, "fetched_keys": []}


def save_state(dest: Path, state: dict):
    d = dest / ".sdr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state, indent=2))


def append_fetched(dest: Path, records: list[dict]):
    (dest / ".sdr").mkdir(parents=True, exist_ok=True)
    f = dest / ".sdr" / "fetched.json"
    existing = json.loads(f.read_text()) if f.exists() else []
    seen = {r["dedupe_key"] for r in existing}
    existing += [r for r in records if r["dedupe_key"] not in seen]
    f.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


def fetch_pdf(item: dict, dest: Path) -> tuple[Path, int] | None:
    url = item.get("pdf_url")
    if not url:
        return None
    try:
        data = common.http_get(url, timeout=60)
    except Exception as e:
        common.warn(f"  download failed: {e}")
        return None
    if not data.startswith(b"%PDF"):
        common.warn("  not a real PDF (magic bytes) — skipped")
        return None
    sub = dest / "papers" / slugify(item.get("query", "misc"))
    sub.mkdir(parents=True, exist_ok=True)
    year = item.get("year") or "nd"
    path = sub / f"{year}-{slugify(item['title'])}.pdf"
    path.write_bytes(data)
    return path, len(data)


def fetch_paper_light(item: dict, dest: Path) -> tuple[Path, int] | None:
    """Light mode: extract text deterministically, store as Markdown."""
    text, method = textextract.extract(item)
    doc = textextract.to_markdown_doc(item, text, method)
    sub = dest / "papers" / slugify(item.get("query", "misc"))
    sub.mkdir(parents=True, exist_ok=True)
    year = item.get("year") or "nd"
    path = sub / f"{year}-{slugify(item['title'])}.md"
    path.write_text(doc)
    common.warn(f"  extracted via {method} ({len(doc) // 1024} KB)")
    item["extraction"] = method
    return path, len(doc.encode())


def fetch_repo_light(item: dict, dest: Path) -> tuple[Path, int] | None:
    """Light mode: fetch only the repo README instead of cloning."""
    url = f"https://api.github.com/repos/{item['title']}/readme"
    try:
        data = common.http_get(url, headers={"Accept": "application/vnd.github.raw+json"})
    except Exception as e:
        common.warn(f"  README fetch failed: {e}")
        return None
    sub = dest / "repos"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{slugify(item['title'])}-README.md"
    header = (f"---\nrepo: {item['url']}\nstars: {item.get('citations')}\n"
              f"note: light mode — README only; clone the repo for code\n---\n\n")
    path.write_text(header + data.decode("utf-8", "replace"))
    return path, len(data) + len(header)


def fetch_repo(item: dict, dest: Path) -> tuple[Path, int] | None:
    sub = dest / "repos"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / slugify(item["title"])
    if path.exists():
        return None
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", item["clone_url"], str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        common.warn(f"  clone failed: {r.stderr.strip()[:200]}")
        return None
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return path, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True, help="search.py result JSON")
    ap.add_argument("--dest", required=True, help="research folder")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="volume budget in MB (cumulative across runs); omit = unlimited")
    ap.add_argument("--top", type=int, default=None, help="take top-N by score")
    ap.add_argument("--ids", default=None, help="comma list of item ids to fetch")
    ap.add_argument("--all", action="store_true", help="fetch every item in the file")
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--hf-download", action="store_true",
                    help="actually download HF models/datasets (can be huge)")
    ap.add_argument("--light", action="store_true",
                    help="light mode: store extracted text as MD instead of "
                         "PDFs, repo READMEs instead of clones (10-50x smaller, "
                         "faster for agents to read)")
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    state = load_state(dest)
    budget = int(args.max_mb * 1024 * 1024) if args.max_mb else None

    items = json.loads(Path(args.infile).read_text())["items"]
    if args.min_score is not None:
        items = [i for i in items if i["score"] >= args.min_score]
    if args.ids:
        want = set(args.ids.split(","))
        items = [i for i in items if i["id"] in want]
    elif args.top:
        items = items[: args.top]
    elif not args.all:
        common.warn("no selection flag given (--top/--ids/--all); defaulting to --top 20")
        items = items[:20]

    records, skipped_budget, failed = [], 0, 0
    for item in items:
        if item["dedupe_key"] in state["fetched_keys"]:
            continue
        if budget is not None and state["bytes_used"] >= budget:
            skipped_budget += 1
            continue
        common.warn(f"fetching {item['id']}: {item['title'][:70]}")
        result = None
        if item.get("clone_url"):
            result = (fetch_repo_light if args.light else fetch_repo)(item, dest)
        elif item.get("type") == "paper":
            result = (fetch_paper_light(item, dest) if args.light
                      else fetch_pdf(item, dest))
        elif item["source"] == "huggingface":
            if args.hf_download:
                common.warn("  --hf-download not implemented for weights; recording link")
            result = ("<link-only>", 0)
        if result is None:
            failed += 1
            continue
        path, size = result
        if budget is not None and state["bytes_used"] + size > budget:
            # over budget: remove what we just wrote and stop taking new items
            if isinstance(path, Path):
                if path.is_dir():
                    subprocess.run(["rm", "-rf", str(path)])
                else:
                    path.unlink()
            skipped_budget += 1
            common.warn("  exceeds volume budget — removed, skipping further items")
            continue
        state["bytes_used"] += size
        state["fetched_keys"].append(item["dedupe_key"])
        rec = dict(item)
        rec["local_path"] = str(path.relative_to(dest)) if isinstance(path, Path) else path
        rec["size_bytes"] = size
        records.append(rec)

    append_fetched(dest, records)
    save_state(dest, state)
    used_mb = state["bytes_used"] / 1024 / 1024
    print(json.dumps({
        "fetched": len(records),
        "failed": failed,
        "skipped_over_budget": skipped_budget,
        "volume_used_mb": round(used_mb, 1),
        "volume_budget_mb": args.max_mb,
        "dest": str(dest),
    }, indent=2))


if __name__ == "__main__":
    main()
