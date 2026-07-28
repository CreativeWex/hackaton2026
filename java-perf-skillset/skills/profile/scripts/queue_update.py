#!/usr/bin/env python3
"""Update one item in the /profile work queue in place.

Part of the `profile` Claude Code skill.

Usage:
    queue_update.py --queue .profile-run/queue.json --queue-id ID \
        --status STATUS [--attempt '<json object>'] [--commit-sha SHA]

--status one of: pending | in_progress | committed | skipped-resolved |
                 skipped-blocked | skipped-3-attempts | skipped-infra
--attempt appends one attempt record (arbitrary JSON object, typically
    {"attemptNumber":1,"diff":"...","verdict":"WORSE",
     "metric":"elapsed_ms","deltaPercent":15.2,"note":"..."})
--commit-sha records the git commit that landed this finding, if any.

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VALID_STATUSES = {
    "pending", "in_progress", "committed",
    "skipped-resolved", "skipped-blocked", "skipped-3-attempts", "skipped-infra",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", required=True, type=Path)
    ap.add_argument("--queue-id", required=True)
    ap.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    ap.add_argument("--attempt", default=None, help="JSON object to append to attempts[]")
    ap.add_argument("--commit-sha", default=None)
    args = ap.parse_args()

    data = json.loads(args.queue.read_text(encoding="utf-8"))
    for item in data.get("items", []):
        if item["queueId"] == args.queue_id:
            item["status"] = args.status
            if args.attempt:
                item.setdefault("attempts", []).append(json.loads(args.attempt))
            if args.commit_sha:
                item["commitSha"] = args.commit_sha
            args.queue.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(str(args.queue))
            return 0

    print(f"ERROR: queueId not found: {args.queue_id}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
