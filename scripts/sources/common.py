"""Shared HTTP helpers for source adapters. Stdlib only, no dependencies."""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "scientific-deep-research/1.0 "
    "(+https://github.com/legifx/scientific-deep-research; "
    f"mailto:{os.environ.get('SDR_CONTACT_EMAIL', 'sdr-skill@example.org')})"
)

RETRIES = 3
BACKOFF = 2.0


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    """GET with retries and polite backoff. Raises on final failure."""
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


def get_json(url: str, headers: dict | None = None, timeout: int = 30):
    return json.loads(http_get(url, headers, timeout).decode("utf-8"))


def qs(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def warn(msg: str):
    print(f"[sdr] {msg}", file=sys.stderr)
