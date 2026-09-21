import json, os, sys, tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
os.environ.update(TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GH_SCAN_TOKEN="x",
                  WATCHLIST_PATH=os.path.join(TMP, "w.json"), STATE_PATH=os.path.join(TMP, "seen.json"))
json.dump({"repos": ["o/r"], "orgs": [], "lookback_days": 2, "max_comments": 25,
           "skip_labels": ["wontfix"], "hide_states": ["assigned", "has-pr"]},
          open(os.environ["WATCHLIST_PATH"], "w"))

from scanner import discovery, notify, state as state_mod, watchlist, github
import scan

now = datetime.now(timezone.utc)
iso = lambda d: (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
passed = []
def ok(name): passed.append(name); print("  ok:", name)

# ------------------------------------------------------------------ state
p = os.path.join(TMP, "s.json")
s = state_mod.State(p)
s.mark("watchlist", "b/x#2"); s.mark("watchlist", "a/x#1"); s.data["discovery"]["old"] = "2020-01-01"
s.save()
raw = open(p).read()
d = json.loads(raw)
assert "old" not in d["discovery"], "old entries must be pruned"
assert raw.index("a/x#1") < raw.index("b/x#2"), "keys must be sorted for clean diffs"
assert State_ok if (State_ok := state_mod.State(p).seen("watchlist", "a/x#1")) else False
ok("state: sorted keys, pruning, reload")

open(p, "w").write("{not json")
assert state_mod.State(p).data == {"watchlist": {}, "discovery": {}}
ok("state: corrupt file starts empty instead of crashing")

# -------------------------------------------------------------- watchlist
def issue(n, title, days=0.5, **kw):
    d = dict(number=n, title=title, html_url=f"https://github.com/o/r/issues/{n}",
             created_at=iso(days), labels=[], assignees=[], comments=0); d.update(kw); return d
ISSUES = [issue(1, "Untouched"), issue(2, "Assigned", assignees=[{"login": "b"}]),
          issue(3, "Has PR"), issue(4, "Claimed", comments=1), issue(5, "Crowded", comments=40),
          issue(6, "PR row", pull_request={"url": "x"}), issue(7, "Old", days=30),
          issue(8, "Has <script>", labels=[{"name": "bug"}]),
          issue(9, "Wontfix", labels=[{"name": "wontfix"}])]
def fake_get(url, params=None, headers=None):
    if url.endswith("/repos/o/r/issues"): return ISSUES
    if url.endswith("/issues/3/timeline"):
        return [{"event": "cross-referenced", "source": {"issue": {"number": 9, "state": "open", "pull_request": {}}}},
                {"event": "cross-referenced", "source": {"issue": {"number": 8, "state": "closed", "pull_request": {}}}}]
    if "/timeline" in url: return []
    if url.endswith("/issues/4/comments"): return [{"body": "Yes I'm working on it", "user": {"login": "z"}}]
    if "/orgs/big/repos" in url:
        return [{"full_name": "big/a", "archived": False, "fork": False},
                {"full_name": "big/old", "archived": True, "fork": False},
                {"full_name": "big/fork", "archived": False, "fork": True}]
    return []
github.get = fake_get
watchlist.time.sleep = lambda s: None

st = state_mod.State(os.path.join(TMP, "w_state.json"))
alerts, keys = watchlist.collect(st)
assert {a["number"] for a in alerts} == {1, 4, 8}, {a["number"] for a in alerts}
assert {a["state"] for a in alerts} == {"open", "claimed"}
ok("watchlist: hides assigned / has-PR / crowded / PR rows / old / skip-label")
assert not st.seen("watchlist", "o/r#1"), "shown items must NOT be recorded before sending"
assert st.seen("watchlist", "o/r#2") and st.seen("watchlist", "o/r#5"), "hidden items are recorded"
ok("watchlist: shown items not recorded until send succeeds")
msg = watchlist.format_message(alerts)
assert "&lt;script&gt;" in msg and "<script>" not in msg
assert msg.index("o/r#1") < msg.index("o/r#4")
ok("watchlist: HTML escaped, open listed before claimed")

cfg = {"repos": ["o/r", "o/r"], "orgs": ["big"], "org_repo_limit": 30}
assert watchlist.expand_repos(cfg) == ["o/r", "big/a"], watchlist.expand_repos(cfg)
ok("watchlist: org expansion skips archived/forks and dedupes")

# --------------------------------------------------------------- signals
from scanner import signals
POS = [
  "Contributors whose pull requests are merged are paid automatically via GitHub Sponsors.",
  "We reward every merged PR with a monthly payout.",
  "Merged pull requests earn a share of our sponsorship pool.",
  "Bug fixes are compensated based on complexity.",
  "We pay contributors for accepted fixes.",
  "We offer monetary rewards for accepted patches.",
  "Contributors are remunerated for significant merged work.",
  "Payments are made to contributors through GitHub Sponsors.",
  "Every merged PR is eligible for payment from our monthly budget.",
]
NEG = [
  "Buy me a coffee if you like this project.",
  "Please donate to support the project. Become a sponsor today!",
  "This project is licensed under MIT.",
  "Sponsor me on GitHub to support my work.",
  "Fixes issue #123 by earning the trust of the cache layer.",
  "The bug was funded by an upstream change in the parser.",
  "See the issues tab for bugs. Sponsored by Acme Corp.",
  "Users earn points in the game by completing levels.",
  "Contribute to this project by sending a pull request; rewards.md is generated.",
  "All contributions are welcome and appreciated.",
]
for t in POS:
    r = signals.classify_text(t)
    assert r and r["tier"] == "A", f"should be tier A: {t}"
for t in NEG:
    r = signals.classify_text(t)
    assert not (r and r["tier"] == "A"), f"should NOT be tier A: {t}"
ok(f"signals: {len(POS)} payment phrasings -> A, {len(NEG)} non-payment phrasings -> not A")

r = signals.classify_text("Earn $50 for each fixed issue.")
assert r["tier"] == "B", "dollar-only README text must be weaker than an explicit claim"
ok("signals: dollar-only README text is tier B, not A")

r = signals.classify_text("Payments go through https://github.com/sponsors/acme for merged work")
assert ("GitHub Sponsors", False) in r["platforms"]
r = signals.classify_text("Join the Stellar Wave on drips.network")
assert ("Drips", True) in r["platforms"]
assert "KYC" in signals.channel_line(r["platforms"]) and "channel: unknown" == signals.channel_line([])
ok("signals: platforms detected, KYC flagged for Drips, unknown channel handled")

assert signals.classify_funding_file("github: [alice]\n")["tier"] == "C"
assert signals.classify_funding_file("") is None
ok("signals: FUNDING.yml is tier C only")

def mk_issue(labels=(), title="t", body=""):
    return {"title": title, "body": body, "labels": [{"name": l} for l in labels]}
assert signals.classify_issue(mk_issue(["200 points", "Stellar Wave"]))["tier"] == "A"
assert signals.classify_issue(mk_issue(["bounty"]))["tier"] == "A"
assert signals.classify_issue(mk_issue(body="Reward: $150"))["tier"] == "A"
assert signals.classify_issue(mk_issue(body="see https://algora.io/x"))["tier"] == "B"
assert signals.classify_issue(mk_issue(labels=["bug"], body="it crashes")) is None
ok("signals: issue labels/points/amount -> A, platform link -> B, plain bug -> none")

# ------------------------------------------------------------- discovery
def disc(n, title, repo="acme/app", body="", labels=(), comments=0, **kw):
    d = dict(html_url=f"https://github.com/{repo}/issues/{n}", title=title, body=body,
             repository_url=f"https://api.github.com/repos/{repo}", comments=comments,
             labels=[{"name": l} for l in labels], assignees=[], created_at=iso(0.2)); d.update(kw); return d
ISS = {
  "points":   disc(1, "Fix parser", labels=["200 points", "Stellar Wave"]),
  "money":    disc(2, "Fix crash", body="Reward: $150 on merge"),
  "platform": disc(3, "Add cache", body="Funded via https://algora.io/acme"),
  "plain":    disc(4, "Typo in docs"),
  "pr":       disc(5, "x", labels=["bounty"], pull_request={}),
  "assigned": disc(6, "x", labels=["bounty"], assignees=[{"login": "a"}]),
  "crowded":  disc(7, "x", labels=["bounty"], comments=30),
  "meta":     disc(8, "x", repo="me/bounty-watch", labels=["bounty"]),
  "casino":   disc(9, "casino airdrop $500", labels=["bounty"]),
}
def fake_search(url, params=None, headers=None):
    if url.endswith("/search/issues"): return {"items": list(ISS.values())}
    return {"items": []}
github.get = fake_search
discovery.time.sleep = lambda s: None
os.environ["SKIP_FILE_SEARCH"] = "1"
st2 = state_mod.State(os.path.join(TMP, "d_state.json"))
items = discovery.collect(st2)
got = {i["url"].rsplit("/", 1)[1]: i["tier"] for i in items}
assert got == {"1": "A", "2": "A", "3": "B"}, got
ok("discovery: labels/points/amount kept, plain/PR/assigned/crowded/meta/blocklisted dropped")
assert items[-1]["tier"] == "B", "tier A must be listed before B"
ok("discovery: strongest tier listed first")

st2.mark("discovery", ISS["points"]["html_url"])
assert "1" not in {i["url"].rsplit("/", 1)[1] for i in discovery.collect(st2)}
ok("discovery: seen issues are not repeated, dedupe is by issue URL")

msg = discovery.format_message(items)
assert "why:" in msg and "channel:" in msg and "Hints, not proof" in msg
assert "KYC" in msg, "Drips/Stellar Wave issue should carry the KYC note"
ok("discovery: alert shows reason, payout channel and KYC note")

# ---- file source
import base64
README = "Contributors whose pull requests are merged are paid automatically via GitHub Sponsors."
def fake_files(url, params=None, headers=None):
    if url.endswith("/search/code"):
        return {"items": [{"repository": {"full_name": "new/proj"}, "path": "CONTRIBUTING.md"},
                          {"repository": {"full_name": "old/dead"}, "path": "README.md"},
                          {"repository": {"full_name": "me/bounty-farm"}, "path": "README.md"},
                          {"repository": {"full_name": "tiny/none"}, "path": "README.md"}]}
    if url.endswith("/repos/new/proj"):
        return dict(archived=False, fork=False, stargazers_count=12, html_url="https://github.com/new/proj",
                    pushed_at=iso(1), created_at=iso(20), description="A project")
    if url.endswith("/repos/old/dead"):
        return dict(archived=False, fork=False, stargazers_count=90, html_url="x", pushed_at=iso(400),
                    created_at=iso(800), description="")
    if url.endswith("/repos/tiny/none"):
        return dict(archived=False, fork=False, stargazers_count=50, html_url="https://github.com/tiny/none",
                    pushed_at=iso(1), created_at=iso(200), description="")
    if url.endswith("/contents/CONTRIBUTING.md"):
        return {"content": base64.b64encode(README.encode()).decode()}
    if url.endswith("/contents/README.md"):
        return {"content": base64.b64encode(b"Just a normal readme about building software.").decode()}
    return None
github.get = fake_files
st3 = state_mod.State(os.path.join(TMP, "f_state.json"))
files = discovery.file_candidates(st3)
assert [f["repo"] for f in files] == ["new/proj"], [f["repo"] for f in files]
f = files[0]
assert f["tier"] == "A" and ("GitHub Sponsors", False) in f["platforms"] and f["age_days"] == 20
ok("discovery: file search keeps a real claim, drops idle/meta/no-claim repos")
m = discovery.format_message(files)
assert "🆕" in m and "GitHub Sponsors" in m and "CONTRIBUTING.md" in m
ok("discovery: new repos are flagged 🆕 and show the source file")

# ---------------------------------------------------------------- notify
parts = notify.split_message("\n\n".join(["x" * 900] * 10))
assert all(len(p) <= notify.TG_LIMIT for p in parts) and len(parts) > 1
ok("notify: long messages split under Telegram's limit")

# -------------------------------------------- end to end: retry on failure
def run_with(delivered):
    github.get = fake_get
    st = state_mod.State(os.path.join(TMP, f"e2e_{delivered}.json"))
    sent = []
    notify.notify = lambda text, title="": (sent.append(text), delivered)[1]
    scan.notify = notify
    scan.run_watchlist(st)
    return st, sent
st_ok, sent = run_with(True)
assert len(sent) == 1 and st_ok.seen("watchlist", "o/r#1")
ok("e2e: successful send records shown issues as seen")
st_bad, sent = run_with(False)
assert len(sent) == 1 and not st_bad.seen("watchlist", "o/r#1"), "failed send must not mark seen"
ok("e2e: FAILED send leaves issues unseen so the next run retries")

print(f"\nALL {len(passed)} CHECK GROUPS PASSED")
