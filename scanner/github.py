"""Small GitHub API helpers with rate-limit awareness."""

import os
import time

import requests

TOKEN = os.environ.get("GH_SCAN_TOKEN") or os.environ.get("GITHUB_TOKEN")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "paid-repo-scanner",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get(url, params=None, headers=None):
    """GET returning parsed JSON, or None on any failure. Never raises."""
    try:
        r = requests.get(url, headers={**HEADERS, **(headers or {})}, params=params, timeout=30)
    except requests.RequestException as e:
        print(f"[warn] request failed {url}: {e}")
        return None
    if r.status_code in (403, 429):
        remaining = r.headers.get("X-RateLimit-Remaining")
        reset = r.headers.get("X-RateLimit-Reset")
        wait = 60
        if remaining == "0" and reset and reset.isdigit():
            wait = max(1, min(int(reset) - int(time.time()), 90))
        print(f"[warn] rate limited on {url}, waiting {wait}s")
        time.sleep(wait)
        return None
    if r.status_code != 200:
        print(f"[warn] {r.status_code} on {url}")
        return None
    return r.json()
