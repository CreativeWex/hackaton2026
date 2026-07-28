#!/usr/bin/env python3
"""Parse every *_report.md at project root into a single work queue.

Part of the `profile` Claude Code skill (the /profile orchestrator).

Reads all producer-skill reports (profiler_report.md from
profiler-find-problem, and the 22 find-*_report.md files), extracts findings
with confidence high/medium (low/unknown carry no actionable recommendation
by design of those skills — nothing to queue), and writes one ordered
queue.json that the orchestrator works through.

Usage:
    build_queue.py --project-root DIR --output .profile-run/queue.json

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# report filename -> (producer skill name, verification track)
# verification track decides which tool /profile runs after a fix:
#   "measurement" -> java-performance-measurement incremental
#   "profiler"    -> profiler incremental
# profiler-find-problem findings are verified via profiler; find-* (static
# code analysis) findings via java-performance-measurement, regardless of
# what the finding's own Verification text says — a deliberate
# simplification, not a parsing fallback. Exception: leak-shaped categories
# (unbounded caches/queues, resource leaks) go to the profiler track — their
# effect only shows under sustained mixed load, a single-scenario measurement
# would report SAME and confirm nothing. Trade-off: a latency regression such
# a fix introduces is not seen per-fix, only cumulatively by the Phase 4
# measurement `final` run.
REPORT_MAP: dict[str, tuple[str, str]] = {
    "profiler_report.md": ("profiler-find-problem", "profiler"),
    "redundant_computation_report.md": ("find-redundant-computation", "measurement"),
    "algorithm_inefficiency_report.md": ("find-algorithm-inefficiency", "measurement"),
    "inefficient_api_usage_report.md": ("find-inefficient-api-usage", "measurement"),
    "data_layout_report.md": ("find-data-layout-waste", "measurement"),
    "redundant_checks_report.md": ("find-redundant-checks", "measurement"),
    "query_issues_report.md": ("find-query-issues", "measurement"),
    "missing_batching_report.md": ("find-missing-batching", "measurement"),
    "unbounded_data_loading_report.md": ("find-unbounded-data-loading", "measurement"),
    "resource_management_report.md": ("find-resource-management-issues", "profiler"),
    "transaction_locking_report.md": ("find-transaction-locking-issues", "measurement"),
    "regex_issues_report.md": ("find-regex-issues", "measurement"),
    "missing_caching_report.md": ("find-missing-caching", "measurement"),
    "over_fetching_api_report.md": ("find-over-fetching-api", "measurement"),
    "concurrency_issues_report.md": ("find-concurrency-issues", "measurement"),
    "orm_fetch_strategy_report.md": ("find-orm-fetch-strategy-issues", "measurement"),
    "gc_pressure_report.md": ("find-gc-pressure", "measurement"),
    "exceptions_control_flow_report.md": ("find-exceptions-as-control-flow", "measurement"),
    "logging_overhead_report.md": ("find-logging-overhead", "measurement"),
    "reflection_hot_path_report.md": ("find-reflection-in-hot-path", "measurement"),
    "cache_locality_report.md": ("find-cache-locality-issues", "measurement"),
    "unbounded_cache_or_queue_report.md": ("find-unbounded-cache-or-queue", "profiler"),
    "dead_code_report.md": ("find-dead-code", "measurement"),
}

HEADER_RE = re.compile(
    r"^##\s+(?P<id>\S+)\s+—\s+(?P<label>.*?)\s*"
    r"\(severity:\s*(?P<severity>\w+)\s*,\s*confidence:\s*(?P<confidence>\w+)\)\s*$"
)
FIELD_RE = re.compile(
    r"\*\*(?P<name>[A-Za-z /()'-]+):\*\*\s*(?P<value>.*?)(?=\n\*\*[A-Za-z /()'-]+:\*\*|\n---|\Z)",
    re.DOTALL,
)

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
CONFIDENCE_RANK = {"high": 2, "medium": 1}

# QG-merge: findings whose Location overlaps in the same file within this many
# lines are treated as the same underlying defect seen by multiple find-*
# skills (classic case: one N+1-shaped loop flagged as query-issues, as
# missing-batching, and as inefficient-api-usage all at once) and collapsed
# into one queue item before fixing, instead of applying — and separately
# re-verifying — three overlapping edits to the same code.
LOCATION_WINDOW_LINES = 3
LOCATION_RE = re.compile(r"`([^`]+\.java):(\d+)`")


def parse_report(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    # Split into finding blocks on H2 headers.
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    findings: list[dict[str, Any]] = []
    for block in blocks:
        header_line = block.splitlines()[0]
        m = HEADER_RE.match(header_line.strip())
        if not m:
            continue
        severity = m.group("severity").lower()
        confidence = m.group("confidence").lower()
        if confidence not in ("high", "medium"):
            continue  # low/unknown carry no actionable recommendation by design

        fields: dict[str, str] = {}
        for fm in FIELD_RE.finditer(block):
            name = fm.group("name").strip().lower()
            fields[name] = fm.group("value").strip()

        recommended_fix = fields.get("recommended fix", "")
        if not recommended_fix or recommended_fix.lower().startswith(
            ("недостаточно", "не сведено", "не определим", "требует уточнения")
        ):
            continue  # no concrete recommendation to act on

        findings.append({
            "findingId": m.group("id"),
            "label": m.group("label"),
            "severity": severity,
            "confidence": confidence,
            "symptom": fields.get("symptom", ""),
            "location": fields.get("location") or fields.get("code location(s)", ""),
            "recommendedFix": recommended_fix,
            "verification": fields.get("verification", ""),
            "evidence": fields.get("evidence", ""),
        })
    return findings


def _extract_locations(item: dict[str, Any]) -> set[tuple[str, int]]:
    return {(f, int(n)) for f, n in LOCATION_RE.findall(item.get("location", ""))}


def _overlaps(a: set[tuple[str, int]], b: set[tuple[str, int]], window: int) -> bool:
    return any(fa == fb and abs(la - lb) <= window for fa, la in a for fb, lb in b)


def dedup_findings(items: list[dict[str, Any]], window: int = LOCATION_WINDOW_LINES) -> list[dict[str, Any]]:
    """QG-merge: collapse findings whose Location overlaps in the same file
    within `window` lines into one item (the highest severity/confidence one),
    recording the rest under `mergedFrom` instead of dropping them silently.
    Findings with no parseable file:line in Location are never merged — no
    location evidence means no basis for claiming two findings are the same
    defect, so they stay independent (safe default, not a missed merge)."""
    n = len(items)
    locs = [_extract_locations(it) for it in items]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        if not locs[i]:
            continue
        for j in range(i + 1, n):
            if locs[j] and _overlaps(locs[i], locs[j], window):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    def priority(idx: int) -> tuple[int, int]:
        it = items[idx]
        return (SEVERITY_RANK.get(it["severity"], 0), CONFIDENCE_RANK.get(it["confidence"], 0))

    merged: list[dict[str, Any]] = []
    for indices in groups.values():
        if len(indices) == 1:
            merged.append(items[indices[0]])
            continue
        indices.sort(key=priority, reverse=True)
        primary = dict(items[indices[0]])
        primary["mergedFrom"] = [
            {"queueId": items[k]["queueId"], "producerSkill": items[k]["producerSkill"],
             "label": items[k]["label"]}
            for k in indices[1:]
        ]
        merged.append(primary)
    return merged


def apply_family_quota(items: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    """Anti-starvation ordering: cap how many consecutive items from the same
    producerSkill the queue serves before forcing a different one, so a
    priority sort dominated by one category (e.g. 20 find-query-issues
    findings) doesn't push every other category to the very end of a run.
    Only reorders *within* the existing priority order — never promotes a
    lower-priority item ahead of a higher-priority one of a different skill
    unless the quota forces it; if no alternative-skill item remains, the
    streak continues (quota is a soft diversity preference, not a hard cap
    that could ever block a real fix)."""
    if quota <= 0:
        return items
    pending = list(items)
    output: list[dict[str, Any]] = []
    streak_skill: str | None = None
    streak_len = 0
    while pending:
        idx = 0
        if streak_len >= quota:
            alt = next((i for i, it in enumerate(pending) if it["producerSkill"] != streak_skill), None)
            if alt is not None:
                idx = alt
        chosen = pending.pop(idx)
        if chosen["producerSkill"] == streak_skill:
            streak_len += 1
        else:
            streak_skill = chosen["producerSkill"]
            streak_len = 1
        output.append(chosen)
    return output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--merge-from", type=Path, default=None,
                     help="Prior queue.json (resume): carry over status/attempts/"
                          "commitSha for matching queueIds instead of resetting to pending")
    ap.add_argument("--family-quota", type=int, default=3,
                     help="Max consecutive queue items from the same producerSkill "
                          "before a different skill's item is pulled forward "
                          "(anti-starvation; 0 disables)")
    args = ap.parse_args()

    prior_by_id: dict[str, dict[str, Any]] = {}
    if args.merge_from and args.merge_from.is_file():
        prior = json.loads(args.merge_from.read_text(encoding="utf-8"))
        for it in prior.get("items", []):
            if it.get("status") not in ("pending", "in_progress"):
                prior_by_id[it["queueId"]] = it

    raw_items: list[dict[str, Any]] = []
    reports_seen: list[str] = []
    for filename, (skill, track) in REPORT_MAP.items():
        path = args.project_root / filename
        if not path.is_file():
            continue
        reports_seen.append(filename)
        for finding in parse_report(path):
            queue_id = f"{filename}::{finding['findingId']}"
            raw_items.append({
                "queueId": queue_id,
                "reportFile": filename,
                "producerSkill": skill,
                "verificationTrack": track,
                "status": "pending",
                "attempts": [],
                **finding,
            })

    deduped = dedup_findings(raw_items)
    merged_count = len(raw_items) - len(deduped)
    if merged_count:
        print(f"QG-merge: collapsed {merged_count} overlapping finding(s) into "
              f"existing queue items (see mergedFrom)", file=sys.stderr)

    items: list[dict[str, Any]] = []
    for item in deduped:
        carried = prior_by_id.pop(item["queueId"], None)
        if carried is not None:
            item["status"] = carried["status"]
            item["attempts"] = carried.get("attempts", [])
            if "commitSha" in carried:
                item["commitSha"] = carried["commitSha"]
        items.append(item)

    if prior_by_id:
        # Findings that were already resolved/committed/skipped in the prior
        # run but no longer appear in the freshly parsed reports — keep them
        # so the final summary doesn't silently lose this history.
        print(f"carrying over {len(prior_by_id)} finding(s) no longer present "
              f"in current reports: {sorted(prior_by_id)}", file=sys.stderr)
        items.extend(prior_by_id.values())

    items.sort(
        key=lambda it: (
            -SEVERITY_RANK.get(it["severity"], 0),
            -CONFIDENCE_RANK.get(it["confidence"], 0),
            it["reportFile"],
            it["findingId"],
        )
    )
    items = apply_family_quota(items, args.family_quota)

    payload = {
        "schemaVersion": 1,
        "reportsSeen": reports_seen,
        "totalFindings": len(items),
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(str(args.output))
    print(f"queued {len(items)} findings from {len(reports_seen)} reports", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
