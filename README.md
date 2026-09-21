# paid-repo-scanner

Sends Telegram alerts for two things, both run by GitHub Actions:

1. **Watchlist** (every ~10 minutes): new open issues in repos you choose
   (default: tscircuit). Issues that are already taken are hidden, so an alert
   means there is still something you can grab.
2. **Discovery** (weekly, Mondays): issues and repo files elsewhere on GitHub
   that suggest paid work, ranked by how direct the evidence is.

## Watchlist

Edit `watchlist.json`:

| Key | Meaning |
|---|---|
| `repos` | `owner/repo` list to watch |
| `orgs` | Watch every active repo in these orgs, e.g. `["tscircuit"]` (see below) |
| `org_repo_limit` | Max repos per org, most recently pushed first (default 30) |
| `lookback_days` | Only issues created in this window (default 2) |
| `max_comments` | Skip threads with more comments than this (default 25) |
| `skip_labels` | Skip issues with these labels |
| `hide_states` | Hide these: `assigned`, `has-pr`. Set to `[]` to see everything |

Every alert is checked for signs it is taken:

| Icon | Meaning | Shown? |
|---|---|---|
| 🟢 | Untouched: no assignee, no open PR, no claim comment | yes |
| 🟡 | Someone commented that they are on it | yes |
| 🟠 | Assigned | hidden |
| 🔴 | An open PR already references it | hidden |

The claim-comment check is a text match ("I'll take this", "I'm working on
it"), so it can miss unusual wording. Read the issue before you start.

No keyword filter is applied to the watchlist. Everything in your watched
repos is shown.

**Watching a whole org:** tscircuit has 200+ repos. Adding `"orgs": ["tscircuit"]`
covers the 30 most recently pushed. Each repo costs API calls every run, so
with 10-minute runs, stay under about 30 repos. Authenticated requests get
5,000 per hour, and each run uses roughly (repos + a few) calls.

## Discovery

Runs weekly (Mondays). Looks for paid work **anywhere on GitHub**, using two
sources merged into one ranked list.

**Issues** created in the last few days that have a bounty, reward, `paid` or
points label (like `200 points`), a program label (`drips-wave`), a dollar
amount, or a named payout platform.

**Files**: `CONTRIBUTING.md` and `README.md` text that links merged work to
payment, for example "contributors are paid via GitHub Sponsors". Code search
finds candidates, then the scanner reads the actual file and checks the wording.

Each result shows a tier, why it matched, the matching sentence, and the payout
channel:

| Tier | Meaning |
|---|---|
| A | A direct claim ("we pay contributors for merged PRs") or money/points on an issue |
| B | A payout platform is named, or a dollar amount sits near contribution wording |
| C | A `FUNDING.yml` only. Accepts donations, not proof of payouts |

Payout platforms recognised: GitHub Sponsors, Drips, Algora, Opire, Polar,
Gitcoin, Bountysource, Open Collective, IssueHunt. Drips is flagged
"ID/KYC likely needed", because Drips Wave asks contributors to verify identity
before withdrawing. Check that before spending time on any program.

**Skipped:** pull requests, assigned issues, crowded threads, repos named like
bounty trackers, archived/forked/idle repos, and a short off-topic blocklist
(casino, airdrop, referral, article writing). Edit `BLOCKLIST` in
`scanner/discovery.py`. It is a plain substring match, so remove a word if it
blocks something real.

**What it cannot do:** a repo saying it pays contributors is a claim, not proof.
Ask whether anyone has actually been paid. The wording patterns are fuzzy: they
will miss unusual phrasing and occasionally match a sentence that means
something else. Tell me what slips through and the patterns can be tuned.

**Code search is strict.** GitHub's code search is limited to about 10
requests a minute, only indexes some files, and needs authentication. The scan
waits between queries and checks at most 25 repos per run, so results are
partial. Set `SKIP_FILE_SEARCH=1` to run the issue source only.

## Setup

### 1. Telegram bot
1. Message **@BotFather**, send `/newbot`, save the token.
2. Send any message to your bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the number at
   `"chat":{"id": ...}`. That is your chat ID.

### 2. GitHub token
Settings, Developer settings, Personal access tokens, **Fine-grained tokens**,
Generate new token. Set **Public repositories (read-only)** and leave every
permission unset. Copy it immediately, it is shown once.

### 3. Repo secrets
Settings, Secrets and variables, Actions, New repository secret:

| Name | Value |
|---|---|
| `GH_SCAN_TOKEN` | your GitHub token |
| `TELEGRAM_BOT_TOKEN` | token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat ID |

**This repo is public. Never put a token in any file.** Secrets live only in
the Actions settings. If one leaks, revoke it (`/revoke` in BotFather, or delete
the GitHub token).

### 4. Workflow permissions
Settings, Actions, General, Workflow permissions: **Read and write**. Without
this the job cannot save `data/seen.json` and you would get repeat alerts.

### 5. Run it
Actions tab, **scan**, **Run workflow**, choose `watchlist`, `discovery` or
`all`. After that it runs on its own.

## About the 10-minute schedule

The cron runs at minutes 3, 13, 23, 33, 43 and 53. **GitHub does not guarantee
scheduled runs on time.** Delays of several minutes are normal, and under load
runs can be skipped or arrive much later, so expect "about every 10 to 30
minutes", not exact 10. Off-minutes help because `:00` is the busiest.

If you need tighter timing, use a free external scheduler (for example
cron-job.org) to call the `workflow_dispatch` API. That needs a token allowed
to trigger workflows.

## Public repo notes

- Actions minutes are free and unlimited for public repos.
- `data/seen.json` is public. It lists which issue keys you have been alerted
  about, nothing more.
- GitHub **disables scheduled workflows after 60 days with no repo activity**.
  State commits usually keep it alive, but after a quiet stretch check the
  Actions tab and re-enable it if needed.
- Leave the optional backup channel off (see below), or your alerts become
  public issues.

## Optional backup channel

Set a repo **variable** (not a secret) `NOTIFY_GH_ISSUE` to `1` and each alert
also opens an issue in this repo. On a public repo those are visible to
everyone, so this is off by default.

## Local testing

```bash
pip install -r requirements.txt
export GH_SCAN_TOKEN=github_pat_...
DRY_RUN=1 MODE=watchlist python scan.py    # prints, sends nothing, records nothing
python tests/test_all.py                   # offline tests with mocked GitHub
```

## Limits

- Search returns at most 1,000 results per query and only what GitHub indexes.
- Discovery finds candidates, not confirmed payers. Many programs also need ID verification that not every contributor can pass.
- It cannot tell whether a bounty is still funded or whether payouts happen.
- Monthly-stipend programs (like tscircuit's sponsorship) are rarely tagged, so
  the watchlist is how you follow them, not discovery.

## State file

`data/seen.json` holds seen keys with dates. Keys are sorted so commits show
only real additions, and entries older than 60 days are pruned.
