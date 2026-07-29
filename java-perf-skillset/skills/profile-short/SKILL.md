---
name: profile-short
description: Быстрый прогон профилирования Java-проекта (2-5 минут) — только критичные ошибки производительности (N+1, unbatched writes, алгоритмическая неэффективность, redundant computation). Обязательно используй этот skill, когда пользователь вызывает /profile-short, просит краткий/быстрый анализ производительности, проверку перед PR или fast feedback. Тонкая обёртка над profile-orchestrator с лимитом 2 packs; полный прогон — /profile, статические линтеры — /profile-static.
---

# Profile Short — Краткий анализ критичных ошибок

## Назначение

Быстрый прогон профилирования, фокус только на **критичных ошибках
производительности**:
- N+1 queries, unbatched writes (pack `data-access`)
- Algorithm inefficiency, redundant computation (pack `cpu-hotpath`)

Время: **2-5 минут** вместо 10-20 для полного прогона.

## Реализация

Это тонкая обёртка: выполняй workflow skill'а **`profile-orchestrator`**
(его SKILL.md — нормативный документ), с тремя отличиями:

1. **Роутер вызывай с `--max-packs 2`**:
   ```bash
   python3 ~/.claude/skills/profile-orchestrator/scripts/route_analysis.py \
     --project-root . --evidence .profile-run/evidence.json --max-packs 2
   ```
   Fallback без evidence-сигналов остаётся стандартным: `data-access` +
   `cpu-hotpath`.
2. В `run-state.json` пиши `"mode": "short"`.
3. Early-stop правило из profile-orchestrator применяй агрессивно: находка
   с `confidence >= 0.85`, объясняющая primary regression, — прекращай
   запуск оставшихся детекторов.

Всё остальное — измерения, profiler, project index, очередь
(`findings_to_queue.py`, порог `confidence >= 0.70`), цикл фиксов,
чекпоинты, git/PR, финальный `PROFILEREPORT.md` — в точности по
`profile-orchestrator`.

## Использование

```bash
/profile-short --project-root /path/to/project    # быстрый анализ
/profile-short --project-root . --resume          # продолжить прерванный прогон
/profile-short --project-root . --force           # с нуля: удалить .profile-run/ и начать заново
```

`--force` — удали `<project-root>/.profile-run/` (только внутреннее
состояние прогона; чекпоинты в нём тоже пропадут — предупреди
пользователя, если они есть) и запусти обычный старт.

## Workflow (сводка)

1. Baseline measurement (initial)
2. Profiler (initial)
3. Project index (кэш по Git SHA)
4. Route analysis — `--max-packs 2` (типично: data-access + cpu-hotpath)
5. Только выбранные детекторы (≤ 10 findings на детектор, early stop)
6. Очередь + apply-recommendations (confidence >= 0.70)
7. Incremental measurement после каждого фикса
8. Отчёт: `PROFILEREPORT.md`

## Отличие от `/profile`

| Аспект | /profile-short | /profile (--full-audit) |
|--------|---|---|
| Время | 2-5 мин | 10-20+ мин |
| Packs | max 2 (по evidence) | все 6 |
| Детекторов | ~4-12 (из выбранных packs) | 22 |
| Early stop | агрессивный | выключен |
| Для | PR checks, fast feedback | release, полный аудит |

## Ограничения

- Не проверяет memory-gc / concurrency / io-observability / cleanup packs,
  если evidence не вывел их в топ-2.
- Max 2 packs, max 10 findings на детектор.
- Находки с `confidence < 0.70` не попадают в очередь фиксов (стандартный
  порог `findings_to_queue.py`).
