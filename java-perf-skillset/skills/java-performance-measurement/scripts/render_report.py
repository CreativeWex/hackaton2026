#!/usr/bin/env python3
"""Render a Markdown performance report from an aggregated result.json.

Part of the `java-performance-measurement` Claude Code skill.

Usage:
    render_report.py --result <result.json> --output <report.md> \
        [--files-changed <path> ...]

Reads the aggregated result.json produced by compare_results.py and writes
a concise Markdown report following references/report-format.md.

Requires Python 3.10+. No external dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VERDICT_EMOJI = {
    "BASELINE_CREATED": "📊",
    "BETTER": "✅",
    "WORSE": "❌",
    "SAME": "➖",
    "MIXED": "⚠️",
    "INCONCLUSIVE": "❓",
    "NOT_COMPARABLE": "🚫",
    "FAILED": "💥",
}


def fmt_num(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def fmt_delta(delta: Any) -> str:
    if delta is None:
        return "n/a"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2f}%"


def metric_row(mid: str, stats: dict[str, Any], cmp_entry: dict[str, Any] | None) -> str:
    unit = stats.get("unit", "")
    name = f"{mid} ({unit})" if unit else mid
    if stats.get("primary"):
        name = f"**{name}**"
    current = fmt_num(stats.get("median"))
    variation = stats.get("variationPercent")
    variation_s = f"{variation:.2f}%" if isinstance(variation, (int, float)) else "n/a"
    if cmp_entry:
        reference = fmt_num(cmp_entry.get("reference"))
        delta = fmt_delta(cmp_entry.get("deltaPercent"))
        verdict = cmp_entry.get("verdict", "n/a")
    else:
        reference, delta, verdict = "n/a", "n/a", "n/a"
    return f"| {name} | {reference} | {current} | {delta} | {variation_s} | {verdict} |"


def render(result: dict[str, Any], files_changed: list[str]) -> str:
    verdict = result.get("verdict", "FAILED")
    emoji = VERDICT_EMOJI.get(verdict, "")
    mode = result.get("mode", "unknown")
    ref = result.get("referenceRun") or {}
    env = result.get("environment") or {}
    metrics: dict[str, Any] = result.get("metrics") or {}
    comparison: dict[str, Any] = result.get("comparison") or {}

    fingerprint_note = (
        "compatible with reference"
        if verdict not in ("NOT_COMPARABLE",)
        else "NOT compatible with reference"
    )
    if mode == "initial":
        fingerprint_note = "baseline (no reference)"

    lines: list[str] = []
    lines.append(f"# Performance report — {emoji} {verdict}")
    lines.append("")
    lines.append(f"- **Mode:** {mode}")
    lines.append(f"- **Run ID:** {result.get('runId', 'unknown')}")
    lines.append(f"- **Git SHA:** {result.get('gitSha', 'unknown')}")
    if ref.get("gitSha"):
        lines.append(f"- **Reference Git SHA:** {ref['gitSha']}")
    if ref.get("runId"):
        lines.append(f"- **Reference run:** {ref['runId']} ({ref.get('path')})")
    lines.append(f"- **Scenario:** {result.get('scenarioId', 'unknown')} "
                 f"({result.get('measurementType', 'unknown')})")
    lines.append(f"- **Repeats:** {result.get('repeatCount', 'n/a')}, "
                 f"aggregation: {result.get('aggregation', 'median')}")
    lines.append(f"- **Scenario fingerprint:** `{result.get('scenarioFingerprint', 'n/a')}` "
                 f"— {fingerprint_note}")
    lines.append(f"- **Environment fingerprint:** `{env.get('fingerprint', 'n/a')}` "
                 f"({env.get('os', '?')}/{env.get('arch', '?')}, "
                 f"{env.get('cpuCount', '?')} CPU, Java {env.get('javaVersion', '?')})")
    lines.append("")

    if metrics:
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Metric | Reference | Current | Delta | Variation | Verdict |")
        lines.append("|---|---|---|---|---|---|")
        for mid, stats in metrics.items():
            lines.append(metric_row(mid, stats, comparison.get(mid)))
        lines.append("")

    lines.append("## Explanation")
    lines.append("")
    lines.append(result.get("explanation", "No explanation available."))
    lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Aggregated result: `{result.get('_resultPath', 'result.json')}`")
    if result.get("rawArtifacts"):
        lines.append(f"- Raw artifacts: `{result['rawArtifacts']}`")
    lines.append("")

    if files_changed:
        lines.append("## Created or updated files")
        lines.append("")
        for f in files_changed:
            lines.append(f"- `{f}`")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--files-changed", nargs="*", default=[],
                    help="Paths recorded in the 'Created or updated files' section")
    args = ap.parse_args()

    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read result JSON: {exc}", file=sys.stderr)
        return 2

    result["_resultPath"] = str(args.result)
    report = render(result, list(args.files_changed))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(str(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
