#!/usr/bin/env python3
"""Aggregate normalized performance samples, compare with a reference and
compute a verdict.

Part of the `java-performance-measurement` Claude Code skill.

Usage:
    compare_results.py \
        --scenario perf/scenario.yaml \
        --mode initial|incremental|final \
        --current-dir <dir-with-normalized-*.json> \
        [--reference <reference-result.json>] \
        [--fingerprint-file <fingerprint.json>] \
        [--git-sha <sha>] \
        [--run-id <id>] \
        [--raw-dir <path-recorded-in-result>] \
        --output <result.json>

The tool is agnostic to JMH/k6/CLI raw formats: it consumes only
normalized per-repeat JSON files of the form:

    {
      "schemaVersion": 1,
      "scenarioId": "...",
      "measurementType": "jmh|http|cli",
      "runId": "...",
      "gitSha": "...",
      "metrics": {"<metric-id>": <number>, ...}
    }

Exit codes:
    0 - result.json written (verdict may still be WORSE/INCONCLUSIVE/...)
    2 - fatal usage / IO / parsing error (verdict FAILED is written when
        possible)

Requires Python 3.10+. No external dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import statistics
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

VERDICT_PRIORITY = [
    "FAILED",
    "NOT_COMPARABLE",
    "INCONCLUSIVE",
    "MIXED",
    "WORSE",
    "BETTER",
    "SAME",
]

VALID_DIRECTIONS = {"lower_is_better", "higher_is_better"}


# --------------------------------------------------------------------------
# Minimal YAML subset parser (no external deps).
# Supports: nested mappings by indentation, lists of scalars and of
# mappings ("- key: value"), scalars (int/float/bool/null/strings),
# comments and quoted strings. Enough for perf/scenario.yaml.
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
    # Remove trailing comments that are not inside quotes.
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
        # List block?
        if pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            items: list[Any] = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                _, content = lines[pos]
                inner = content[2:].strip()
                if ":" in inner and not inner.startswith(("'", '"')):
                    # list item that is a mapping: "- key: value"
                    pos += 1
                    item: dict[str, Any] = {}
                    key, _, val = inner.partition(":")
                    if val.strip():
                        item[key.strip()] = _parse_scalar(val)
                    else:
                        item[key.strip()] = parse_block(indent + 4)
                    # subsequent keys of the same mapping are indented deeper
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
        # Mapping block
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
# Scenario helpers
# --------------------------------------------------------------------------
def load_scenario(path: Path) -> dict[str, Any]:
    scenario = parse_simple_yaml(path.read_text(encoding="utf-8"))
    for required in ("id", "type", "metrics"):
        if required not in scenario:
            raise ValueError(f"scenario.yaml: missing required key '{required}'")
    metrics = scenario["metrics"]
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("scenario.yaml: 'metrics' must be a non-empty list")
    for m in metrics:
        if "id" not in m or "direction" not in m:
            raise ValueError("scenario.yaml: each metric needs 'id' and 'direction'")
        if m["direction"] not in VALID_DIRECTIONS:
            raise ValueError(
                f"scenario.yaml: metric '{m['id']}' has invalid direction "
                f"'{m['direction']}'"
            )
    return scenario


def scenario_fingerprint(scenario_path: Path, scenario: dict[str, Any]) -> str:
    """Hash of scenario content + measurement type + tool commands."""
    h = hashlib.sha256()
    h.update(scenario_path.read_bytes())
    h.update(str(scenario.get("type")).encode())
    commands = scenario.get("commands") or {}
    for key in sorted(commands):
        h.update(f"{key}={commands[key]}".encode())
    # payload checksums, if a payloads dir exists next to scenario.yaml
    payloads_dir = scenario_path.parent / "payloads"
    if payloads_dir.is_dir():
        for p in sorted(payloads_dir.rglob("*")):
            if p.is_file():
                h.update(p.name.encode())
                h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
    return h.hexdigest()[:16]


def environment_fingerprint(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    env: dict[str, Any] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "cpuCount": os.cpu_count(),
        "javaVersion": (extra or {}).get("javaVersion", "unknown"),
        "jvmOptions": (extra or {}).get("jvmOptions", "unknown"),
        "toolVersion": (extra or {}).get("toolVersion", "unknown"),
        "memoryLimit": (extra or {}).get("memoryLimit", "unknown"),
    }
    digest = hashlib.sha256(
        json.dumps(env, sort_keys=True).encode()
    ).hexdigest()[:16]
    env["fingerprint"] = digest
    return env


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def load_samples(current_dir: Path, scenario_id: str) -> list[dict[str, Any]]:
    files = sorted(current_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No normalized *.json files in {current_dir}")
    samples = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if "metrics" not in data or not isinstance(data["metrics"], dict):
            raise ValueError(f"{f}: missing 'metrics' object")
        if data.get("scenarioId") not in (None, scenario_id):
            raise ValueError(
                f"{f}: scenarioId '{data.get('scenarioId')}' does not match "
                f"scenario '{scenario_id}'"
            )
        data["_source"] = str(f)
        samples.append(data)
    return samples


def aggregate_metric(values: list[float]) -> dict[str, Any]:
    med = statistics.median(values)
    mean = statistics.fmean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    variation = (stddev / mean * 100.0) if mean != 0 else (0.0 if stddev == 0 else math.inf)
    return {
        "samples": values,
        "median": med,
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "stddev": stddev,
        "variationPercent": round(variation, 4) if math.isfinite(variation) else None,
    }


def aggregate_all(
    samples: list[dict[str, Any]], scenario: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Returns (metric-id -> stats, errors)."""
    errors: list[str] = []
    stats: dict[str, dict[str, Any]] = {}
    for metric in scenario["metrics"]:
        mid = metric["id"]
        values: list[float] = []
        for s in samples:
            if mid not in s["metrics"]:
                errors.append(
                    f"metric '{mid}' missing in sample {s.get('_source', '?')}"
                )
                continue
            v = s["metrics"][mid]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(
                    f"metric '{mid}' in {s.get('_source', '?')} is not numeric"
                )
                continue
            values.append(float(v))
        if len(values) != len(samples):
            # a required metric is missing in at least one repeat -> FAILED
            continue
        stats[mid] = aggregate_metric(values)
        stats[mid]["unit"] = metric.get("unit", "")
        stats[mid]["direction"] = metric["direction"]
        stats[mid]["primary"] = bool(metric.get("primary", False))
    return stats, errors


# --------------------------------------------------------------------------
# Comparison & verdict
# --------------------------------------------------------------------------
def relative_delta_percent(reference: float, current: float) -> float | None:
    if reference == 0:
        return None
    return (current - reference) / abs(reference) * 100.0


def classify_metric(
    direction: str,
    delta_percent: float | None,
    noise: float,
    regression: float,
    improvement: float,
) -> str:
    """Returns SAME / BETTER / WORSE / INCONCLUSIVE for a single metric."""
    if delta_percent is None:
        return "INCONCLUSIVE"
    # Normalize so that positive == improvement.
    signed = -delta_percent if direction == "lower_is_better" else delta_percent
    if abs(delta_percent) <= noise:
        return "SAME"
    if signed >= improvement:
        return "BETTER"
    if signed <= -regression:
        return "WORSE"
    # Above noise but below the significance thresholds.
    return "SAME"


def combine_verdicts(metric_verdicts: list[str]) -> str:
    has_better = "BETTER" in metric_verdicts
    has_worse = "WORSE" in metric_verdicts
    if "INCONCLUSIVE" in metric_verdicts:
        return "INCONCLUSIVE"
    if has_better and has_worse:
        return "MIXED"
    if has_worse:
        return "WORSE"
    if has_better:
        return "BETTER"
    return "SAME"


def compute_verdict(
    mode: str,
    stats: dict[str, dict[str, Any]],
    errors: list[str],
    scenario: dict[str, Any],
    reference: dict[str, Any] | None,
    scenario_fp: str,
    env_fp: str,
) -> tuple[str, str, dict[str, Any]]:
    """Returns (verdict, explanation, per-metric comparison)."""
    repeat = scenario.get("repeat") or {}
    max_variation = float(repeat.get("maxVariationPercent", 10))
    comparison_cfg = scenario.get("comparison") or {}
    noise = float(comparison_cfg.get("noiseThresholdPercent", 5))
    regression = float(comparison_cfg.get("regressionThresholdPercent", 10))
    improvement = float(comparison_cfg.get("improvementThresholdPercent", 10))

    comparison: dict[str, Any] = {}

    if errors:
        return "FAILED", "; ".join(errors), comparison

    if not stats:
        return "FAILED", "No metrics could be aggregated", comparison

    # Variation check on primary metrics.
    noisy = [
        mid
        for mid, s in stats.items()
        if s["primary"]
        and (s["variationPercent"] is None or s["variationPercent"] > max_variation)
    ]

    if mode == "initial":
        if noisy:
            return (
                "INCONCLUSIVE",
                f"Variation of primary metric(s) {', '.join(noisy)} exceeds "
                f"maxVariationPercent={max_variation}; baseline not reliable",
                comparison,
            )
        return "BASELINE_CREATED", "Initial baseline created successfully", comparison

    if reference is None:
        return (
            "FAILED",
            "Reference result.json is required for mode "
            f"'{mode}' but was not provided",
            comparison,
        )

    # Fingerprint compatibility.
    ref_scenario_fp = reference.get("scenarioFingerprint")
    ref_env_fp = (reference.get("environment") or {}).get("fingerprint")
    if ref_scenario_fp != scenario_fp or ref_env_fp != env_fp:
        detail = []
        if ref_scenario_fp != scenario_fp:
            detail.append(
                f"scenario fingerprint {ref_scenario_fp} != {scenario_fp}"
            )
        if ref_env_fp != env_fp:
            detail.append(f"environment fingerprint {ref_env_fp} != {env_fp}")
        return "NOT_COMPARABLE", "; ".join(detail), comparison

    if noisy:
        return (
            "INCONCLUSIVE",
            f"Variation of primary metric(s) {', '.join(noisy)} exceeds "
            f"maxVariationPercent={max_variation}",
            comparison,
        )

    ref_metrics = reference.get("metrics") or {}
    metric_verdicts: list[str] = []
    for mid, s in stats.items():
        ref_entry = ref_metrics.get(mid)
        if ref_entry is None:
            comparison[mid] = {"verdict": "INCONCLUSIVE", "reason": "missing in reference"}
            if s["primary"]:
                metric_verdicts.append("INCONCLUSIVE")
            continue
        ref_median = ref_entry.get("median")
        delta = relative_delta_percent(float(ref_median), s["median"]) if ref_median is not None else None
        verdict = classify_metric(s["direction"], delta, noise, regression, improvement)
        comparison[mid] = {
            "reference": ref_median,
            "current": s["median"],
            "deltaPercent": round(delta, 4) if delta is not None else None,
            "variationPercent": s["variationPercent"],
            "direction": s["direction"],
            "primary": s["primary"],
            "verdict": verdict,
        }
        if s["primary"]:
            metric_verdicts.append(verdict)

    if not metric_verdicts:
        return "INCONCLUSIVE", "No primary metrics available for comparison", comparison

    overall = combine_verdicts(metric_verdicts)
    explanations = {
        "SAME": f"All primary metrics changed within noise threshold ({noise}%)",
        "BETTER": (
            f"At least one primary metric improved beyond {improvement}% "
            f"with no regression beyond {regression}%"
        ),
        "WORSE": f"At least one primary metric regressed beyond {regression}%",
        "MIXED": "Both significant improvement and significant regression detected",
        "INCONCLUSIVE": "At least one primary metric could not be compared",
    }
    return overall, explanations[overall], comparison


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", required=True, type=Path)
    ap.add_argument("--mode", required=True, choices=["initial", "incremental", "final"])
    ap.add_argument("--current-dir", required=True, type=Path,
                    help="Directory with normalized per-repeat *.json files")
    ap.add_argument("--reference", type=Path, default=None,
                    help="Reference result.json (required for incremental/final)")
    ap.add_argument("--fingerprint-file", type=Path, default=None,
                    help="Optional JSON with javaVersion/jvmOptions/toolVersion/memoryLimit")
    ap.add_argument("--git-sha", default="unknown")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--raw-dir", default=None,
                    help="Path to raw artifacts, recorded in result.json")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    def write_result(payload: dict[str, Any]) -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(str(args.output))

    run_id = args.run_id or re.sub(r"[:+]", "-", __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"))

    base: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": args.mode,
        "runId": run_id,
        "gitSha": args.git_sha,
        "rawArtifacts": args.raw_dir,
    }

    try:
        scenario = load_scenario(args.scenario)
        extra = {}
        if args.fingerprint_file and args.fingerprint_file.is_file():
            extra = json.loads(args.fingerprint_file.read_text(encoding="utf-8"))
        env = environment_fingerprint(extra)
        scenario_fp = scenario_fingerprint(args.scenario, scenario)

        samples = load_samples(args.current_dir, scenario["id"])
        stats, errors = aggregate_all(samples, scenario)

        reference = None
        if args.reference is not None:
            if not args.reference.is_file():
                if args.mode != "initial":
                    raise FileNotFoundError(
                        f"Reference not found: {args.reference}. "
                        "Run 'initial' mode first."
                    )
            else:
                reference = json.loads(args.reference.read_text(encoding="utf-8"))

        verdict, explanation, comparison = compute_verdict(
            args.mode, stats, errors, scenario, reference,
            scenario_fp, env["fingerprint"],
        )

        base.update({
            "scenarioId": scenario["id"],
            "measurementType": scenario["type"],
            "repeatCount": len(samples),
            "aggregation": (scenario.get("repeat") or {}).get("aggregation", "median"),
            "metrics": stats,
            "comparison": comparison,
            "environment": env,
            "scenarioFingerprint": scenario_fp,
            "referenceRun": {
                "path": str(args.reference) if args.reference else None,
                "runId": (reference or {}).get("runId"),
                "gitSha": (reference or {}).get("gitSha"),
            },
            "verdict": verdict,
            "explanation": explanation,
        })
        write_result(base)
        return 0
    except Exception as exc:  # noqa: BLE001 - report as FAILED, keep raw data
        base.update({
            "verdict": "FAILED",
            "explanation": f"{type(exc).__name__}: {exc}",
        })
        try:
            write_result(base)
        except OSError:
            print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
