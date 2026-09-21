"""Seen-item state stored as readable JSON.

Keys are sorted on save so git diffs show only real additions, and entries
older than PRUNE_DAYS are dropped so the file does not grow forever.
"""

import json
import os
from datetime import datetime, timedelta, timezone

PRUNE_DAYS = 60


def _now():
    return datetime.now(timezone.utc)


class State:
    def __init__(self, path):
        self.path = path
        self.data = {"watchlist": {}, "discovery": {}}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in self.data:
                    if isinstance(loaded.get(k), dict):
                        self.data[k] = loaded[k]
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] could not read {path}: {e}. Starting empty.")

    def seen(self, bucket, key):
        return key in self.data[bucket]

    def mark(self, bucket, key):
        self.data[bucket][key] = _now().strftime("%Y-%m-%d")

    def prune(self):
        cutoff = (_now() - timedelta(days=PRUNE_DAYS)).strftime("%Y-%m-%d")
        for bucket in self.data.values():
            for k in [k for k, v in bucket.items() if v < cutoff]:
                del bucket[k]

    def save(self):
        self.prune()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
