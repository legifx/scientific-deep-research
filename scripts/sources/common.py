"""Shared HTTP helpers for source adapters. Stdlib only, no dependencies."""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = (
    "scientific-deep-research/1.0 "
    "(+https://github.com/legifx/scientific-deep-research; "
    f"mailto:{os.environ.get('SDR_CONTACT_EMAIL', 'sdr-skill@example.org')})"
)

RETRIES = 3
BACKOFF = 2.0

# ---- Test seam (C08) ----------------------------------------------------
# Tests replace http_get with a fixture-backed function so the suite never
# touches the network. Production behaviour is unchanged when it is None.
_HTTP_GET_OVERRIDE = None


def set_http_get(fn):
    global _HTTP_GET_OVERRIDE
    _HTTP_GET_OVERRIDE = fn


def real_http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    """The actual network request, independent of any test override."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503):
                time.sleep(BACKOFF * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(BACKOFF * (attempt + 1))
    raise last_err


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    """GET with retries and polite backoff. Raises on final failure."""
    if _HTTP_GET_OVERRIDE is not None:
        return _HTTP_GET_OVERRIDE(url, headers, timeout)
    return real_http_get(url, headers, timeout)


def content_length(url: str, headers: dict | None = None, timeout: int = 30):
    """C04 pre-flight: declared size via HEAD, or None if unknown.

    Lets fetch.py refuse an oversized download before transferring it.
    """
    if _HTTP_GET_OVERRIDE is not None or not url:
        return None
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, headers=hdrs, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            v = resp.headers.get("Content-Length")
            return int(v) if v else None
    except Exception:
        return None


def get_json(url: str, headers: dict | None = None, timeout: int = 30):
    return json.loads(http_get(url, headers, timeout).decode("utf-8"))


def qs(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def warn(msg: str):
    print(f"[sdr] {msg}", file=sys.stderr)


# ---- Text similarity (C02 / C12) ----------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def tokens(text: str) -> set:
    return set(_TOKEN_RE.findall((text or "").lower()))


def jaccard(a: str, b: str):
    """Token Jaccard similarity, or None if either side has no tokens."""
    A, B = tokens(a), tokens(b)
    if not A or not B:
        return None
    return len(A & B) / len(A | B)


# ---- Volume accounting (C04) --------------------------------------------
def disk_bytes(path) -> int:
    """Bytes actually allocated on disk, not logical file size.

    A directory of many small files can occupy far more than the sum of
    st_size, so the volume budget counts allocated blocks where available.
    """
    total = 0
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        blocks = getattr(st, "st_blocks", None)
        total += blocks * 512 if blocks else st.st_size
    return total


def file_bytes(path) -> int:
    """Allocated bytes for a single file."""
    try:
        st = path.stat()
    except OSError:
        return 0
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks else st.st_size


# ---- Run report (C14 minimal) -------------------------------------------
def read_report(sdr_dir: Path) -> dict:
    f = Path(sdr_dir) / "report.json"
    return json.loads(f.read_text()) if f.exists() else {}


def update_report(sdr_dir: Path, **kv) -> dict:
    """Merge counters into <sdr_dir>/report.json (cumulative across scripts)."""
    d = Path(sdr_dir)
    d.mkdir(parents=True, exist_ok=True)
    rep = read_report(d)
    for k, v in kv.items():
        if isinstance(v, (int, float)) and isinstance(rep.get(k), (int, float)):
            rep[k] = rep[k] + v
        else:
            rep[k] = v
    (d / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    return rep
