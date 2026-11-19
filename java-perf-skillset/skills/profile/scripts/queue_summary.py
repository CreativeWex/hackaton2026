#!/usr/bin/env python3
"""Summarize the final state of the /profile work queue for the PR report.

Part of the `profile` Claude Code skill.

Usage:
    queue_summary.py --queue .profile-run/queue.json --output .profile-run/queue-summary.md

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUS_LABEL = {
    "committed": "Исправлено и закоммичено",
    "skipped-resolved": "Пропущено — находка уже была неактуальна на момент фикса",
    "skipped-blocked": "Пропущено — конфликт с проектным правилом",
    "skipped-3-attempts": "Пропущено — 3 попытки не дали улучшения",
    "skipped-infra": "Пропущено — инфраструктурная проблема при верификации, не связано с самой правкой",
    "pending": "Не обработано (очередь прервана раньше времени)",
    "in_progress": "Не завершено (очередь прервана раньше времени)",
}


def render(data: dict[str, Any]) -> str:
    items = data.get("items", [])
    by_status: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_status.setdefault(it["status"], []).append(it)

    lines: list[str] = []
    lines.append("# Итог обработки очереди")
    lines.append("")
    lines.append(f"- Всего находок в очереди: {len(items)}")
    for status in ("committed", "skipped-resolved", "skipped-blocked", "skipped-3-attempts", "skipped-infra", "pending", "in_progress"):
        count = len(by_status.get(status, []))
        if count:
            lines.append(f"- {STATUS_LABEL[status]}: {count}")
    lines.append("")

    if by_status.get("committed"):
        lines.append("## Закоммиченные исправления")
        lines.append("")
        lines.append("| Находка | Отчёт | Severity | Метрика | Дельта | Commit |")
        lines.append("|---|---|---|---|---|---|")
        for it in by_status["committed"]:
            last_attempt = (it.get("attempts") or [{}])[-1]
            metric = last_attempt.get("metric", "n/a")
            delta = last_attempt.get("deltaPercent")
            delta_s = f"{delta:+.2f}%" if isinstance(delta, (int, float)) else "n/a"
            lines.append(
                f"| {it['findingId']} | {it['reportFile']} | {it['severity']} | "
                f"{metric} | {delta_s} | `{it.get('commitSha', 'n/a')}` |"
            )
        lines.append("")

    for status in ("skipped-3-attempts", "skipped-blocked", "skipped-infra"):
        rows = by_status.get(status)
        if not rows:
            continue
        lines.append(f"## {STATUS_LABEL[status]}")
        lines.append("")
        for it in rows:
            lines.append(f"### {it['findingId']} ({it['reportFile']})")
            lines.append("")
            attempts = it.get("attempts", [])
            if attempts:
                for a in attempts:
                    lines.append(f"- попытка {a.get('attemptNumber', '?')}: "
                                  f"вердикт {a.get('verdict', 'n/a')}"
                                  + (f", {a.get('metric')} {a.get('deltaPercent')}%"
                                     if a.get('metric') else "")
                                  + (f" — {a['note']}" if a.get('note') else ""))
            else:
                lines.append("- без записанных попыток")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    data = json.loads(args.queue.read_text(encoding="utf-8"))
    report = render(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(str(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
