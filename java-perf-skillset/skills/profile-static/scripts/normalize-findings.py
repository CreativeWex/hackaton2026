#!/usr/bin/env python3
"""Normalize raw linter output (CheckStyle XML / PMD JSON / SpotBugs XML)
into one common findings schema, shared by all three runners:

    [{"tool": "checkstyle|pmd|spotbugs",
      "file": "...", "line": 1, "column": 0,
      "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO",
      "rule": "...", "message": "..."}]

Usage: normalize-findings.py <tool> <raw-input-file> <output-json>

Python 3.10+, stdlib only.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

CHECKSTYLE_SEVERITY = {"error": "HIGH", "warning": "MEDIUM", "info": "INFO"}
PMD_PRIORITY = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "INFO"}


def spotbugs_severity(rank: int) -> str:
    # SpotBugs rank: 1-4 scariest, 5-9 scary, 10-14 troubling, 15-20 of concern
    if rank <= 4:
        return "CRITICAL"
    if rank <= 9:
        return "HIGH"
    if rank <= 14:
        return "MEDIUM"
    return "LOW"


def parse_checkstyle(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    findings = []
    for file_el in root.findall("file"):
        fname = file_el.get("name", "unknown")
        for err in file_el.findall("error"):
            source = err.get("source", "")
            findings.append({
                "tool": "checkstyle",
                "file": fname,
                "line": int(err.get("line", 0) or 0),
                "column": int(err.get("column", 0) or 0),
                "severity": CHECKSTYLE_SEVERITY.get(err.get("severity", "warning"), "MEDIUM"),
                "rule": source.rsplit(".", 1)[-1].removesuffix("Check"),
                "message": err.get("message", ""),
            })
    return findings


def parse_pmd(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    findings = []
    for file_data in data.get("files", []):
        fname = file_data.get("filename", "unknown")
        for v in file_data.get("violations", []):
            findings.append({
                "tool": "pmd",
                "file": fname,
                "line": int(v.get("beginline", 0) or 0),
                "column": int(v.get("begincolumn", 0) or 0),
                "severity": PMD_PRIORITY.get(int(v.get("priority", 3)), "MEDIUM"),
                "rule": v.get("rule", ""),
                "message": (v.get("description") or "").strip(),
            })
    return findings


def parse_spotbugs(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    findings = []
    for bug in root.findall(".//BugInstance"):
        # primary source line: the one marked primary, else the first
        lines = bug.findall("SourceLine")
        primary = next((s for s in lines if s.get("primary") == "true"),
                       lines[0] if lines else None)
        msg_el = bug.find("LongMessage")
        message = (msg_el.text or "").strip() if msg_el is not None else bug.get("type", "")
        findings.append({
            "tool": "spotbugs",
            "file": (primary.get("sourcepath") or primary.get("sourcefile") or "unknown")
                    if primary is not None else "unknown",
            "line": int(primary.get("start", 0) or 0) if primary is not None else 0,
            "column": 0,
            "severity": spotbugs_severity(int(bug.get("rank", 20) or 20)),
            "rule": bug.get("type", ""),
            "message": message or f"{bug.get('abbrev', '')}: {bug.get('type', '')}",
        })
    return findings


PARSERS = {"checkstyle": parse_checkstyle, "pmd": parse_pmd, "spotbugs": parse_spotbugs}


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in PARSERS:
        print(f"Usage: normalize-findings.py <{'|'.join(PARSERS)}> <raw-input> <output-json>",
              file=sys.stderr)
        return 2
    tool, raw, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if not raw.is_file() or raw.stat().st_size == 0:
        print(f"warning: {tool}: raw output {raw} missing or empty; writing []",
              file=sys.stderr)
        findings: list[dict] = []
    else:
        try:
            findings = PARSERS[tool](raw)
        except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
            print(f"error: {tool}: cannot parse {raw}: {exc}", file=sys.stderr)
            return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{tool}: {len(findings)} findings -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
