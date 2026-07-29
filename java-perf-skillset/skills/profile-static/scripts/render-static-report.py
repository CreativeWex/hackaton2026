#!/usr/bin/env python3
"""Aggregate normalized findings from CheckStyle, PMD and SpotBugs
(.profile-run/<tool>-findings.json, common schema produced by
normalize-findings.py) and render a unified STATICREPORT.md.

Usage: render-static-report.py <project-root> [--min-severity LEVEL]

LEVEL: CRITICAL | HIGH | MEDIUM | LOW | INFO (keep findings at this level
and above; default keeps everything).

Python 3.10+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

TOOLS = ("checkstyle", "pmd", "spotbugs")
TOOL_TITLES = {"checkstyle": "CheckStyle", "pmd": "PMD", "spotbugs": "SpotBugs"}
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}


def load_findings(project_root: Path) -> dict[str, list[dict]]:
    findings: dict[str, list[dict]] = {}
    for tool in TOOLS:
        path = project_root / ".profile-run" / f"{tool}-findings.json"
        items: list[dict] = []
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, list):
                    items = [f for f in data if isinstance(f, dict)]
                else:
                    print(f"warning: {path} is not a JSON list; ignored", file=sys.stderr)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        findings[tool] = items
    return findings


def rank(finding: dict) -> int:
    return SEVERITY_RANK.get(str(finding.get("severity", "MEDIUM")).upper(), 2)


def count_by_severity(items: list[dict]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in items:
        counts[SEVERITY_ORDER[rank(f)]] += 1
    return counts


def short_path(path: str) -> str:
    norm = path.replace("\\", "/")
    for marker in ("src/main/java/", "src/test/java/", "src/"):
        idx = norm.find(marker)
        if idx >= 0:
            return norm[idx:]
    return norm


def render(project_root: Path, findings: dict[str, list[dict]],
           min_severity: str | None) -> str:
    total = sum(len(v) for v in findings.values())
    all_counts = count_by_severity([f for v in findings.values() for f in v])

    lines = [
        f"# Static Analysis Report: {project_root.name}",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if min_severity:
        lines.append(f"**Severity filter:** {min_severity} and above")
    lines += [
        "",
        "## Summary",
        "",
        "| Tool | Issues | Critical | High | Medium | Low/Info |",
        "|------|--------|----------|------|--------|----------|",
    ]
    for tool in TOOLS:
        c = count_by_severity(findings[tool])
        lines.append(f"| {TOOL_TITLES[tool]} | {len(findings[tool])} | {c['CRITICAL']} "
                     f"| {c['HIGH']} | {c['MEDIUM']} | {c['LOW'] + c['INFO']} |")
    lines += [
        "",
        f"**Total: {total} issues** | **Critical: {all_counts['CRITICAL']}** "
        f"| **High: {all_counts['HIGH']}** | **Medium: {all_counts['MEDIUM']}**",
        "",
    ]

    for tool in TOOLS:
        items = findings[tool]
        if not items:
            continue
        lines.append(f"## {TOOL_TITLES[tool]} Issues ({len(items)})")
        lines.append("")
        for f in sorted(items, key=lambda x: (rank(x), short_path(str(x.get("file", ""))),
                                              int(x.get("line", 0) or 0))):
            sev = SEVERITY_ORDER[rank(f)]
            loc = f"{short_path(str(f.get('file', 'unknown')))}:{f.get('line', 0)}"
            lines.append(f"- **{sev}** [{loc}] `{f.get('rule', '')}`")
            msg = str(f.get("message", "")).strip()
            if msg:
                lines.append(f"  {msg}")
            lines.append("")

    if total == 0:
        lines.append("No issues found.")
    else:
        lines.append("## Recommendations")
        lines.append("")
        if all_counts["CRITICAL"]:
            lines.append(f"- **{all_counts['CRITICAL']} critical issues** need immediate attention")
        if all_counts["HIGH"]:
            lines.append(f"- **{all_counts['HIGH']} high-severity issues** should be fixed before release")
        if not (all_counts["CRITICAL"] or all_counts["HIGH"]):
            lines.append("- Only medium/low findings — address during regular refactoring")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--min-severity", choices=SEVERITY_ORDER, default=None,
                    help="Keep findings at this severity and above")
    args = ap.parse_args()

    root = args.project_root.resolve()
    if not root.is_dir():
        print(f"error: project root not found: {root}", file=sys.stderr)
        return 1

    findings = load_findings(root)
    if args.min_severity:
        limit = SEVERITY_RANK[args.min_severity]
        findings = {tool: [f for f in items if rank(f) <= limit]
                    for tool, items in findings.items()}

    report = render(root, findings, args.min_severity)
    out = root / "STATICREPORT.md"
    out.write_text(report, encoding="utf-8")

    total = sum(len(v) for v in findings.values())
    print(f"Report written to {out}")
    print(f"Summary: {total} total issues"
          + "".join(f" | {TOOL_TITLES[t]}: {len(findings[t])}" for t in TOOLS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
