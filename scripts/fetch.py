#!/usr/bin/env python3
"""Download curated items into the research folder, enforcing the volume budget.

- Papers: PDF via pdf_url (arXiv direct or open-access location), validated
  by magic bytes (%PDF) so HTML error pages never masquerade as papers, then
  checked against the title so a mis-linked PDF cannot pass as another paper.
- Repos: shallow git clone (--depth 1) into repos/, size pre-checked against
  the GitHub API `size` field so nothing is cloned just to be deleted.
- HF models/datasets: recorded as links only (weights are huge).
- Volume: running counter across ALL calls (persisted in .sdr/state.json),
  measured in allocated disk blocks rather than logical file size.
- Failures never disappear: an item that cannot be downloaded is kept as a
  link-only record with a failure reason (C05).

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


# Every fetch_* returns (path_or_None, size, error_or_None).
# An error string is a failure reason for the link-only record (C05), never
# a silent drop.


def fetch_pdf(item: dict, dest: Path, budget=None, used=0):
    url = item.get("pdf_url")
    if not url:
        return None, 0, "no_pdf_url"
    if budget is not None:
        declared = common.content_length(url)
        if declared and used + declared > budget:
            return None, 0, "over_budget_preflight"
    try:
        data = common.http_get(url, timeout=60)
    except Exception as e:
        code = getattr(e, "code", None)
        return None, 0, f"http_{code}" if code else f"download_failed:{type(e).__name__}"
    if not data.startswith(b"%PDF"):
        return None, 0, "not_a_pdf"
    sub = dest / "papers" / slugify(item.get("query", "misc"))
    sub.mkdir(parents=True, exist_ok=True)
    year = item.get("year") or "nd"
    path = sub / f"{year}-{slugify(item['title'])}.pdf"
    path.write_bytes(data)
    # C12: does the content match the record it is filed under?
    match = textextract.verify_pdf_against_title(data, item.get("title") or "")
    if match is not None:
        item["title_match"] = match
        if match < textextract.VERIFY_THRESHOLD:
            item["status"] = "pdf_unverified"
            common.warn(f"  title match only {match:.2f} — marked pdf_unverified")
    else:
        item["title_match"] = None
    return path, common.file_bytes(path), None


def fetch_paper_light(item: dict, dest: Path, budget=None, used=0):
    """Light mode: extract text deterministically, store as Markdown."""
    text, method = textextract.extract(item)
    if method == "abstract-only" and not (item.get("abstract") or "").strip():
        return None, 0, "no_text_available"
    doc = textextract.to_markdown_doc(item, text, method)
    sub = dest / "papers" / slugify(item.get("query", "misc"))
    sub.mkdir(parents=True, exist_ok=True)
    year = item.get("year") or "nd"
    path = sub / f"{year}-{slugify(item['title'])}.md"
    path.write_text(doc)
    common.warn(f"  extracted via {method} ({len(doc) // 1024} KB)")
    item["extraction"] = method
    return path, common.file_bytes(path), None


def fetch_repo_light(item: dict, dest: Path, budget=None, used=0):
    """Light mode: fetch only the repo README instead of cloning."""
    url = f"https://api.github.com/repos/{item['title']}/readme"
    try:
        data = common.http_get(url, headers={"Accept": "application/vnd.github.raw+json"})
    except Exception as e:
        code = getattr(e, "code", None)
        return None, 0, f"http_{code}" if code else "readme_failed"
    sub = dest / "repos"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{slugify(item['title'])}-README.md"
    header = (f"---\nrepo: {item['url']}\nstars: {item.get('citations')}\n"
              f"note: light mode — README only; clone the repo for code\n---\n\n")
    path.write_text(header + data.decode("utf-8", "replace"))
    return path, common.file_bytes(path), None


def fetch_repo(item: dict, dest: Path, budget=None, used=0):
    sub = dest / "repos"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / slugify(item["title"])
    if path.exists():
        return None, 0, "already_present"
    # C04: the GitHub search result already carries the repo size in KB.
    # Check it before cloning so an oversized repo is never transferred.
    est = (item.get("size_kb") or 0) * 1024
    if budget is not None and est and used + est > budget:
        return None, 0, "over_budget_preflight"
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", item["clone_url"], str(path)],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        return None, 0, "clone_failed"
    return path, common.disk_bytes(path), None


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
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the PDF title check (C12)")
    args = ap.parse_args()

    data = json.loads(Path(args.infile).read_text())
    if data.get("aborted"):
        common.warn("search.py reported aborted=true — nothing to fetch")
        print(json.dumps({"fetched": 0, "aborted": True,
                          "reason": data.get("reason")}, indent=2))
        sys.exit(1)

    dest = Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    state = load_state(dest)
    budget = int(args.max_mb * 1024 * 1024) if args.max_mb else None

    items = data["items"]
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

    if args.no_verify:
        textextract.VERIFY_THRESHOLD = 0.0

    records, skipped_budget, failed = [], 0, 0
    unverified = 0
    for item in items:
        if item["dedupe_key"] in state["fetched_keys"]:
            continue
        if budget is not None and state["bytes_used"] >= budget:
            skipped_budget += 1
            continue
        common.warn(f"fetching {item['id']}: {item['title'][:70]}")
        if item.get("clone_url"):
            fn = fetch_repo_light if args.light else fetch_repo
        elif item.get("type") == "paper":
            fn = fetch_paper_light if args.light else fetch_pdf
        elif item["source"] == "huggingface":
            if args.hf_download:
                common.warn("  --hf-download not implemented for weights; recording link")
            rec = dict(item)
            rec.update({"local_path": None, "size_bytes": 0,
                        "status": "link_only", "failure_reason": "weights_not_downloaded"})
            records.append(rec)
            state["fetched_keys"].append(item["dedupe_key"])
            continue
        else:
            continue

        path, size, err = fn(item, dest, budget, state["bytes_used"])

        if err:
            # C05: keep it as a link-only record instead of dropping it.
            if err == "over_budget_preflight":
                skipped_budget += 1
                common.warn(f"  size exceeds remaining budget — skipped ({err})")
                continue
            failed += 1
            common.warn(f"  {err} — kept as link-only entry")
            rec = dict(item)
            rec.update({"local_path": None, "size_bytes": 0,
                        "status": "link_only", "failure_reason": err})
            records.append(rec)
            state["fetched_keys"].append(item["dedupe_key"])
            continue

        if budget is not None and state["bytes_used"] + size > budget:
            if path.is_dir():
                subprocess.run(["rm", "-rf", str(path)])
            else:
                path.unlink(missing_ok=True)
            skipped_budget += 1
            # C04: stop here. Previously this continued and downloaded every
            # remaining item only to delete it.
            common.warn("  exceeds volume budget — removed, stopping fetch loop")
            break

        if item.get("status") == "pdf_unverified":
            unverified += 1
        state["bytes_used"] += size
        state["fetched_keys"].append(item["dedupe_key"])
        rec = dict(item)
        rec["local_path"] = str(path.relative_to(dest))
        rec["size_bytes"] = size
        rec.setdefault("status", "downloaded")
        records.append(rec)

    append_fetched(dest, records)
    save_state(dest, state)
    link_only = sum(1 for r in records if r.get("status") == "link_only")
    common.update_report(
        dest / ".sdr",
        fetched=len(records), failed=failed, link_only=link_only,
        skipped_over_budget=skipped_budget, pdf_unverified=unverified,
        volume_used_mb=round(state["bytes_used"] / 1024 / 1024, 2),
        volume_budget_mb=args.max_mb, volume_unit="disk_blocks",
    )
    print(json.dumps({
        "fetched": len(records),
        "failed": failed,
        "link_only": link_only,
        "skipped_over_budget": skipped_budget,
        "pdf_unverified": unverified,
        "volume_used_mb": round(state["bytes_used"] / 1024 / 1024, 2),
        "volume_budget_mb": args.max_mb,
        "volume_unit": "disk_blocks",
        "dest": str(dest),
    }, indent=2))


if __name__ == "__main__":
    main()
