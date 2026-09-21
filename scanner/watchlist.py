"""Watchlist: alerts you to new, still-available issues in repos you choose.

Each new issue is checked for signs it is already taken (assignee, an open PR
that references it, or a comment like "I'll take this"). Taken issues are
hidden so an alert means there is still something you can grab.

No keyword blocklist is applied here: everything in your watched repos is
shown, because you chose them.
"""

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

from . import github

WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "watchlist.json")

CLAIM_PATTERN = re.compile(
    r"\b(i'?ll take|i will take|i'?m working|i am working|i'?m fixing|i am fixing|"
    r"working on (it|this)|i'?d like to work|can i work|assign (this )?to me|"
    r"i can (fix|take|work)|i'?ll (fix|work on|do))\b",
    re.IGNORECASE,
)

ICON = {"open": "🟢", "claimed": "🟡", "assigned": "🟠", "has-pr": "🔴"}
ORDER = {"open": 0, "claimed": 1, "assigned": 2, "has-pr": 3}


def load_config():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


def expand_repos(cfg):
    """Repos to watch: the explicit list plus, optionally, every repo in orgs."""
    repos = list(cfg.get("repos", []))
    for org in cfg.get("orgs", []):
        # Most recently pushed first, so active repos are covered even if capped
        items = github.get(
            f"https://api.github.com/orgs/{org}/repos",
            params={"sort": "pushed", "direction": "desc", "per_page": cfg.get("org_repo_limit", 30)},
        )
        for r in items or []:
            if not r.get("archived") and not r.get("fork"):
                repos.append(r["full_name"])
    seen, out = set(), []
    for r in repos:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def claim_status(repo, issue):
    """Return (state, detail): open, claimed, assigned or has-pr."""
    number = issue["number"]

    if issue.get("assignees"):
        names = ", ".join(a["login"] for a in issue["assignees"])
        return "assigned", f"assigned to {names}"

    timeline = github.get(
        f"https://api.github.com/repos/{repo}/issues/{number}/timeline",
        params={"per_page": 100},
    )
    prs = set()
    for ev in timeline or []:
        if ev.get("event") == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            # the key's presence marks a PR; its value can be an empty dict
            if "pull_request" in src and src.get("state") == "open":
                prs.add(src["number"])
    if prs:
        return "has-pr", "open PR: " + ", ".join(f"#{n}" for n in sorted(prs))

    if issue.get("comments", 0) > 0:
        comments = github.get(
            f"https://api.github.com/repos/{repo}/issues/{number}/comments",
            params={"per_page": 30},
        )
        for c in comments or []:
            if CLAIM_PATTERN.search(c.get("body") or ""):
                return "claimed", f"claim comment by {c['user']['login']}"

    return "open", "no claim found"


def collect(state, dry_run=False):
    """Return (alerts, keys). Nothing is recorded as seen here."""
    cfg = load_config()
    since = (
        datetime.now(timezone.utc) - timedelta(days=cfg.get("lookback_days", 2))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    skip_labels = {s.lower() for s in cfg.get("skip_labels", [])}
    hide = set(cfg.get("hide_states", []))
    max_comments = cfg.get("max_comments")

    alerts, keys = [], []          # keys: shown to you, recorded after a good send
    quiet = []                     # hidden or skipped: safe to record right away

    for repo in expand_repos(cfg):
        items = github.get(
            f"https://api.github.com/repos/{repo}/issues",
            params={
                "state": "open",
                "since": since,
                "sort": "created",
                "direction": "desc",
                "per_page": cfg.get("max_issues_per_repo", 30),
            },
        )
        time.sleep(0.5)
        for issue in items or []:
            if "pull_request" in issue:
                continue
            if issue["created_at"] < since:
                continue  # 'since' matches updates; we only want new issues
            key = f"{repo}#{issue['number']}"
            if state.seen("watchlist", key):
                continue
            if {l["name"].lower() for l in issue.get("labels", [])} & skip_labels:
                quiet.append(key)
                continue
            if max_comments is not None and issue.get("comments", 0) > max_comments:
                quiet.append(key)
                continue

            status, detail = claim_status(repo, issue)
            if status in hide:
                quiet.append(key)
                continue

            alerts.append(
                {
                    "key": key,
                    "repo": repo,
                    "number": issue["number"],
                    "title": issue["title"],
                    "url": issue["html_url"],
                    "state": status,
                    "detail": detail,
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "created_at": issue["created_at"],
                }
            )
            keys.append(key)

    if not dry_run:
        for k in quiet:
            state.mark("watchlist", k)
    return alerts, keys


def format_message(alerts, max_items=15):
    alerts = sorted(alerts, key=lambda a: (ORDER[a["state"]], a["created_at"]))
    lines = ["<b>Watchlist: new issues</b>", "🟢 open · 🟡 claimed", ""]
    for a in alerts[:max_items]:
        title = html.escape(a["title"][:90])
        labels = f" [{html.escape(', '.join(a['labels'][:3]))}]" if a["labels"] else ""
        lines.append(
            f'{ICON[a["state"]]} <a href="{html.escape(a["url"])}">'
            f'{html.escape(a["repo"])}#{a["number"]}</a> {title}{labels}\n'
            f"    {html.escape(a['detail'])}"
        )
    if len(alerts) > max_items:
        lines.append(f"\n...and {len(alerts) - max_items} more.")
    return "\n".join(lines)
