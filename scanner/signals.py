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
# Words that mean "someone did work on the project"
CONTRIB = (
    r"(?:merged?|contribut\w*|pull requests?|\bPRs?\b|patch(?:es)?|fix(?:es|ed)?|"
    r"issues?|bugs?|commits?)"
)

# The PROJECT must be the payer. These patterns describe the project paying
# contributors, and they are checked one SENTENCE at a time.
PROJECT_PAYS = [
    # "we pay contributors", "we reward merged PRs", "we offer bounties/rewards"
    re.compile(r"\bwe\s+(?:will\s+|do\s+|also\s+)?(?:pay|reward|compensate|sponsor|fund|offer|award)\b"
               r"[^.\n]{0,60}?\b(?:contribut\w*|pull requests?|\bPRs?\b|patch(?:es)?|fix(?:es)?|"
               r"bugs?|issues?|work|bount(?:y|ies)|rewards?|money|payments?|stipends?)", re.I),
    # "contributors are/get/will be paid|rewarded|compensated"
    re.compile(r"\b(?:contributors?|contributions?|merged (?:pull requests?|PRs?)|"
               r"pull requests?|\bPRs?\b|maintainers?)\s+(?:\w+\s+){0,3}?"
               r"(?:are|is|get|gets|will be|can be|may be|receive[sd]?)\s+"
               r"(?:\w+\s+){0,2}?(?:paid|rewarded|compensated|remunerated|eligible for (?:payment|a reward|rewards?))\b", re.I),
    # "paid contributors", "paid bounties", "bounty program", "bounty board"
    re.compile(r"\bpaid\s+(?:contributors?|bount(?:y|ies)|bounty program)\b"
               r"|\bbounty\s+(?:program|board|programme|pool|hunters?)\b"
               r"|\bbounties\s+(?:are|is)\s+(?:paid|available|offered|posted)\b", re.I),
    # "paid via/through GitHub Sponsors|Open Collective|Algora ..."
    re.compile(r"\b(?:paid|payouts?|payments?|rewards?|bounties)\s+(?:are\s+|is\s+)?(?:made\s+)?"
               r"(?:via|through|using|from|by)\s+(?:github sponsors|opencollective|open collective|"
               r"algora|opire|polar|drips|gitcoin|paypal|stripe|usdc|crypto)\b", re.I),
    # "merged PRs earn a share of the pool", "contributors earn money"
    re.compile(r"\b(?:contributors?|contributions?|merged (?:pull requests?|PRs?)|pull requests?|\bPRs?\b)\s+"
               r"(?:\w+\s+){0,2}?earns?\s+(?:a\s+)?(?:share|money|cash|payment|rewards?)\b", re.I),
    # "bug fixes / patches / PRs are compensated|paid|rewarded"
    re.compile(r"\b(?:bug fix(?:es)?|fix(?:es)?|patch(?:es)?|features?|documentation|docs)\s+"
               r"(?:\w+\s+){0,2}?(?:are|is|get|will be)\s+(?:\w+\s+){0,2}?"
               r"(?:paid|rewarded|compensated|remunerated)\b", re.I),
    # "payments/payouts are made to contributors"
    re.compile(r"\b(?:payments?|payouts?|rewards?)\s+(?:are\s+|is\s+|will be\s+)?(?:made|sent|issued|given)\s+to\s+"
               r"(?:contributors?|authors?|developers?|maintainers?)\b", re.I),
    # "monetary rewards", "cash rewards", "monthly payout"
    re.compile(r"\b(?:monetary|cash|financial)\s+(?:rewards?|compensation|payouts?|incentives?)\b"
               r"|\b(?:monthly|weekly)\s+payouts?\b|\bpaid\s+(?:automatically|monthly|weekly|on merge)\b", re.I),
]

# Sentences where a payment word appears but the project is NOT paying
FALSE_POSITIVE = re.compile(
    r"(paid work|paid to (?:make|contribute|work)|being paid|are paid to|if you(?:'re| are) paid|"
    r"on behalf of|your employer|employer|your company|paying customers?|customers? (?:who )?pay|"
    r"pay(?:ing)? attention|pay it forward|pay respect|pay (?:close|special|particular) |"
    r"paid (?:plan|tier|version|feature|subscription|license)|"
    r"\bnot\b[^.\n]{0,50}\b(?:paid|payment|bount|reward)|\bno\s+(?:payment|pay|bount|reward)|"
    r"\bdon'?t\b[^.\n]{0,60}\bbount|\bwithout\s+(?:payment|pay)\b|"
    r"legal (?:issues|liabilit|responsib)|not (?:automatically|guaranteed)|"
    r"paid adoption|\brewards?\.md\b|\bpaid contribution schemes?\b(?!\s*[\w]+\s+are))",
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
# Only labels that unambiguously mean "money is attached". Bare "paid" and
# "reward" are deliberately excluded: they mean paid-plan features and in-game
# rewards in many repos.
STRONG_LABEL = re.compile(r"bount(?:y|ies)|drips-?wave|stellar wave|💎|💰|\bfunded\b|\bcash\b", re.I)
WEAK_LABEL = re.compile(r"^(?:paid|reward|rewards?)$", re.I)
MONEY = re.compile(r"\$\s?\d[\d,]*(\.\d+)?|\b\d[\d,]*\s?(usd|usdc|dollars)\b", re.I)


def detect_platforms(text):
    """Return [(name, needs_kyc)] for every payout platform named in text."""
    return [(name, kyc) for name, (rx, kyc) in PLATFORMS.items() if rx.search(text or "")]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|\s*[*\u2022]\s+|\s*#+\s+")


def sentences(text):
    """Split markdown-ish text into clean sentences (no links, no code)."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # keep link text only
    text = re.sub(r"<[^>]+>", " ", text)
    out = []
    for part in _SENT_SPLIT.split(text):
        part = " ".join(part.split())
        if 15 <= len(part) <= 400:
            out.append(part)
    return out


def snippet(text, match=None, width=200):
    """Return readable text cut on word boundaries."""
    t = " ".join((text or "").split())
    if len(t) <= width:
        return t
    cut = t[:width].rsplit(" ", 1)[0]
    return cut + "..."


def classify_text(text):
    """Classify README/CONTRIBUTING-style text, one sentence at a time.

    A sentence counts only if it matches a "project pays" pattern and is not a
    known false-positive shape (employer pays, customers pay, negations, idioms).
    Returns dict(tier, reason, snippet, platforms) or None.
    """
    if not text:
        return None
    platforms = detect_platforms(text)

    for sent in sentences(text):
        if FALSE_POSITIVE.search(sent) or DONATION_ONLY.search(sent):
            continue
        if any(rx.search(sent) for rx in PROJECT_PAYS):
            return {"tier": "A", "reason": "project says it pays contributors",
                    "snippet": snippet(sent), "platforms": platforms}

    # A bare dollar amount near contribution words is weaker: it also matches
    # pricing pages, so it is ranked B and never A.
    for sent in sentences(text):
        if FALSE_POSITIVE.search(sent) or DONATION_ONLY.search(sent):
            continue
        if MONEY_NEAR.search(sent):
            return {"tier": "B", "reason": "dollar amount near contribution wording",
                    "snippet": snippet(sent), "platforms": platforms}

    if platforms:
        names = ", ".join(n for n, _ in platforms)
        first = next((sn for sn in sentences(text)
                      if any(PLATFORMS[n][0].search(sn) for n, _ in platforms)), "")
        return {"tier": "B", "reason": f"names payout platform: {names}",
                "snippet": snippet(first), "platforms": platforms}
    return None


def classify_issue(item):
    """Classify a GitHub issue dict from the search API.

    Returns dict(tier, reason, snippet, platforms) or None.
    A bare "paid" or "reward" label is not enough on its own: those labels mean
    paid-plan features or in-game rewards in many repos. They only count when
    backed by a dollar amount or a named payout platform.
    """
    labels = [l["name"] for l in item.get("labels", [])]
    text = f"{item.get('title', '')}\n{item.get('body', '') or ''}"
    label_blob = " | ".join(labels)
    platforms = detect_platforms(f"{text}\n{label_blob}")
    money = MONEY.search(text)

    strong = next((l for l in labels if POINTS_LABEL.search(l) or STRONG_LABEL.search(l)), None)
    if strong:
        return {"tier": "A", "reason": f"label: {strong}", "snippet": "", "platforms": platforms}

    weak = next((l for l in labels if WEAK_LABEL.match(l.strip())), None)
    if weak and (money or platforms):
        why = f"amount: {money.group(0)}" if money else "named payout platform"
        return {"tier": "A", "reason": f"label: {weak} + {why}",
                "snippet": "", "platforms": platforms}

    if money:
        return {"tier": "A", "reason": f"amount: {money.group(0)}",
                "snippet": snippet(text[max(0, money.start() - 40): money.end() + 60]),
                "platforms": platforms}

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
