"""Signal detection: how strongly does some text suggest contributors get paid?

Tiers, strongest first:
  A  a direct claim, or money/points attached to an issue
  B  a named payout platform, or sponsor wording next to contributor wording
  C  a funding file only (donations, not payouts)

Everything here is pattern matching, so it is a hint and never proof. Each match
returns the snippet that triggered it so the alert can show the source text.
"""

import re

# ---------------------------------------------------------------- platforms
# name -> (regex, needs_kyc). KYC flag is only set where I have seen it stated.
PLATFORMS = {
    "GitHub Sponsors": (re.compile(r"github\.com/sponsors|github sponsors", re.I), False),
    "Drips": (re.compile(r"drips\.network|drips wave|\bdrips-wave\b|stellar wave", re.I), True),
    "Algora": (re.compile(r"algora\.io", re.I), False),
    "Opire": (re.compile(r"opire\.dev|\bopire\b", re.I), False),
    "Polar": (re.compile(r"polar\.sh", re.I), False),
    "Gitcoin": (re.compile(r"gitcoin", re.I), False),
    "Bountysource": (re.compile(r"bountysource", re.I), False),
    "Open Collective": (re.compile(r"opencollective\.com", re.I), False),
    "IssueHunt": (re.compile(r"issuehunt", re.I), False),
}

# ------------------------------------------------------------ text patterns
# A contribution word within ~80 characters of a payment word, either order.
CONTRIB = (
    r"(?:merged?|contribut\w*|pull requests?|\bPRs?\b|patch(?:es)?|fix(?:es|ed)?|"
    r"issues?|bugs?|commits?)"
)
# Unambiguous payment words. "funded" and "sponsored" are left out on purpose:
# they describe a bug or a company as often as a payout.
PAYMENT = (
    r"(?:paid|pays?|paying|payments?|payouts?|rewarded?|rewards?|monetary|"
    r"compensat\w*|remunerat\w*|earn(?:s|ed)?\s+(?:a\s+)?(?:share|money|cash)|"
    r"bount(?:y|ies)|stipends?|honorari\w*)"
)
# Not preceded/followed by "." or "_" so filenames like rewards.md do not match
PAY_NEAR = re.compile(
    rf"({CONTRIB}[^.\n]{{0,80}}?(?<![\w.]){PAYMENT}(?![\w]|\.\w)"
    rf"|(?<![\w.]){PAYMENT}(?![\w]|\.\w)[^.\n]{{0,80}}?{CONTRIB})",
    re.I,
)

# "Earn $50", "$200 per merged PR": a dollar amount near contribution words
MONEY_NEAR = re.compile(
    rf"(?:{CONTRIB}[^.\n]{{0,60}}?\$\s?\d|\$\s?\d[\d,]*[^.\n]{{0,60}}?{CONTRIB}"
    rf"|earn(?:s|ed)?\s+\$\s?\d)",
    re.I,
)

# Sentences that clearly ask for donations rather than pay contributors
DONATION_ONLY = re.compile(
    r"(support (this|the|our) (project|work)|buy me a coffee|donat\w+|"
    r"become a (sponsor|backer)|sponsor (me|us|this))",
    re.I,
)

# "N points" style labels, and program labels
POINTS_LABEL = re.compile(r"\b\d+\s*[- ]?points?\b", re.I)
PROGRAM_LABEL = re.compile(r"bounty|reward|paid|funded|drips-?wave|stellar wave|💎|💰", re.I)
MONEY = re.compile(r"\$\s?\d[\d,]*(\.\d+)?|\b\d[\d,]*\s?(usd|usdc|dollars)\b", re.I)


def detect_platforms(text):
    """Return [(name, needs_kyc)] for every payout platform named in text."""
    return [(name, kyc) for name, (rx, kyc) in PLATFORMS.items() if rx.search(text or "")]


def snippet(text, match, width=70):
    s = max(0, match.start() - 10)
    e = min(len(text), match.end() + 10)
    out = " ".join(text[s:e].split())
    return out[: width * 2]


def classify_text(text):
    """Classify README/CONTRIBUTING-style text.

    Returns dict(tier, reason, snippet, platforms) or None.
    """
    if not text:
        return None
    platforms = detect_platforms(text)

    m = PAY_NEAR.search(text)
    if m:
        # Skip when the matching sentence is a plain donation ask
        sentence = snippet(text, m, width=120)
        if not DONATION_ONLY.search(sentence):
            return {"tier": "A", "reason": "text links contributions to payment",
                    "snippet": sentence, "platforms": platforms}

    # A bare dollar amount near contribution words is weaker: it also matches
    # pricing pages, so it is ranked B and never A.
    m = MONEY_NEAR.search(text)
    if m:
        return {"tier": "B", "reason": "dollar amount near contribution wording",
                "snippet": snippet(text, m, width=120), "platforms": platforms}

    if platforms:
        names = ", ".join(n for n, _ in platforms)
        first = next(iter(PLATFORMS[platforms[0][0]][0].finditer(text)), None)
        return {"tier": "B", "reason": f"names payout platform: {names}",
                "snippet": snippet(text, first) if first else "", "platforms": platforms}
    return None


def classify_issue(item):
    """Classify a GitHub issue dict from the search API.

    Returns dict(tier, reason, snippet, platforms) or None.
    """
    labels = [l["name"] for l in item.get("labels", [])]
    text = f"{item.get('title', '')}\n{item.get('body', '') or ''}"
    label_blob = " | ".join(labels)
    platforms = detect_platforms(f"{text}\n{label_blob}")

    if any(POINTS_LABEL.search(l) for l in labels) or any(PROGRAM_LABEL.search(l) for l in labels):
        which = next((l for l in labels if POINTS_LABEL.search(l) or PROGRAM_LABEL.search(l)), "")
        return {"tier": "A", "reason": f"label: {which}", "snippet": "", "platforms": platforms}

    m = MONEY.search(text)
    if m:
        return {"tier": "A", "reason": f"amount: {m.group(0)}",
                "snippet": snippet(text, m), "platforms": platforms}

    if platforms:
        names = ", ".join(n for n, _ in platforms)
        return {"tier": "B", "reason": f"names payout platform: {names}",
                "snippet": "", "platforms": platforms}
    return None


def classify_funding_file(text):
    """A FUNDING.yml only proves donations are accepted."""
    if not text or not re.search(r"^\s*\w+\s*:", text, re.M):
        return None
    platforms = detect_platforms(text)
    if re.search(r"^\s*github\s*:", text, re.M | re.I) and not platforms:
        platforms = [("GitHub Sponsors", False)]
    return {"tier": "C", "reason": "FUNDING.yml (accepts donations, not proof of payouts)",
            "snippet": "", "platforms": platforms}


def channel_line(platforms):
    """Human-readable payout channel for the alert."""
    if not platforms:
        return "channel: unknown"
    parts = [f"{n} (ID/KYC likely needed)" if kyc else n for n, kyc in platforms]
    return "channel: " + ", ".join(parts)
