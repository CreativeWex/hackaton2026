# Форматы отчётов

Каждый запуск skill обязан создать ровно один Markdown-отчёт.
Отчёт краткий и не содержит интерпретации причин изменения производительности
и рекомендаций по оптимизации.

Обязательные элементы любого отчёта:

1. Итоговый verdict.
2. Режим запуска (initial / incremental / final).
3. Текущий Git SHA.
4. Reference Git SHA, если есть.
5. Scenario ID и measurement type.
6. Repeat count и aggregation.
7. Совместимость fingerprint.
8. Таблица: Metric / Reference / Current / Delta / Variation / Verdict.
9. Текстовое объяснение итогового статуса.
10. Пути к result.json и raw artifacts.
11. Список созданных или изменённых файлов.

`scripts/render_report.py` генерирует отчёты по этим шаблонам.

---

## Шаблон: initial

Путь: `.performance/initial/report.md`

```markdown
# Performance report — 📊 BASELINE_CREATED

- **Mode:** initial
- **Run ID:** 2026-07-28T12-00-00Z
- **Git SHA:** 3f9c1ab
- **Scenario:** orders-api-create-order (http)
- **Repeats:** 5, aggregation: median
- **Scenario fingerprint:** `a1b2c3d4e5f60718` — baseline (no reference)
- **Environment fingerprint:** `0f1e2d3c4b5a6978` (Linux/x86_64, 8 CPU, Java 21)

## Metrics

| Metric | Reference | Current | Delta | Variation | Verdict |
|---|---|---|---|---|---|
| **throughput_rps (rps)** | n/a | 120.5 | n/a | 2.10% | n/a |
| **latency_p95_ms (ms)** | n/a | 145.0 | n/a | 3.40% | n/a |
| latency_p99_ms (ms) | n/a | 290.0 | n/a | 5.10% | n/a |
| **error_rate_percent (percent)** | n/a | 0.01 | n/a | 0.00% | n/a |

## Explanation

Initial baseline created successfully.

## Artifacts

- Aggregated result: `.performance/initial/result.json`
- Raw artifacts: `.performance/initial/raw/`

## Created or updated files

- `perf/scenario.yaml`
- `perf/run-performance.sh`
- `perf/run-one.sh`
- `perf/normalize-result.py`
- `perf/README.md`
- `.gitignore`
- `.performance/initial/result.json`
- `.performance/latest/result.json`
```

Для initial колонки Reference/Delta/Verdict в таблице — `n/a`.

---

## Шаблон: incremental

Путь: `.performance/runs/<run-id>/report.md`

```markdown
# Performance report — ✅ BETTER

- **Mode:** incremental
- **Run ID:** 2026-07-29T09-15-00Z-8d2e1f0
- **Git SHA:** 8d2e1f0
- **Reference Git SHA:** 3f9c1ab
- **Reference run:** 2026-07-28T12-00-00Z (.performance/latest/result.json)
- **Scenario:** orders-api-create-order (http)
- **Repeats:** 5, aggregation: median
- **Scenario fingerprint:** `a1b2c3d4e5f60718` — compatible with reference
- **Environment fingerprint:** `0f1e2d3c4b5a6978` (Linux/x86_64, 8 CPU, Java 21)

## Metrics

| Metric | Reference | Current | Delta | Variation | Verdict |
|---|---|---|---|---|---|
| **throughput_rps (rps)** | 120.5 | 138.2 | +14.69% | 2.80% | BETTER |
| **latency_p95_ms (ms)** | 145.0 | 128.4 | -11.45% | 3.10% | BETTER |
| latency_p99_ms (ms) | 290.0 | 275.1 | -5.14% | 6.00% | SAME |
| **error_rate_percent (percent)** | 0.01 | 0.01 | +0.00% | 0.00% | SAME |

## Explanation

At least one primary metric improved beyond 10% with no regression beyond 10%.

## Artifacts

- Aggregated result: `.performance/runs/2026-07-29T09-15-00Z-8d2e1f0/result.json`
- Raw artifacts: `.performance/runs/2026-07-29T09-15-00Z-8d2e1f0/raw/`

## Created or updated files

- `.performance/runs/2026-07-29T09-15-00Z-8d2e1f0/result.json`
- `.performance/runs/2026-07-29T09-15-00Z-8d2e1f0/report.md`
- `.performance/latest/result.json` (updated: valid measurement)
```

Особенности:
- Если вердикт `FAILED`, `NOT_COMPARABLE` или `INCONCLUSIVE`,
  `.performance/latest/result.json` не обновляется — это указывается
  в списке файлов явно (например, «latest/result.json NOT updated»).
- При `NOT_COMPARABLE` таблица метрик может присутствовать, но колонки
  Delta/Verdict — `n/a`, а в Explanation указывается, какой fingerprint
  разошёлся.

---

## Шаблон: final

Путь: `.performance/final/<run-id>/report.md`

```markdown
# Performance report — ✅ BETTER

- **Mode:** final
- **Run ID:** 2026-08-04T17-40-00Z-c0ffee1
- **Git SHA:** c0ffee1
- **Reference Git SHA:** 3f9c1ab
- **Reference run:** 2026-07-28T12-00-00Z (.performance/initial/result.json)
- **Scenario:** orders-api-create-order (http)
- **Repeats:** 5, aggregation: median
- **Scenario fingerprint:** `a1b2c3d4e5f60718` — compatible with reference
- **Environment fingerprint:** `0f1e2d3c4b5a6978` (Linux/x86_64, 8 CPU, Java 21)

## Metrics

| Metric | Reference | Current | Delta | Variation | Verdict |
|---|---|---|---|---|---|
| **throughput_rps (rps)** | 120.5 | 151.7 | +25.89% | 2.20% | BETTER |
| **latency_p95_ms (ms)** | 145.0 | 112.3 | -22.55% | 2.90% | BETTER |
| latency_p99_ms (ms) | 290.0 | 231.0 | -20.34% | 4.70% | BETTER |
| **error_rate_percent (percent)** | 0.01 | 0.00 | -100.00% | 0.00% | BETTER |

## Explanation

At least one primary metric improved beyond 10% with no regression beyond 10%.
Comparison performed against the initial baseline; the baseline was not modified.

## Artifacts

- Aggregated result: `.performance/final/2026-08-04T17-40-00Z-c0ffee1/result.json`
- Raw artifacts: `.performance/final/2026-08-04T17-40-00Z-c0ffee1/raw/`

## Created or updated files

- `.performance/final/2026-08-04T17-40-00Z-c0ffee1/result.json`
- `.performance/final/2026-08-04T17-40-00Z-c0ffee1/report.md`
```

Особенности:
- Reference — всегда `.performance/initial/result.json`.
- `initial/` и `latest/` не модифицируются в режиме final.

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
