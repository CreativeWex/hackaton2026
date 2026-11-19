#!/usr/bin/env python3
"""Print the next pending item from the /profile work queue.

Part of the `profile` Claude Code skill.

Usage:
    queue_next.py --queue .profile-run/queue.json

Prints the next item with status "pending" (queue.json is already sorted by
priority by build_queue.py) as JSON to stdout, or {"done": true} if none
remain. Does not mutate the queue — use queue_update.py to claim/update it.

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", required=True, type=Path)
    args = ap.parse_args()

    data = json.loads(args.queue.read_text(encoding="utf-8"))
    for item in data.get("items", []):
        if item.get("status") == "pending":
            print(json.dumps(item, indent=2, ensure_ascii=False))
            return 0

    print(json.dumps({"done": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
