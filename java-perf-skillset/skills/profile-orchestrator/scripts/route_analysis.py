#!/usr/bin/env python3
"""Evidence-driven router: pick at most 3 analysis packs for this run.

Part of the `profile-orchestrator` Claude Code skill. Reads compact
measurement/profiler evidence and decides which detector packs are worth
running, instead of unconditionally running all 22 find-* skills.

Usage:
    route_analysis.py --project-root DIR --evidence .profile-run/evidence.json
    route_analysis.py --project-root DIR --evidence ... --full
    route_analysis.py --project-root DIR --evidence ... --full-audit

Output: <project-root>/.profile-run/analysis-plan.json

Evidence format: JSON, either flat ({"sql_count": 248, ...}) or nested
({"baseline": {...}, "profiler": {...}}). Keys may be snake_case or
camelCase. A missing/invalid evidence file is not an error — the router
falls back to the default packs (data-access + cpu-hotpath).

Modes:
  (default)     top-scored packs, max 3; fallback when no evidence signals.
  --full        adds the `cleanup` pack; the 3-pack limit still holds
                (cleanup takes one of the three slots).
  --full-audit  explicit, documented successor of the legacy "run
                everything" /profile behaviour: selects ALL packs. Never
                the default.

Python 3.10+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PLAN_VERSION = 1
MAX_PACKS = 3
FALLBACK_PACKS = ["data-access", "cpu-hotpath"]

PACK_SKILLS: dict[str, list[str]] = {
    "data-access": [
        "find-query-issues",
        "find-missing-batching",
        "find-orm-fetch-strategy-issues",
        "find-over-fetching-api",
        "find-unbounded-data-loading",
        "find-missing-caching",
    ],
    "cpu-hotpath": [
        "find-algorithm-inefficiency",
        "find-inefficient-api-usage",
        "find-redundant-computation",
        "find-redundant-checks",
        "find-reflection-in-hot-path",
        "find-regex-issues",
    ],
    "memory-gc": [
        "find-gc-pressure",
        "find-data-layout-waste",
        "find-resource-management-issues",
        "find-unbounded-cache-or-queue",
    ],
    "concurrency": [
        "find-concurrency-issues",
        "find-transaction-locking-issues",
        "find-cache-locality-issues",
    ],
    "io-observability": [
        "find-logging-overhead",
        "find-exceptions-as-control-flow",
    ],
    "cleanup": [
        "find-dead-code",
    ],
}

# signal (normalized snake_case) -> (pack, base score when present & nonzero,
# threshold for +1 magnitude bonus). Camel-case evidence keys are normalized
# before lookup, so sqlCount/jdbcSamples/... are covered by the same rows.
SIGNALS: dict[str, tuple[str, int, float]] = {
    "sql_count":        ("data-access", 2, 50),
    "jdbc_samples":     ("data-access", 2, 50),
    "cpu_hotspots":     ("cpu-hotpath", 2, 3),
    "cpu_pct":          ("cpu-hotpath", 2, 60),
    "allocation_rate":  ("memory-gc", 2, 100),
    "gc_pause_ms":      ("memory-gc", 2, 200),
    "heap_growth_mb":   ("memory-gc", 2, 50),
    "blocked_ms":       ("concurrency", 2, 500),
    "lock_contention":  ("concurrency", 2, 1),
    "logging_samples":  ("io-observability", 2, 20),
    "exception_count":  ("io-observability", 2, 20),
}

FINDINGS_CONTRACT = {
    "format": "jsonl",
    "path": ".profile-run/findings.jsonl",
    "max_per_pack": 10,
    "minimum_confidence": 0.7,
}

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_key(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


def numeric_value(value) -> float:
    """Best-effort numeric significance of an evidence value."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 1.0 if value.strip() else 0.0
    if isinstance(value, list):
        return float(len(value))
    if isinstance(value, dict):
        return float(len(value))
    return 0.0


def flatten(node, out: dict[str, float]) -> None:
    """Collect leaf signal values from arbitrarily nested evidence
    (top-level {"baseline": ..., "profiler": ...} or flat). On duplicate
    keys the larger value wins — evidence is about the worst observation."""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        norm = normalize_key(str(key))
        if isinstance(value, dict) and norm not in SIGNALS:
            flatten(value, out)
            continue
        num = numeric_value(value)
        if norm in out:
            out[norm] = max(out[norm], num)
        else:
            out[norm] = num


def score_packs(evidence: dict[str, float]) -> tuple[dict[str, int], dict[str, list[str]]]:
    scores = {pack: 0 for pack in PACK_SKILLS if pack != "cleanup"}
    matched: dict[str, list[str]] = {pack: [] for pack in scores}
    for signal, (pack, base, bonus_at) in SIGNALS.items():
        value = evidence.get(signal, 0.0)
        if value <= 0:
            continue
        scores[pack] += base + (1 if value >= bonus_at else 0)
        matched[pack].append(f"{signal}={evidence[signal]:g}")
    return scores, matched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--evidence", type=Path, default=None,
                    help="Evidence JSON (default: <project-root>/.profile-run/evidence.json)")
    ap.add_argument("--full", action="store_true",
                    help="Include the cleanup pack (still max 3 packs total)")
    ap.add_argument("--full-audit", action="store_true",
                    help="Explicit full audit: select ALL packs (legacy /profile scope)")
    ap.add_argument("--max-packs", type=int, default=MAX_PACKS)
    ap.add_argument("--output", type=Path, default=None,
                    help="Plan path (default: <project-root>/.profile-run/analysis-plan.json)")
    args = ap.parse_args()

    root = args.project_root.resolve()
    if not root.is_dir():
        print(f"error: --project-root {root} is not a directory", file=sys.stderr)
        return 2
    evidence_path = args.evidence or (root / ".profile-run" / "evidence.json")
    if not evidence_path.is_absolute():
        evidence_path = root / evidence_path
    out = args.output or (root / ".profile-run" / "analysis-plan.json")

    raw = None
    evidence_status = "ok"
    if evidence_path.is_file():
        try:
            raw = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            evidence_status = f"invalid ({exc.__class__.__name__})"
            print(f"warning: evidence file {evidence_path} unreadable: {exc}; "
                  f"falling back to default packs", file=sys.stderr)
    else:
        evidence_status = "missing"
        print(f"warning: evidence file {evidence_path} not found; "
              f"falling back to default packs", file=sys.stderr)

    flat: dict[str, float] = {}
    flatten(raw, flat)
    scores, matched = score_packs(flat)

    fallback_used = False
    if args.full_audit:
        mode = "full-audit"
        selected = list(PACK_SKILLS)
    else:
        mode = "full" if args.full else "standard"
        ranked = sorted((p for p in scores if scores[p] > 0),
                        key=lambda p: (-scores[p], p))
        limit = max(1, args.max_packs)
        if args.full:
            # cleanup is explicit-opt-in and takes one of the max-packs slots
            selected = ranked[:limit - 1]
            if not selected:
                fallback_used = True
                selected = FALLBACK_PACKS[:limit - 1]
            selected = selected + ["cleanup"]
        else:
            selected = ranked[:limit]
            if not selected:
                fallback_used = True
                selected = FALLBACK_PACKS[:limit]

    plan = {
        "version": PLAN_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "max_packs": args.max_packs,
        "evidence_path": str(evidence_path),
        "evidence_status": evidence_status,
        "fallback_used": fallback_used,
        "selected_packs": selected,
        "scores": scores,
        "matched_signals": {p: sig for p, sig in matched.items() if sig},
        "skills": {pack: PACK_SKILLS[pack] for pack in selected},
        "findings_contract": dict(FINDINGS_CONTRACT),
        "early_stop": {
            "enabled": mode == "standard",
            "rule": "stop launching further detectors once a high-confidence "
                    "(>= 0.85) root cause explaining the primary regression is "
                    "recorded in findings.jsonl; never applies in --full/--full-audit",
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"selected packs ({mode}"
          f"{', fallback' if fallback_used else ''}): {', '.join(selected)}",
          file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
