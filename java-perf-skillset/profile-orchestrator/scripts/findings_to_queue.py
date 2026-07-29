#!/usr/bin/env python3
"""Convert JSONL findings into the existing Phase-3 queue format.

Part of the `profile-orchestrator` Claude Code skill — the integration
bridge between the new unified findings contract
(.profile-run/findings.jsonl) and the battle-tested fix loop of the
`profile` skill (queue_next.py / queue_update.py / checkpoint_save.py),
which stays unchanged and keeps consuming .profile-run/queue.json
(schemaVersion 1, see profile/references/queue-schema.md).

Usage:
    findings_to_queue.py --project-root DIR \
        [--findings .profile-run/findings.jsonl] \
        [--output .profile-run/queue.json] \
        [--merge-from .profile-run/queue.json]

Selection rules (the prioritization the orchestrator hands to apply):
- findings with confidence < 0.70 are NOT queued (below apply threshold);
- duplicates by (category, location.file, location.line, suggested_fix)
  are collapsed keeping the highest confidence;
- findings overlapping by file:line within 3 lines are QG-merged into the
  strongest one (mergedFrom records the rest), same as legacy build_queue;
- at most 10 queued findings per pack (category), highest priority first;
- sorted by severity, then confidence descending.

--merge-from carries over status/attempts/commitSha of already-processed
queue items on resume, exactly like legacy build_queue.py.

Python 3.10+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MIN_CONFIDENCE = 0.7
MAX_PER_PACK = 10
LOCATION_WINDOW_LINES = 3

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}

# Same deliberate track split as legacy build_queue.py: leak-shaped
# detectors verify via profiler (effect only shows under sustained mixed
# load), everything else via a single-scenario measurement.
PROFILER_TRACK_DETECTORS = {
    "find-resource-management-issues",
    "find-unbounded-cache-or-queue",
    "profiler-find-problem",
}


def norm_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        return {"high": 0.9, "medium": 0.75, "low": 0.4}.get(value.lower(), 0.0)
    return 0.0


def confidence_word(score: float) -> str:
    """Map numeric confidence to the high/medium words the legacy queue
    schema and apply-recommendations understand."""
    return "high" if score >= 0.85 else "medium"


def load_findings(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not path.is_file():
        return findings
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("id"):
            findings.append(obj)
    return findings


def location_of(f: dict[str, Any]) -> tuple[str, int | None]:
    loc = f.get("location")
    if isinstance(loc, dict):
        file = str(loc.get("file", ""))
        line = loc.get("line")
        return file, int(line) if isinstance(line, int) else None
    return "", None


def to_queue_item(f: dict[str, Any]) -> dict[str, Any]:
    score = norm_confidence(f.get("confidence"))
    file, line = location_of(f)
    detector = str(f.get("detector", "")) or str(f.get("category", "unknown"))
    verify = f.get("verify") if isinstance(f.get("verify"), dict) else {}
    metrics = verify.get("metrics", [])
    metrics_s = ", ".join(map(str, metrics)) if isinstance(metrics, list) else str(metrics)
    evidence = f.get("evidence", [])
    evidence_s = ("; ".join(map(str, evidence))
                  if isinstance(evidence, list) else str(evidence))
    track = "profiler" if detector in PROFILER_TRACK_DETECTORS else "measurement"
    label = str(f.get("type") or f.get("category") or "finding")
    return {
        "queueId": f"findings.jsonl::{f['id']}",
        "reportFile": ".profile-run/findings.jsonl",
        "producerSkill": detector,
        "verificationTrack": track,
        "status": "pending",
        "attempts": [],
        "findingId": str(f["id"]),
        "label": label,
        "category": str(f.get("category", "unknown")),
        "severity": str(f.get("severity", "unknown")).lower(),
        "confidence": confidence_word(score),
        "confidenceScore": score,
        "symptom": evidence_s,
        "location": f"`{file}:{line if line is not None else '?'}`",
        "recommendedFix": str(f.get("suggested_fix", "")),
        "verification": (f"{verify.get('scenario', '')}: {metrics_s}".strip(": ")
                         or "повторный прогон детектора"),
        "evidence": evidence_s,
        "finding": f,  # full contract object, passed inline to apply-recommendations
    }


def priority_key(item: dict[str, Any]) -> tuple:
    return (
        -SEVERITY_RANK.get(item["severity"], 0),
        -item["confidenceScore"],
        item["findingId"],
    )


def dedup_exact(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple, dict[str, Any]] = {}
    for f in findings:
        file, line = location_of(f)
        key = (str(f.get("category", "")), file, str(line),
               str(f.get("suggested_fix", "")))
        cur = best.get(key)
        if cur is None or norm_confidence(f.get("confidence")) > norm_confidence(
                cur.get("confidence")):
            best[key] = f
    return list(best.values())


def qg_merge(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse queue items pointing at the same file within
    LOCATION_WINDOW_LINES lines (same defect seen by several detectors)."""
    def loc(item: dict[str, Any]) -> tuple[str, int | None]:
        return location_of(item["finding"])

    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        fi, li = loc(items[i])
        if not fi or li is None:
            continue
        for j in range(i + 1, n):
            fj, lj = loc(items[j])
            if fi == fj and lj is not None and abs(li - lj) <= LOCATION_WINDOW_LINES:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    merged: list[dict[str, Any]] = []
    for indices in groups.values():
        if len(indices) == 1:
            merged.append(items[indices[0]])
            continue
        indices.sort(key=lambda k: priority_key(items[k]))
        primary = dict(items[indices[0]])
        primary["mergedFrom"] = [
            {"queueId": items[k]["queueId"],
             "producerSkill": items[k]["producerSkill"],
             "label": items[k]["label"]}
            for k in indices[1:]
        ]
        merged.append(primary)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--findings", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--merge-from", type=Path, default=None,
                    help="Prior queue.json (resume): carry over status/attempts/"
                         "commitSha for matching queueIds")
    ap.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE)
    ap.add_argument("--max-per-pack", type=int, default=MAX_PER_PACK)
    args = ap.parse_args()

    root = args.project_root.resolve()
    if not root.is_dir():
        print(f"error: --project-root {root} is not a directory", file=sys.stderr)
        return 2
    findings_path = args.findings or (root / ".profile-run" / "findings.jsonl")
    if not findings_path.is_absolute():
        findings_path = root / findings_path
    out = args.output or (root / ".profile-run" / "queue.json")
    if not out.is_absolute():
        out = root / out

    prior_by_id: dict[str, dict[str, Any]] = {}
    merge_from = args.merge_from
    if merge_from and not merge_from.is_absolute():
        merge_from = root / merge_from
    if merge_from and merge_from.is_file():
        try:
            prior = json.loads(merge_from.read_text(encoding="utf-8"))
            for it in prior.get("items", []):
                if it.get("status") not in ("pending", "in_progress"):
                    prior_by_id[it["queueId"]] = it
        except (json.JSONDecodeError, OSError):
            pass

    findings = load_findings(findings_path)
    eligible = [f for f in findings
                if norm_confidence(f.get("confidence")) >= args.min_confidence
                and str(f.get("suggested_fix", "")).strip()]
    below = len(findings) - len(eligible)

    items = [to_queue_item(f) for f in dedup_exact(eligible)]
    items = qg_merge(items)
    items.sort(key=priority_key)

    # cap per pack (category), keeping the highest-priority findings
    per_pack: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        pack = item["category"]
        if per_pack.get(pack, 0) >= args.max_per_pack:
            dropped += 1
            continue
        per_pack[pack] = per_pack.get(pack, 0) + 1
        capped.append(item)
    items = capped

    final_items: list[dict[str, Any]] = []
    for item in items:
        carried = prior_by_id.pop(item["queueId"], None)
        if carried is not None:
            item["status"] = carried["status"]
            item["attempts"] = carried.get("attempts", [])
            if "commitSha" in carried:
                item["commitSha"] = carried["commitSha"]
        final_items.append(item)
    if prior_by_id:
        print(f"carrying over {len(prior_by_id)} finding(s) no longer present "
              f"in current findings.jsonl: {sorted(prior_by_id)}", file=sys.stderr)
        final_items.extend(prior_by_id.values())

    payload = {
        "schemaVersion": 1,
        "source": str(findings_path),
        "reportsSeen": [".profile-run/findings.jsonl"],
        "totalFindings": len(final_items),
        "items": final_items,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"queued {len(final_items)} findings "
          f"({below} below confidence {args.min_confidence:g} or without fix, "
          f"{dropped} over per-pack cap {args.max_per_pack})", file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
