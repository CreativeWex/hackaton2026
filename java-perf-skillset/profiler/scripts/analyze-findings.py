#!/usr/bin/env python3
"""Turn one profiler/collect.sh raw run into a findings.json.

Part of the `profiler` Claude Code skill.

Detection is driven purely by JDK/Actuator output formats (jcmd GC.heap_info,
GC.class_histogram, Thread.print, Micrometer/Actuator metrics), not by
anything project-specific — that is why this script lives in the skill and
is not regenerated per project (see references/detection-rules.md for the
exact rules encoded below).

Expects the raw directory layout documented in SKILL.md:

    $RAW_DIR/
      meta.json
      heap/snapshot-N.txt        jcmd <pid> GC.run; GC.run; GC.heap_info
      histogram/snapshot-N.txt   jcmd <pid> GC.class_histogram (>=1, N=1 and N=last required)
      threads/snapshot-N.txt     jcmd <pid> Thread.print (or actuator threaddump)
      actuator/snapshot-N.json   {"gcPauseMaxMs":, "connectionsPending":, "threadsLive":, "heapUsedBytes":}

Usage:
    analyze-findings.py --raw-dir DIR --scenario profiler/scenario.yaml \
        --mode initial --scenario-id ID --run-id ID --git-sha SHA \
        --output FILE

Exit codes:
    0 - findings.json written (findings list may be empty)
    2 - fatal usage / IO / parsing error

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------
# Minimal YAML subset parser (same shape as java-performance-measurement's
# compare_results.py — duplicated here so this script stays standalone).
# --------------------------------------------------------------------------
def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text.lower() in {"null", "~"}:
        return None
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if (text.startswith('"') and text.endswith('"') and len(text) >= 2) or (
        text.startswith("'") and text.endswith("'") and len(text) >= 2
    ):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    out = []
    in_s = in_d = False
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))

    pos = 0

    def parse_block(indent: int) -> Any:
        nonlocal pos
        if pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            items: list[Any] = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                _, content = lines[pos]
                inner = content[2:].strip()
                if ":" in inner and not inner.startswith(("'", '"')):
                    pos += 1
                    item: dict[str, Any] = {}
                    key, _, val = inner.partition(":")
                    if val.strip():
                        item[key.strip()] = _parse_scalar(val)
                    else:
                        item[key.strip()] = parse_block(indent + 4)
                    while pos < len(lines) and lines[pos][0] > indent and not lines[pos][1].startswith("- "):
                        k_indent, k_content = lines[pos]
                        k, _, v = k_content.partition(":")
                        pos += 1
                        if v.strip():
                            item[k.strip()] = _parse_scalar(v)
                        else:
                            item[k.strip()] = parse_block(k_indent + 2)
                    items.append(item)
                else:
                    pos += 1
                    items.append(_parse_scalar(inner))
            return items
        mapping: dict[str, Any] = {}
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            _, content = lines[pos]
            if ":" not in content:
                raise ValueError(f"Cannot parse YAML line: {content!r}")
            key, _, val = content.partition(":")
            pos += 1
            if val.strip():
                mapping[key.strip()] = _parse_scalar(val)
            else:
                if pos < len(lines) and lines[pos][0] > indent:
                    mapping[key.strip()] = parse_block(lines[pos][0])
                else:
                    mapping[key.strip()] = None
        return mapping

    result = parse_block(0)
    if not isinstance(result, dict):
        raise ValueError("Top-level YAML structure must be a mapping")
    return result


# --------------------------------------------------------------------------
# Raw snapshot parsing
# --------------------------------------------------------------------------
HEAP_USED_RE = re.compile(r"used\s+(\d+)K", re.IGNORECASE)
HISTOGRAM_ROW_RE = re.compile(r"^\s*\d+:\s+(\d+)\s+(\d+)\s+(\S.*)$")
DEADLOCK_FOUND_RE = re.compile(r"Found\s+(?:one|\d+)\s+(?:Java-level\s+)?deadlock", re.IGNORECASE)
DEADLOCK_NONE_RE = re.compile(r"No deadlocks found", re.IGNORECASE)
THREAD_NAME_RE = re.compile(r'"([^"]+)"')


def numbered_files(dir_path: Path, prefix: str = "snapshot-") -> list[tuple[int, Path]]:
    if not dir_path.is_dir():
        return []
    out = []
    for p in dir_path.glob(f"{prefix}*.txt"):
        m = re.search(r"(\d+)", p.stem)
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def parse_heap_used_mb(text: str) -> float | None:
    # Prefer a line that mentions "heap" and isn't Metaspace/class space.
    for line in text.splitlines():
        low = line.lower()
        if "heap" in low and "metaspace" not in low and "class space" not in low:
            m = HEAP_USED_RE.search(line)
            if m:
                return int(m.group(1)) / 1024.0
    m = HEAP_USED_RE.search(text)
    return int(m.group(1)) / 1024.0 if m else None


def parse_histogram(text: str) -> dict[str, int]:
    classes: dict[str, int] = {}
    for line in text.splitlines():
        m = HISTOGRAM_ROW_RE.match(line)
        if not m:
            continue
        _instances, nbytes, cls = m.groups()
        classes[cls.strip()] = int(nbytes)
    return classes


def find_deadlock(text: str) -> dict[str, Any] | None:
    if DEADLOCK_NONE_RE.search(text):
        return None
    m = DEADLOCK_FOUND_RE.search(text)
    if not m:
        return None
    block = text[m.start():m.start() + 4000]
    names = sorted(set(THREAD_NAME_RE.findall(block)))
    return {"block": block.strip(), "threadNames": names}


def trend_findings(
    values: list[float],
    noise: float,
    min_monotonic_points: int,
) -> tuple[float, int] | None:
    """Returns (totalGrowth, longestRisingRun) if a sustained rising trend
    of at least min_monotonic_points consecutive points (each rising by more
    than `noise`) is present, else None. A single spike does not qualify."""
    if len(values) < min_monotonic_points:
        return None
    longest = 1
    current = 1
    for i in range(1, len(values)):
        if values[i] > values[i - 1] + noise:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    total_growth = values[-1] - values[0]
    if longest >= min_monotonic_points and total_growth > noise:
        return total_growth, longest
    return None


def severity_for_growth(growth: float, high: float, medium: float) -> str:
    if growth >= high:
        return "high"
    if growth >= medium:
        return "medium"
    return "low"


# --------------------------------------------------------------------------
# Main analysis
# --------------------------------------------------------------------------
def analyze(raw_dir: Path, scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    meta_path = raw_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}

    snapshots_cfg = scenario.get("snapshots") or {}
    expected_count = int(snapshots_cfg.get("count", 3))
    min_monotonic = int(snapshots_cfg.get("minMonotonicPointsForLeak", 3))

    thresholds = scenario.get("thresholds") or {}
    heap_noise_mb = float(thresholds.get("heapGrowthNoiseMb", 5))
    thread_noise = float(thresholds.get("threadGrowthNoise", 3))
    gc_pause_max_ms = float(thresholds.get("gcPauseMaxMs", 500))
    conn_pending_max = float(thresholds.get("connectionsPendingMax", 0))

    # ---- heap trend ----
    heap_files = numbered_files(raw_dir / "heap")
    heap_values: list[float] = []
    for _n, path in heap_files:
        val = parse_heap_used_mb(path.read_text(encoding="utf-8", errors="replace"))
        if val is not None:
            heap_values.append(val)

    hist_files = numbered_files(raw_dir / "histogram")
    top_growth_classes: list[dict[str, Any]] = []
    if len(hist_files) >= 2:
        first = parse_histogram(hist_files[0][1].read_text(encoding="utf-8", errors="replace"))
        last = parse_histogram(hist_files[-1][1].read_text(encoding="utf-8", errors="replace"))
        deltas = []
        for cls, last_bytes in last.items():
            delta = last_bytes - first.get(cls, 0)
            if delta > 0:
                deltas.append({"class": cls, "bytesGrowth": delta})
        deltas.sort(key=lambda d: d["bytesGrowth"], reverse=True)
        top_growth_classes = deltas[:5]

    heap_trend = trend_findings(heap_values, heap_noise_mb, min_monotonic)
    if heap_trend is not None:
        growth, _run = heap_trend
        findings.append({
            "id": "heap-growth",
            "category": "heap_leak",
            "severity": severity_for_growth(growth, high=50, medium=20),
            "magnitude": round(growth, 2),
            "magnitudeUnit": "mb",
            "evidence": {
                "usedMbBySnapshot": [round(v, 2) for v in heap_values],
                "topGrowthClasses": top_growth_classes,
            },
        })

    # ---- thread count trend ----
    actuator_files = numbered_files(raw_dir / "actuator", prefix="snapshot-")
    actuator_snapshots: list[dict[str, Any]] = []
    for _n, path in actuator_files:
        try:
            actuator_snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    threads_live = [s["threadsLive"] for s in actuator_snapshots if s.get("threadsLive") is not None]
    thread_trend = trend_findings([float(v) for v in threads_live], thread_noise, min_monotonic)
    if thread_trend is not None:
        growth, _run = thread_trend
        findings.append({
            "id": "thread-growth",
            "category": "thread_leak",
            "severity": severity_for_growth(growth, high=50, medium=15),
            "magnitude": round(growth, 2),
            "magnitudeUnit": "count",
            "evidence": {"threadsLiveBySnapshot": threads_live},
        })

    # ---- deadlocks ----
    thread_dump_files = numbered_files(raw_dir / "threads")
    seen_deadlock_ids: dict[str, dict[str, Any]] = {}
    for n, path in thread_dump_files:
        dl = find_deadlock(path.read_text(encoding="utf-8", errors="replace"))
        if dl is None:
            continue
        key = hashlib.sha256(",".join(dl["threadNames"]).encode()).hexdigest()[:8]
        fid = f"deadlock-{key}"
        if fid not in seen_deadlock_ids:
            seen_deadlock_ids[fid] = {
                "id": fid,
                "category": "deadlock",
                "severity": "critical",
                "magnitude": None,
                "magnitudeUnit": None,
                "evidence": {"threadNames": dl["threadNames"], "block": dl["block"], "seenAtSnapshots": [n]},
            }
        else:
            seen_deadlock_ids[fid]["evidence"]["seenAtSnapshots"].append(n)
    findings.extend(seen_deadlock_ids.values())

    # ---- GC pause ----
    pauses = [s["gcPauseMaxMs"] for s in actuator_snapshots if s.get("gcPauseMaxMs") is not None]
    if pauses and max(pauses) > gc_pause_max_ms:
        findings.append({
            "id": "gc-pause",
            "category": "gc_pause",
            "severity": "high" if max(pauses) > gc_pause_max_ms * 2 else "medium",
            "magnitude": max(pauses),
            "magnitudeUnit": "ms",
            "evidence": {"gcPauseMaxMsBySnapshot": pauses, "thresholdMs": gc_pause_max_ms},
        })

    # ---- connection pool starvation ----
    pending = [s["connectionsPending"] for s in actuator_snapshots if s.get("connectionsPending") is not None]
    if pending and max(pending) > conn_pending_max:
        findings.append({
            "id": "connection-starvation",
            "category": "connection_starvation",
            "severity": "high" if max(pending) > conn_pending_max + 5 else "medium",
            "magnitude": max(pending),
            "magnitudeUnit": "count",
            "evidence": {"connectionsPendingBySnapshot": pending, "thresholdCount": conn_pending_max},
        })

    run_meta = {
        "snapshotCount": len(heap_files),
        "expectedSnapshotCount": expected_count,
        "durationS": meta.get("durationS"),
        "concurrency": meta.get("concurrency"),
    }
    return findings, run_meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--scenario", required=True, type=Path)
    ap.add_argument("--mode", required=True, choices=["initial", "incremental", "final"])
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--git-sha", default="unknown")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    try:
        scenario = parse_simple_yaml(args.scenario.read_text(encoding="utf-8"))
        findings, run_meta = analyze(args.raw_dir, scenario)
        payload = {
            "schemaVersion": 1,
            "mode": args.mode,
            "scenarioId": args.scenario_id,
            "runId": args.run_id,
            "gitSha": args.git_sha,
            "meta": run_meta,
            "findings": findings,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(str(args.output))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
