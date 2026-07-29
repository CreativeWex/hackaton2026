#!/usr/bin/env python3
"""
Aggregate static analysis findings from CheckStyle, PMD, SpotBugs
and render unified STATICREPORT.md
"""

import json
import sys
import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

def load_findings(project_root: str) -> Dict[str, List[Dict]]:
    """Load findings from all three linters"""
    findings = {
        'checkstyle': [],
        'pmd': [],
        'spotbugs': []
    }

    profile_run = Path(project_root) / '.profile-run'

    # Load CheckStyle findings
    cs_file = profile_run / 'checkstyle-findings.json'
    if cs_file.exists():
        try:
            with open(cs_file) as f:
                cs_data = json.load(f)
                # CheckStyle returns list of files with violations
                for file_data in cs_data:
                    for violation in file_data.get('violations', []):
                        findings['checkstyle'].append({
                            'file': file_data.get('name', 'unknown'),
                            'line': violation.get('line', 0),
                            'column': violation.get('column', 0),
                            'message': violation.get('message', ''),
                            'severity': violation.get('severity', 'warning').upper(),
                            'rule': violation.get('rule', ''),
                            'source': violation.get('source', '')
                        })
        except Exception as e:
            print(f"Error loading CheckStyle findings: {e}", file=sys.stderr)

    # Load PMD findings
    pmd_file = profile_run / 'pmd-findings.json'
    if pmd_file.exists():
        try:
            with open(pmd_file) as f:
                pmd_data = json.load(f)
                for file_data in pmd_data.get('files', []):
                    for violation in file_data.get('violations', []):
                        findings['pmd'].append({
                            'file': file_data.get('filename', 'unknown'),
                            'line': violation.get('line', 0),
                            'column': violation.get('column', 0),
                            'message': violation.get('message', ''),
                            'severity': violation.get('priority', 3),
                            'rule': violation.get('rule', ''),
                            'ruleSet': violation.get('ruleSet', '')
                        })
        except Exception as e:
            print(f"Error loading PMD findings: {e}", file=sys.stderr)

    # Load SpotBugs findings
    sb_file = profile_run / 'spotbugs-findings.json'
    if sb_file.exists():
        try:
            with open(sb_file) as f:
                sb_data = json.load(f)
                for bug in sb_data:
                    severity_map = {1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW'}
                    findings['spotbugs'].append({
                        'file': bug.get('file', 'unknown'),
                        'line': bug.get('line', 0),
                        'type': bug.get('type', ''),
                        'category': bug.get('category', ''),
                        'priority': bug.get('priority', 2),
                        'severity': severity_map.get(bug.get('priority', 2), 'MEDIUM'),
                        'message': f"{bug.get('abbrev', '')}: {bug.get('type', '')}"
                    })
        except Exception as e:
            print(f"Error loading SpotBugs findings: {e}", file=sys.stderr)

    return findings

def severity_level(severity: Any) -> int:
    """Convert severity to numeric level for sorting"""
    if isinstance(severity, str):
        levels = {'CRITICAL': 1, 'HIGH': 2, 'MEDIUM': 3, 'LOW': 4, 'WARNING': 5, 'INFO': 6}
        return levels.get(severity.upper(), 5)
    elif isinstance(severity, int):
        return severity
    return 5

def render_report(project_root: str, findings: Dict[str, List[Dict]]) -> str:
    """Generate markdown report"""

    total_issues = sum(len(f) for f in findings.values())
    critical_count = sum(1 for f in findings['checkstyle'] if severity_level(f.get('severity')) == 1)
    critical_count += sum(1 for f in findings['pmd'] if f.get('severity', 3) <= 2)
    critical_count += sum(1 for f in findings['spotbugs'] if f.get('priority', 2) <= 1)

    high_count = sum(1 for f in findings['checkstyle'] if severity_level(f.get('severity')) == 2)
    high_count += sum(1 for f in findings['pmd'] if f.get('severity', 3) == 3)
    high_count += sum(1 for f in findings['spotbugs'] if f.get('priority', 2) == 2)

    project_name = Path(project_root).name

    report = f"""# Static Analysis Report: {project_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

| Tool | Issues | Critical | High | Medium |
|------|--------|----------|------|--------|
| CheckStyle | {len(findings['checkstyle'])} | {sum(1 for f in findings['checkstyle'] if severity_level(f.get('severity')) <= 1)} | {sum(1 for f in findings['checkstyle'] if severity_level(f.get('severity')) == 2)} | {sum(1 for f in findings['checkstyle'] if severity_level(f.get('severity')) == 3)} |
| PMD | {len(findings['pmd'])} | {sum(1 for f in findings['pmd'] if f.get('severity', 3) <= 2)} | {sum(1 for f in findings['pmd'] if f.get('severity', 3) == 3)} | {sum(1 for f in findings['pmd'] if f.get('severity', 3) == 4)} |
| SpotBugs | {len(findings['spotbugs'])} | {sum(1 for f in findings['spotbugs'] if f.get('priority', 2) <= 1)} | {sum(1 for f in findings['spotbugs'] if f.get('priority', 2) == 2)} | {sum(1 for f in findings['spotbugs'] if f.get('priority', 2) >= 3)} |

**Total: {total_issues} issues** | **Critical: {critical_count}** | **High: {high_count}**

"""

    if findings['checkstyle']:
        report += f"## CheckStyle Issues ({len(findings['checkstyle'])})\n\n"
        for f in sorted(findings['checkstyle'], key=lambda x: (severity_level(x.get('severity')), x.get('file', ''))):
            report += f"- **{f.get('severity', 'WARNING')}** [{f.get('file')}:{f.get('line')}]\n"
            report += f"  {f.get('message', '')}\n"
            report += f"  Rule: `{f.get('rule', 'unknown')}`\n\n"

    if findings['pmd']:
        report += f"## PMD Issues ({len(findings['pmd'])})\n\n"
        severity_names = {1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW', 5: 'INFO'}
        for f in sorted(findings['pmd'], key=lambda x: (x.get('severity', 3), x.get('file', ''))):
            sev = severity_names.get(f.get('severity', 3), 'MEDIUM')
            report += f"- **{sev}** [{f.get('file')}:{f.get('line')}]\n"
            report += f"  {f.get('message', '')}\n"
            report += f"  Rule: `{f.get('ruleSet', 'unknown')}`\n\n"

    if findings['spotbugs']:
        report += f"## SpotBugs Issues ({len(findings['spotbugs'])})\n\n"
        for f in sorted(findings['spotbugs'], key=lambda x: (x.get('priority', 2), x.get('file', ''))):
            report += f"- **{f.get('severity', 'MEDIUM')}** [{f.get('file')}:{f.get('line')}]\n"
            report += f"  {f.get('message', '')}\n"
            report += f"  Category: `{f.get('category', 'unknown')}`\n\n"

    if total_issues == 0:
        report += "✅ **No issues found!**\n"
    else:
        report += f"\n## Recommendations\n\n"
        if critical_count > 0:
            report += f"⚠️ **{critical_count} critical issues** need immediate attention\n"
        if high_count > 0:
            report += f"⚠️ **{high_count} high-severity issues** should be fixed before release\n"

    return report

def main():
    if len(sys.argv) < 2:
        print("Usage: render-static-report.py <project-root>", file=sys.stderr)
        sys.exit(1)

    project_root = sys.argv[1]

    if not Path(project_root).exists():
        print(f"Error: Project root not found: {project_root}", file=sys.stderr)
        sys.exit(1)

    # Load findings
    findings = load_findings(project_root)

    # Render report
    report = render_report(project_root, findings)

    # Write to file
    output_file = Path(project_root) / 'STATICREPORT.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✅ Report written to {output_file}")

    # Summary
    total = sum(len(f) for f in findings.values())
    print(f"Summary: {total} total issues found")
    print(f"  - CheckStyle: {len(findings['checkstyle'])}")
    print(f"  - PMD: {len(findings['pmd'])}")
    print(f"  - SpotBugs: {len(findings['spotbugs'])}")

if __name__ == '__main__':
    main()
