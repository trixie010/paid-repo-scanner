"""Entry point. MODE=watchlist | discovery | all"""

import os
import sys

from scanner import discovery, notify, state as state_mod, watchlist

MODE = os.environ.get("MODE", "all").lower()
STATE_PATH = os.environ.get("STATE_PATH", "data/seen.json")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def run_watchlist(state):
    if not os.path.exists(watchlist.WATCHLIST_PATH):
        print("No watchlist.json, skipping watchlist.")
        return
    alerts, keys = watchlist.collect(state, dry_run=DRY_RUN)
    print(f"Watchlist: {len(alerts)} new available issues")
    if not alerts:
        return
    if notify.notify(watchlist.format_message(alerts), "Watchlist: new issues"):
        for k in keys:
            state.mark("watchlist", k)   # only after a successful send
    else:
        print("[warn] not delivered, will retry next run")


def run_discovery(state):
    items = discovery.collect(state)
    print(f"Discovery: {len(items)} candidate issues")
    if not items:
        return
    shown = items[: discovery.MAX_RESULTS]
    if notify.notify(discovery.format_message(items), "Discovery: possible paid work"):
        for it in items:                  # overflow is recorded too, not re-sent
            state.mark("discovery", it["key"])
    else:
        print("[warn] not delivered, will retry next run")


def main():
    if not DRY_RUN and not (notify.TG_TOKEN and notify.TG_CHAT_ID):
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or DRY_RUN=1).")
    state = state_mod.State(STATE_PATH)
    if MODE in ("watchlist", "all"):
        run_watchlist(state)
    if MODE in ("discovery", "all"):
        run_discovery(state)
    if not DRY_RUN:
        state.save()


if __name__ == "__main__":
    main()
