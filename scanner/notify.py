"""Telegram notifications, with an optional GitHub-issue backup channel.

Callers get True back only when at least one channel accepted the message, so
they can mark items as seen AFTER a successful send instead of before.
"""

import os
import re

import requests

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
NOTIFY_GH_ISSUE = os.environ.get("NOTIFY_GH_ISSUE", "").lower() in ("1", "true", "yes")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
WORKFLOW_TOKEN = os.environ.get("WORKFLOW_TOKEN")

TG_LIMIT = 4000  # Telegram caps messages at 4096 characters


def _telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]}")


def _github_issue(text, title):
    plain = text.replace("<b>", "**").replace("</b>", "**")
    plain = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", plain)
    r = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/issues",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {WORKFLOW_TOKEN}",
        },
        json={"title": title, "body": plain, "labels": ["scanner-alert"]},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub issue {r.status_code}: {r.text[:200]}")


def split_message(text, limit=TG_LIMIT):
    """Split on blank lines so no message exceeds Telegram's limit."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts


def notify(text, title="Scanner alert"):
    """Return True if the alert was delivered by at least one channel."""
    if DRY_RUN:
        print("---- DRY RUN: would send ----")
        print(text)
        return False  # nothing delivered, so callers must not record it as seen

    delivered = False
    if TG_TOKEN and TG_CHAT_ID:
        try:
            for part in split_message(text):
                _telegram(part)
            delivered = True
        except Exception as e:
            print(f"[error] Telegram failed: {e}")

    if NOTIFY_GH_ISSUE and GH_REPO and WORKFLOW_TOKEN:
        try:
            _github_issue(text, title)
            delivered = True
        except Exception as e:
            print(f"[error] backup issue failed: {e}")

    return delivered
