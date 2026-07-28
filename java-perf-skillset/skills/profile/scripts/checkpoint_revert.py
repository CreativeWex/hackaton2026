#!/usr/bin/env python3
"""Revert one or more /profile checkpoints, most-recent-first.

Part of the `profile` Claude Code skill. Callable standalone, independent of
an active /profile run — e.g. the user changed their mind about the last
fix after the fact.

Reverse-applies (`patch -R`) the unified diffs saved by checkpoint_save.py,
strictly from the newest checkpoint backwards. Stops at the first checkpoint
that fails to reverse-apply cleanly (a later, still-wanted fix touched the
same lines) rather than guessing — everything reverted before the conflict
stays reverted; the conflicting checkpoint and anything older than it are
left untouched.

Usage:
    checkpoint_revert.py --project-root DIR [--checkpoints-dir .profile-run/checkpoints]
        (--last N | --queue-id ID)
        [--dry-run]

--last N        revert the N most recent checkpoints (most recent first)
--queue-id ID   revert exactly one checkpoint by queueId (still processes
                any newer checkpoints' conflict risk is not auto-resolved —
                if newer checkpoints exist and touch the same files, the
                revert may fail with a conflict; that's the correct,
                safe outcome, not a bug)
--dry-run       use `patch --dry-run` — report what would happen, change nothing

Requires the `patch` binary (GNU patch) on PATH. Requires Python 3.10+.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_checkpoints(checkpoints_dir: Path) -> list[dict[str, Any]]:
    out = []
    if not checkpoints_dir.is_dir():
        return out
    for d in sorted(checkpoints_dir.iterdir()):
        meta_path = d / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["_dir"] = d
            out.append(meta)
    out.sort(key=lambda m: m["seq"])
    return out


def revert_one(checkpoint: dict[str, Any], project_root: Path, patch_bin: str,
                dry_run: bool) -> tuple[bool, str]:
    """Returns (success, message)."""
    patches_dir = checkpoint["_dir"] / "patches"
    if not checkpoint.get("files"):
        return True, f"checkpoint {checkpoint['seq']} ({checkpoint['queueId']}): no file changes recorded, nothing to revert"

    for f in checkpoint["files"]:
        patch_file = patches_dir / f["patchFile"]
        target = project_root / f["relpath"]
        cmd = [patch_bin, "-R", "-p1", "--batch", "--forward",
               f"--directory={project_root}", f"--input={patch_file}"]
        if dry_run:
            cmd.insert(1, "--dry-run")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        combined = (proc.stdout or "") + (proc.stderr or "")

        # `patch` leaves .orig/.rej debris next to the target file on a failed
        # or fuzzy match, dry-run or not — clean up either way so a failed
        # revert attempt never leaves stray files in the working tree; our own
        # message below carries the diagnostic that .rej would have held.
        for suffix in (".orig", ".rej"):
            stray = Path(str(target) + suffix)
            if stray.is_file():
                stray.unlink()

        if proc.returncode != 0 or "FAILED" in combined:
            return False, (
                f"checkpoint {checkpoint['seq']} ({checkpoint['queueId']}): "
                f"CONFLICT reverting {f['relpath']} — a later change likely "
                f"touched the same lines. Nothing from this checkpoint onward "
                f"(older) was touched.\n{combined.strip()}"
            )
    return True, f"checkpoint {checkpoint['seq']} ({checkpoint['queueId']}): reverted cleanly"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--checkpoints-dir", type=Path, default=None)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--last", type=int)
    group.add_argument("--queue-id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--patch-bin", default="patch")
    args = ap.parse_args()

    checkpoints_dir = args.checkpoints_dir or (args.project_root / ".profile-run" / "checkpoints")
    checkpoints = load_checkpoints(checkpoints_dir)
    if not checkpoints:
        print(f"No checkpoints found under {checkpoints_dir}", file=sys.stderr)
        return 1

    checkpoints_desc = list(reversed(checkpoints))  # most recent first

    if args.queue_id:
        targets = [c for c in checkpoints_desc if c["queueId"] == args.queue_id]
        if not targets:
            print(f"No checkpoint with queueId={args.queue_id}", file=sys.stderr)
            return 2
    else:
        if args.last <= 0:
            print("--last must be a positive integer", file=sys.stderr)
            return 2
        targets = checkpoints_desc[: args.last]

    reverted: list[int] = []
    for checkpoint in targets:
        ok, message = revert_one(checkpoint, args.project_root, args.patch_bin, args.dry_run)
        print(message)
        if not ok:
            print(f"Stopped. Reverted {len(reverted)}/{len(targets)} requested checkpoint(s) "
                  f"before hitting this conflict.", file=sys.stderr)
            return 3
        reverted.append(checkpoint["seq"])

    verb = "Would revert" if args.dry_run else "Reverted"
    print(f"{verb} {len(reverted)} checkpoint(s): {reverted}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
