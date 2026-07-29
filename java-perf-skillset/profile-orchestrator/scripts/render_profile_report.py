#!/usr/bin/env python3
"""Render the single final human-readable report: PROFILEREPORT.md.

Part of the `profile-orchestrator` Claude Code skill. Reads the unified
JSONL findings contract (.profile-run/findings.jsonl), deduplicates and
sorts findings, and writes PROFILEREPORT.md at the project root — the only
final Markdown report of the system. Per-detector *_report.md files are
deprecated and intentionally ignored.

Usage:
    render_profile_report.py --project-root DIR

Behaviour:
- invalid JSONL lines are skipped (counted, never fatal);
- findings are deduplicated by (category, location.file, location.line,
  suggested_fix) keeping the highest-confidence duplicate;
- sorted by severity (critical > high > medium > low > unknown), then by
  confidence descending;
- an empty/absent findings file still produces a valid report stating that
  no structured findings were collected.

Python 3.10+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
APPLY_MIN_CONFIDENCE = 0.7


def load_findings(path: Path) -> tuple[list[dict], int]:
    """Parse findings.jsonl -> (valid findings, invalid line count)."""
    if not path.is_file():
        return [], 0
    findings: list[dict] = []
    invalid = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if not isinstance(obj, dict) or "id" not in obj:
            invalid += 1
            continue
        findings.append(obj)
    return findings, invalid


def _norm_confidence(finding: dict) -> float:
    value = finding.get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):  # tolerate legacy high/medium/low words
        return {"high": 0.9, "medium": 0.75, "low": 0.4}.get(value.lower(), 0.0)
    return 0.0


def _location(finding: dict) -> tuple[str, object]:
    loc = finding.get("location")
    if isinstance(loc, dict):
        return str(loc.get("file", "?")), loc.get("line", "?")
    return "?", "?"


def dedup(findings: list[dict]) -> tuple[list[dict], int]:
    """Deduplicate by (category, location.file, location.line, suggested_fix),
    keeping the highest-confidence occurrence."""
    best: dict[tuple, dict] = {}
    for f in findings:
        file, line = _location(f)
        key = (str(f.get("category", "")), file, str(line),
               str(f.get("suggested_fix", "")))
        cur = best.get(key)
        if cur is None or _norm_confidence(f) > _norm_confidence(cur):
            best[key] = f
    unique = list(best.values())
    return unique, len(findings) - len(unique)


def sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: (
        SEVERITY_ORDER.get(str(f.get("severity", "unknown")).lower(), 4),
        -_norm_confidence(f),
        str(f.get("id", "")),
    ))


def render_finding(f: dict) -> list[str]:
    file, line = _location(f)
    conf = _norm_confidence(f)
    severity = str(f.get("severity", "unknown")).lower()
    lines = [f"### {f.get('id', '?')} — {severity} (confidence {conf:.2f})", ""]
    meta = [f"- **Category:** {f.get('category', '?')}"]
    if f.get("detector"):
        meta.append(f"- **Detector:** {f['detector']}")
    if f.get("type"):
        meta.append(f"- **Type:** {f['type']}")
    meta.append(f"- **Location:** `{file}:{line}`")
    if conf < APPLY_MIN_CONFIDENCE:
        meta.append(f"- **Note:** ниже порога применения "
                    f"({APPLY_MIN_CONFIDENCE:.2f}) — в apply не передавалась")
    lines.extend(meta)
    evidence = f.get("evidence")
    if isinstance(evidence, list) and evidence:
        lines.append("- **Evidence:**")
        lines.extend(f"  - {item}" for item in evidence)
    elif evidence:
        lines.append(f"- **Evidence:** {evidence}")
    if f.get("suggested_fix"):
        lines += ["", f"**Recommended fix:** {f['suggested_fix']}"]
    verify = f.get("verify")
    if isinstance(verify, dict):
        scenario = verify.get("scenario", "")
        metrics = verify.get("metrics", [])
        metrics_s = ", ".join(map(str, metrics)) if isinstance(metrics, list) else str(metrics)
        lines += ["", f"**Verification:** scenario `{scenario or 'n/a'}`, "
                      f"metrics: {metrics_s or 'n/a'}"]
    elif verify:
        lines += ["", f"**Verification:** {verify}"]
    lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True, type=Path)
    ap.add_argument("--findings", type=Path, default=None,
                    help="Findings JSONL (default: <project-root>/.profile-run/findings.jsonl)")
    ap.add_argument("--output", type=Path, default=None,
                    help="Report path (default: <project-root>/PROFILEREPORT.md)")
    args = ap.parse_args()

    root = args.project_root.resolve()
    if not root.is_dir():
        print(f"error: --project-root {root} is not a directory", file=sys.stderr)
        return 2
    findings_path = args.findings or (root / ".profile-run" / "findings.jsonl")
    if not findings_path.is_absolute():
        findings_path = root / findings_path
    out = args.output or (root / "PROFILEREPORT.md")

    findings, invalid = load_findings(findings_path)
    unique, merged = dedup(findings)
    ordered = sort_findings(unique)

    plan_note = ""
    plan_path = root / ".profile-run" / "analysis-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            packs = ", ".join(plan.get("selected_packs", [])) or "n/a"
            plan_note = (f"- **Analysis packs:** {packs} "
                         f"(mode: {plan.get('mode', 'n/a')}"
                         f"{', fallback routing' if plan.get('fallback_used') else ''})")
        except (json.JSONDecodeError, OSError):
            plan_note = ""

    severity_counts: dict[str, int] = {}
    for f in ordered:
        sev = str(f.get("severity", "unknown")).lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    counts_line = ", ".join(
        f"{sev}: {severity_counts[sev]}"
        for sev in ("critical", "high", "medium", "low", "unknown")
        if sev in severity_counts) or "нет"

    lines = [
        "# PROFILEREPORT",
        "",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- **Findings source:** `{findings_path.name}` "
        f"(единый JSONL-контракт; legacy `*_report.md` не используются)",
    ]
    if plan_note:
        lines.append(plan_note)
    lines.append(f"- **Findings:** {len(ordered)} ({counts_line})")
    if merged:
        lines.append(f"- **Deduplicated:** {merged} повторов схлопнуто")
    if invalid:
        lines.append(f"- **Skipped:** {invalid} невалидных JSONL-строк "
                     f"(проигнорированы, не ошибка)")
    lines.append("")

    if not ordered:
        lines += [
            "## Находки",
            "",
            "Structured findings не были получены: `.profile-run/findings.jsonl` "
            "отсутствует или не содержит валидных записей. Это валидное "
            "состояние — либо анализ не выявил проблем с достаточной "
            "уверенностью, либо детекторы ещё не запускались.",
            "",
        ]
    else:
        lines += ["## Находки", ""]
        for f in ordered:
            lines.extend(render_finding(f))

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"rendered {len(ordered)} findings "
          f"({merged} deduplicated, {invalid} invalid lines skipped)",
          file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
