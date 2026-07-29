#!/usr/bin/env python3
"""Render a Markdown report from a compare-findings.py output.

Part of the `profiler` Claude Code skill.

Usage:
    render-report.py --result <findings.json> --output <report.md> \
        [--files-changed <path> ...]

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


def finding_row(fid: str, finding: dict[str, Any], cmp_entry: dict[str, Any] | None) -> str:
    category = finding.get("category", "?")
    severity = finding.get("severity", "?")
    unit = finding.get("magnitudeUnit") or ""
    current = fmt_num(finding.get("magnitude"))
    if unit and finding.get("magnitude") is not None:
        current = f"{current} {unit}"
    name = f"**{fid}** ({category}, {severity})"
    if cmp_entry:
        reference = fmt_num(cmp_entry.get("reference"))
        if unit and cmp_entry.get("reference") is not None:
            reference = f"{reference} {unit}"
        delta = fmt_delta(cmp_entry.get("deltaPercent"))
        verdict = cmp_entry.get("verdict", "n/a")
    else:
        reference, delta, verdict = "n/a", "n/a", "n/a"
    return f"| {name} | {reference} | {current} | {delta} | {verdict} |"


def resolved_rows(comparison: dict[str, Any], current_ids: set[str]) -> list[str]:
    """RESOLVED findings have no entry in current findings, only in comparison."""
    rows = []
    for fid, cmp_entry in comparison.items():
        if cmp_entry.get("verdict") == "RESOLVED" and fid not in current_ids:
            category = cmp_entry.get("category", "?")
            severity = cmp_entry.get("severity") or "?"
            reference = fmt_num(cmp_entry.get("reference"))
            rows.append(f"| **{fid}** ({category}, {severity}) | {reference} | resolved | n/a | RESOLVED |")
    return rows


def render(result: dict[str, Any], files_changed: list[str]) -> str:
    verdict = result.get("verdict", "FAILED")
    emoji = VERDICT_EMOJI.get(verdict, "")
    mode = result.get("mode", "unknown")
    ref = result.get("referenceRun") or {}
    env = result.get("environment") or {}
    meta = result.get("meta") or {}
    findings: list[dict[str, Any]] = result.get("findings") or []
    comparison: dict[str, Any] = result.get("comparison") or {}

    fingerprint_note = "NOT compatible with reference" if verdict == "NOT_COMPARABLE" else "compatible with reference"
    if mode == "initial":
        fingerprint_note = "baseline (no reference)"

    lines: list[str] = []
    lines.append(f"# Profiler report — {emoji} {verdict}")
    lines.append("")
    lines.append(f"- **Mode:** {mode}")
    lines.append(f"- **Run ID:** {result.get('runId', 'unknown')}")
    lines.append(f"- **Git SHA:** {result.get('gitSha', 'unknown')}")
    if ref.get("gitSha"):
        lines.append(f"- **Reference Git SHA:** {ref['gitSha']}")
    if ref.get("runId"):
        lines.append(f"- **Reference run:** {ref['runId']} ({ref.get('path')})")
    lines.append(f"- **Scenario:** {result.get('scenarioId', 'unknown')}")
    lines.append(f"- **Snapshots:** {meta.get('snapshotCount', 'n/a')}/{meta.get('expectedSnapshotCount', 'n/a')}, "
                 f"duration {meta.get('durationS', 'n/a')}s, concurrency {meta.get('concurrency', 'n/a')}")
    lines.append(f"- **Profile fingerprint:** `{result.get('profileFingerprint', 'n/a')}` — {fingerprint_note}")
    lines.append(f"- **Environment fingerprint:** `{env.get('fingerprint', 'n/a')}` "
                 f"({env.get('os', '?')}/{env.get('arch', '?')}, {env.get('cpuCount', '?')} CPU, "
                 f"Java {env.get('javaVersion', '?')})")
    lines.append("")

    current_ids = {f["id"] for f in findings}
    if findings or comparison:
        lines.append("## Findings")
        lines.append("")
        lines.append("| Finding | Reference | Current | Delta | Verdict |")
        lines.append("|---|---|---|---|---|")
        if not findings:
            lines.append("| _none_ |  |  |  |  |")
        for f in findings:
            lines.append(finding_row(f["id"], f, comparison.get(f["id"])))
        lines.extend(resolved_rows(comparison, current_ids))
        lines.append("")

    lines.append("## Explanation")
    lines.append("")
    lines.append(result.get("explanation", "No explanation available."))
    lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Findings: `{result.get('_resultPath', 'findings.json')}`")
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
    ap.add_argument("--files-changed", nargs="*", default=[])
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
