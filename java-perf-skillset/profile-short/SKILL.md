# Profile Short — Краткий анализ критичных ошибок

## Назначение

Быстрый прогон профилирования, фокус только на **критичных ошибках производительности**:
- N+1 queries (data-access)
- Unbatched writes (data-access)  
- Algorithm inefficiency (cpu-hotpath)
- Redundant computation (cpu-hotpath)

Выбирает max 2 packs автоматически по evidence.
Время: **2-5 минут** вместо 10-20 для полного прогона.

## Использование

```bash
/profile-short --project-root /path/to/project
```

Аргументы:
- `--project-root` — путь к Java проекту (обязательный)
- `--resume` — продолжить прерванный прогон
- `--force` — перезапустить с нуля

## Workflow

1. ✅ Baseline measurement (initial)
2. ✅ Profiler (initial)  
3. ✅ Project index (cache)
4. ✅ Route analysis (max 2 packs: data-access + cpu-hotpath)
5. ✅ Run only critical detectors:
   - find-query-issues (N+1)
   - find-missing-batching (unbatched writes)
   - find-algorithm-inefficiency (hotspots)
   - find-redundant-computation (wasted work)
6. ✅ Apply recommendations (confidence >= 0.75)
7. ✅ Incremental measurement (verify fixes)
8. ✅ Report: PROFILEREPORT.md

## Выход

- `PROFILEREPORT.md` — краткий отчет с найденными ошибками и исправлениями
- `.profile-run/` — артефакты анализа
- Checkpoints for each applied fix

## Отличие от `/profile`

| Аспект | /profile-short | /profile |
|--------|---|---|
| Время | 2-5 мин | 10-20 мин |
| Packs | max 2 (data-access, cpu-hotpath) | все 6 packs |
| Детекторов | ~4 (критичные) | 22 |
| Findings | только high/critical | все |
| Для | PR checks, fast feedback | release |

## Реализация

Использует `profile-orchestrator` с параметрами:
- Fallback если нет evidence: data-access + cpu-hotpath
- Max findings: 10 per detector
- Early stop at confidence >= 0.85
- Applies only confidence >= 0.75

Скрипты:
- `~/.claude/skills/profile/scripts/` (profile-orchestrator)
- `~/.claude/skills/profile-orchestrator/scripts/`

## Примеры

```bash
# Быстрый анализ
/profile-short --project-root .

# Продолжить прерванный прогон
/profile-short --project-root . --resume

# С нуля (очистить артефакты)
/profile-short --project-root . --force
```

## Ограничения

- Не проверяет memory/gc проблемы (только data-access + cpu-hotpath)
- Не выполняет cleanup анализ (dead code)
- Max 2 packs, max 10 findings на детектор
- Пропускает findings с confidence < 0.70
