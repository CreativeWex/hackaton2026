# Форматы отчётов

Каждый запуск skill'а обязан создать ровно один Markdown-отчёт. Отчёт
краткий и не содержит интерпретации причины находки и рекомендаций по
исправлению — это зона другого skill'а, который читает `findings.json`.

Обязательные элементы любого отчёта:

1. Итоговый verdict.
2. Режим запуска (initial / incremental / final).
3. Текущий Git SHA.
4. Reference Git SHA, если есть.
5. Scenario ID.
6. Число снятых снимков / ожидаемое, длительность, конкурентность.
7. Совместимость fingerprint.
8. Таблица: Finding / Reference / Current / Delta / Verdict.
9. Текстовое объяснение итогового статуса.
10. Пути к findings.json и raw artifacts.
11. Список созданных или изменённых файлов.

`scripts/render-report.py` генерирует отчёты по этим шаблонам.

---

## Шаблон: initial

Путь: `.profiler/initial/report.md`

```markdown
# Profiler report — 📊 BASELINE_CREATED

- **Mode:** initial
- **Run ID:** 2026-07-28T12-00-00Z
- **Git SHA:** 3f9c1ab
- **Scenario:** sensorhub-mixed-load
- **Snapshots:** 4/4, duration 60s, concurrency 8
- **Profile fingerprint:** `7a0613ae4793c60d` — baseline (no reference)
- **Environment fingerprint:** `e24633ef1ba7c0cd` (Linux/x86_64, 8 CPU, Java 21)

## Findings

| Finding | Reference | Current | Delta | Verdict |
|---|---|---|---|---|
| **heap-growth** (heap_leak, high) | n/a | 58.59 mb | n/a | n/a |

## Explanation

Initial findings baseline created successfully

## Artifacts

- Findings: `.profiler/initial/findings.json`
- Raw artifacts: `.profiler/initial/raw`

## Created or updated files

- `profiler/scenario.yaml`
- `profiler/collect.sh`
- `profiler/run-profiler.sh`
- `profiler/README.md`
- `.gitignore`
- `.profiler/initial/findings.json`
- `.profiler/latest/findings.json`
```

Если находок нет вообще — таблица содержит одну строку `| _none_ |  |  |  |  |`.

---

## Шаблон: incremental

Путь: `.profiler/runs/<run-id>/report.md`

```markdown
# Profiler report — ✅ BETTER

- **Mode:** incremental
- **Run ID:** 2026-07-29T09-15-00Z-8d2e1f0
- **Git SHA:** 8d2e1f0
- **Reference Git SHA:** 3f9c1ab
- **Reference run:** 2026-07-28T12-00-00Z (.profiler/latest/findings.json)
- **Scenario:** sensorhub-mixed-load
- **Snapshots:** 4/4, duration 60s, concurrency 8
- **Profile fingerprint:** `7a0613ae4793c60d` — compatible with reference
- **Environment fingerprint:** `e24633ef1ba7c0cd` (Linux/x86_64, 8 CPU, Java 21)

## Findings

| Finding | Reference | Current | Delta | Verdict |
|---|---|---|---|---|
| **heap-growth** (heap_leak, high) | 58.59 mb | resolved | n/a | RESOLVED |

## Explanation

At least one finding resolved or improved, none regressed or appeared new

## Artifacts

- Findings: `.profiler/runs/2026-07-29T09-15-00Z-8d2e1f0/findings.json`
- Raw artifacts: `.profiler/runs/2026-07-29T09-15-00Z-8d2e1f0/raw`

## Created or updated files

- `.profiler/runs/2026-07-29T09-15-00Z-8d2e1f0/findings.json`
- `.profiler/runs/2026-07-29T09-15-00Z-8d2e1f0/report.md`
- `.profiler/latest/findings.json` (updated: valid run)
```

Особенности:
- Если вердикт `FAILED`, `NOT_COMPARABLE` или `INCONCLUSIVE`,
  `.profiler/latest/findings.json` не обновляется — указывай это явно в
  списке файлов (например, «latest/findings.json NOT updated»).
- `RESOLVED`-находки (были в reference, отсутствуют сейчас) показываются в
  таблице отдельной строкой с `Current: resolved` — они не входят в текущий
  `findings.json`, только в `comparison`.
- `NEW`-находки (появились только сейчас) — `Reference: n/a`.
- При `NOT_COMPARABLE` таблица находок может присутствовать (текущие
  находки без сравнения), но Delta/Verdict — `n/a`, а Explanation объясняет,
  какой fingerprint разошёлся.

---

## Шаблон: final

Путь: `.profiler/final/<run-id>/report.md`

```markdown
# Profiler report — ✅ BETTER

- **Mode:** final
- **Run ID:** 2026-08-04T17-40-00Z-c0ffee1
- **Git SHA:** c0ffee1
- **Reference Git SHA:** 3f9c1ab
- **Reference run:** 2026-07-28T12-00-00Z (.profiler/initial/findings.json)
- **Scenario:** sensorhub-mixed-load
- **Snapshots:** 4/4, duration 60s, concurrency 8
- **Profile fingerprint:** `7a0613ae4793c60d` — compatible with reference
- **Environment fingerprint:** `e24633ef1ba7c0cd` (Linux/x86_64, 8 CPU, Java 21)

## Findings

| Finding | Reference | Current | Delta | Verdict |
|---|---|---|---|---|
| **heap-growth** (heap_leak, high) | 58.59 mb | resolved | n/a | RESOLVED |
| **deadlock-d5156762** (deadlock, critical) | n/a | n/a | n/a | n/a |

## Explanation

At least one finding resolved or improved, none regressed or appeared new.
Comparison performed against the initial baseline; the baseline was not modified.

## Artifacts

- Findings: `.profiler/final/2026-08-04T17-40-00Z-c0ffee1/findings.json`
- Raw artifacts: `.profiler/final/2026-08-04T17-40-00Z-c0ffee1/raw`

## Created or updated files

- `.profiler/final/2026-08-04T17-40-00Z-c0ffee1/findings.json`
- `.profiler/final/2026-08-04T17-40-00Z-c0ffee1/report.md`
```

Особенности:
- Reference — всегда `.profiler/initial/findings.json`.
- `initial/` и `latest/` не модифицируются в режиме final.
- Если между initial и final появилась находка, которую incremental-цепочка
  уже показывала как WORSE/NEW и она так и осталась нерешённой к final —
  это законный результат: final отражает совокупный итог, а не гарантирует,
  что всё улучшилось.

---

## Эмодзи вердиктов

| Verdict | Эмодзи |
|---|---|
| BASELINE_CREATED | 📊 |
| BETTER | ✅ |
| WORSE | ❌ |
| SAME | ➖ |
| MIXED | ⚠️ |
| INCONCLUSIVE | ❓ |
| NOT_COMPARABLE | 🚫 |
| FAILED | 💥 |
