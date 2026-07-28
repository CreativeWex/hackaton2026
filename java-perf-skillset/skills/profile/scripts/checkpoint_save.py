#!/usr/bin/env python3
"""Save one reversible checkpoint for an accepted /profile fix.

Part of the `profile` Claude Code skill.

Diffs a pre-fix snapshot directory against the live project tree and stores
one git-style unified patch per changed file under
.profile-run/checkpoints/<seq>-<queueId>/patches/. This is the revert
mechanism used when no git repository is available (and an extra safety net
even when one is) — see checkpoint_revert.py.

Usage:
    checkpoint_save.py --project-root DIR --before-dir SNAPSHOT_DIR \
        --queue-id ID --seq N --output-dir .profile-run/checkpoints \
        [--label TEXT]

SNAPSHOT_DIR must mirror the project tree structure for exactly the files
that were snapshotted before the fix was applied (relative paths match, e.g.
SNAPSHOT_DIR/src/main/java/Foo.java <-> PROJECT_ROOT/src/main/java/Foo.java).
The orchestrator decides what to snapshot — normally everything listed in
the finding's Location plus pom.xml/build.gradle* defensively.

Known limitation: a file the fix *creates from scratch* outside that
snapshotted set (not just edits an existing one) is invisible to this
mechanism — there is nothing to diff it against, and reverting later will
not delete it. This is intentionally left as a stated gap rather than
papered over with a full-tree scan on every fix; findings almost always
target already-flagged existing code, so this is a narrow edge case.

Requires the `diff` binary (GNU diffutils) on PATH — no other external
dependency. Requires Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def make_patch(before: Path, after: Path, relpath: str, diff_bin: str) -> str | None:
    """Returns the unified diff text, or None if the two are identical."""
    before_arg = str(before) if before.is_file() else os.devnull
    after_arg = str(after) if after.is_file() else os.devnull
    if before_arg == os.devnull and after_arg == os.devnull:
        return None

    proc = subprocess.run(
        [
            diff_bin, "-u",
            "--label", f"a/{relpath}",
            "--label", f"b/{relpath}",
            before_arg, after_arg,
        ],
        capture_output=True, text=True,
    )
    if proc.returncode == 2:
        raise RuntimeError(f"diff failed on {relpath}: {proc.stderr.strip()}")
    if proc.returncode == 0:
        return None  # identical, nothing to record
    return proc.stdout


def safe_filename(relpath: str) -> str:
    return relpath.replace("/", "__").replace("\\", "__") + ".patch"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--before-dir", required=True, type=Path)
    ap.add_argument("--queue-id", required=True)
    ap.add_argument("--seq", required=True, type=int)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--diff-bin", default="diff")
    args = ap.parse_args()

    if not args.before_dir.is_dir():
        print(f"ERROR: --before-dir not found: {args.before_dir}", file=sys.stderr)
        return 2

    safe_id = args.queue_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    checkpoint_dir = args.output_dir / f"{args.seq:04d}-{safe_id}"
    patches_dir = checkpoint_dir / "patches"

    relpaths = sorted(
        str(p.relative_to(args.before_dir)).replace("\\", "/")
        for p in args.before_dir.rglob("*") if p.is_file()
    )

    files_meta: list[dict[str, Any]] = []
    for relpath in relpaths:
        before = args.before_dir / relpath
        after = args.project_root / relpath
        patch_text = make_patch(before, after, relpath, args.diff_bin)
        if patch_text is None:
            continue
        patch_name = safe_filename(relpath)
        files_meta.append({"relpath": relpath, "patchFile": patch_name})
        patches_dir.mkdir(parents=True, exist_ok=True)
        (patches_dir / patch_name).write_text(patch_text, encoding="utf-8")

    meta = {
        "schemaVersion": 1,
        "seq": args.seq,
        "queueId": args.queue_id,
        "label": args.label,
        "files": files_meta,
    }
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(str(checkpoint_dir))
    print(f"checkpoint {args.seq}: {len(files_meta)} file(s) changed for {args.queue_id}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
