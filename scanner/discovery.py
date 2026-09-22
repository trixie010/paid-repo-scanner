"""Discovery: finds issues and repos elsewhere on GitHub that suggest paid work.

Two sources, one ranked list:

  issues  search for recently created open issues with bounty/points/program
          labels, dollar amounts, or a named payout platform
  files   search CONTRIBUTING / README files for wording that links merged
          contributions to payment (including "paid via GitHub Sponsors")

Every result carries a tier (A strongest, C weakest), the reason it matched, the
matching snippet, and the payout channel, so you can judge it yourself.
These are hints, never proof of payment.
"""

import base64
import html
import os
import re
import time
from datetime import datetime, timedelta, timezone

from . import github, signals

MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", "25"))
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "12"))          # entries per message
PER_REPO_CAP = int(os.environ.get("PER_REPO_CAP", "3"))          # issues shown per repo
LOOKBACK_DAYS = int(os.environ.get("DISCOVERY_LOOKBACK_DAYS", "3"))
MIN_STARS = int(os.environ.get("MIN_STARS", "5"))
MAX_IDLE_DAYS = int(os.environ.get("MAX_IDLE_DAYS", "60"))
MAX_FILE_CHECKS = int(os.environ.get("MAX_FILE_CHECKS", "25"))   # keeps API use bounded
NEW_REPO_DAYS = 90

# Repos that track or farm bounties rather than pay them
META_REPO = re.compile(r"bounty|bounties|scout|farm|hunter|watch|tracker|plaza", re.I)

# Off-topic content, not a judgement about legitimacy. Discovery only.
BLOCKLIST = [
    "airdrop", "referral", "casino", "gambling", "trading bot",
    "blog post", "article writing", "tutorial proposal", "content creator",
]

ISSUE_QUERIES = [
    'is:issue is:open label:bounty created:>{since}',
    'is:issue is:open label:"💎 Bounty" created:>{since}',
    'is:issue is:open label:paid created:>{since}',
    'is:issue is:open label:reward created:>{since}',
    'is:issue is:open label:drips-wave created:>{since}',
    'is:issue is:open "GitHub Sponsors" contributors paid created:>{since}',
    'is:issue is:open "$" bounty in:title,body created:>{since}',
]

# Code search is strict and partial, so these are few and specific.
FILE_QUERIES = [
    'filename:CONTRIBUTING.md "paid" "merged"',
    'filename:CONTRIBUTING.md "GitHub Sponsors" contributors',
    'filename:CONTRIBUTING.md "rewarded" "pull request"',
    'filename:README.md "contributors are paid"',
    'filename:README.md "we pay contributors"',
    'filename:README.md "paid via GitHub Sponsors"',
]

TIER_ORDER = {"A": 0, "B": 1, "C": 2}


def _blocked(text):
    t = (text or "").lower()
    return any(term in t for term in BLOCKLIST)


def _repo_of(item):
    return item["repository_url"].split("repos/", 1)[-1]


# ----------------------------------------------------------------- issues
def issue_candidates(state):
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    found = {}
    for tmpl in ISSUE_QUERIES:
        data = github.get(
            "https://api.github.com/search/issues",
            params={"q": tmpl.format(since=since), "sort": "created", "order": "desc", "per_page": 30},
        )
        time.sleep(2.5)  # search allows ~30 requests/minute
        for item in (data or {}).get("items", []):
            url = item["html_url"]
            if url in found or state.seen("discovery", url):
                continue
            if "pull_request" in item or item.get("assignees"):
                continue
            if int(item.get("comments", 0)) > MAX_COMMENTS:
                continue
            repo = _repo_of(item)
            if META_REPO.search(repo.split("/")[-1]):
                continue
            if _blocked(f"{item.get('title', '')} {item.get('body', '') or ''}"):
                continue
            sig = signals.classify_issue(item)
            if not sig:
                continue
            found[url] = {
                "key": url, "kind": "issue", "url": url, "repo": repo,
                "title": item["title"], "comments": item.get("comments", 0),
                "created_at": item["created_at"], **sig,
            }
    return list(found.values())


# ------------------------------------------------------------------ files
def _decode(content):
    try:
        return base64.b64decode(content["content"]).decode("utf-8", "replace")
    except Exception:
        return ""


def file_candidates(state):
    """Search code for payment wording, then confirm by reading the file."""
    repos = {}
    for q in FILE_QUERIES:
        data = github.get("https://api.github.com/search/code", params={"q": q, "per_page": 15})
        time.sleep(7)   # code search is limited to about 10 requests/minute
        for it in (data or {}).get("items", []):
            repos.setdefault(it["repository"]["full_name"], it["path"])

    out, checked = [], 0
    for full, path in repos.items():
        key = f"repo:{full}"
        if state.seen("discovery", key) or META_REPO.search(full.split("/")[-1]):
            continue
        if checked >= MAX_FILE_CHECKS:
            break
        checked += 1

        repo = github.get(f"https://api.github.com/repos/{full}")
        if not repo or repo.get("archived") or repo.get("fork"):
            continue
        if repo["stargazers_count"] < MIN_STARS:
            continue
        pushed = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - pushed > timedelta(days=MAX_IDLE_DAYS):
            continue

        f = github.get(f"https://api.github.com/repos/{full}/contents/{path}")
        text = _decode(f) if f else ""
        if _blocked(text[:4000]):
            continue
        sig = signals.classify_text(text)
        if not sig:
            continue

        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        out.append({
            "key": key, "kind": "repo", "url": repo["html_url"], "repo": full,
            "title": (repo.get("description") or "")[:100],
            "stars": repo["stargazers_count"],
            "age_days": (datetime.now(timezone.utc) - created).days,
            "file": path, **sig,
        })
        time.sleep(0.5)
    return out


# ------------------------------------------------------------------ public
def collect(state):
    items = issue_candidates(state)
    if os.environ.get("SKIP_FILE_SEARCH") != "1":
        items += file_candidates(state)
    # strongest tier first, then fewest comments / newest
    items.sort(key=lambda x: (TIER_ORDER[x["tier"]], x.get("comments", 0), x.get("created_at", "")))
    return items


def group(items):
    """Collapse to one entry per repo so one project cannot flood the alert.

    Returns (entries, shown_keys). Every item in a collapsed entry counts as
    shown, because the entry reports how many there were. Only entries beyond
    MAX_RESULTS are left unshown, and those stay unseen so they arrive next time.
    """
    by_repo, order = {}, []
    for it in items:
        if it["repo"] not in by_repo:
            by_repo[it["repo"]] = []
            order.append(it["repo"])
        by_repo[it["repo"]].append(it)

    entries = []
    for repo in order:
        group_items = by_repo[repo]
        head = dict(group_items[0])
        head["count"] = len(group_items)
        head["extra_titles"] = [g["title"] for g in group_items[1:PER_REPO_CAP]]
        head["keys"] = [g["key"] for g in group_items]
        entries.append(head)

    shown = entries[:MAX_RESULTS]
    shown_keys = [k for e in shown for k in e["keys"]]
    return shown, shown_keys, len(entries) - len(shown)


def format_message(entries, hidden=0):
    lines = ["<b>Discovery: possible paid work</b>", "A strong claim · B named platform · C donations only", ""]
    e = html.escape
    for it in entries:
        head = f'<b>{it["tier"]}</b> <a href="{e(it["url"])}">{e(it["repo"])}</a>'
        if it["kind"] == "issue":
            meta = f'💬 {it["comments"]} · {e(it["title"][:80])}'
        else:
            new = "🆕 " if it["age_days"] < NEW_REPO_DAYS else ""
            meta = f'{new}⭐ {it["stars"]} · in {e(it["file"])}'
        lines.append(f"{head}\n    {meta}")
        if it.get("count", 1) > 1:
            more = it["count"] - 1
            lines.append(f"    +{more} more issue{'s' if more > 1 else ''} in this repo")
        lines.append(f"    why: {e(it['reason'])}")
        if it.get("snippet"):
            lines.append(f"    “{e(it['snippet'][:220])}”")
        lines.append(f"    {e(signals.channel_line(it['platforms']))}")
        lines.append("")
    if hidden > 0:
        lines.append(f"...and {hidden} more repos, coming in the next run.")
    lines.append("Hints, not proof. Confirm a program really pays before investing time.")
    return "\n".join(lines)
