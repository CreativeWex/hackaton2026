---
name: profile-orchestrator
description: >
  Предпочтительная точка входа полного цикла анализа и исправления
  неоптимального Java-кода — evidence-driven замена legacy-режима /profile
  «всегда все 22 детектора». По очереди: java-performance-discovery,
  baseline-измерение и baseline-профилирование, однократный кэшируемый
  project index (build_project_index.py, кэш по Git SHA), компактный
  evidence.json, router (route_analysis.py) выбирает максимум 3 analysis
  packs, запускаются только выбранные find-* детекторы, findings копятся в
  едином JSONL-контракте .profile-run/findings.jsonl (без промежуточных
  Markdown-отчётов), затем очередь приоритетных дедуплицированных находок
  (findings_to_queue.py, confidence >= 0.70) и цикл фиксов через
  apply-recommendations с verify-измерением, в конце — final measurement и
  единственный финальный отчёт PROFILEREPORT.md
  (render_profile_report.py). Обязательно используй этот skill, когда
  пользователь вызывает `/profile-orchestrator`, просит полный
  автоматический анализ и исправление Java-проекта, «профилируй и почини»,
  evidence-driven прогон, либо вызывает `/profile` (legacy-алиас —
  делегирует сюда с --full). Поддерживает --full (добавляет pack cleanup,
  лимит 3 packs сохраняется) и --full-audit (явный полный аудит всеми
  packs). Измерения, профайлер, чекпоинты, откат и guard hook — те же, что
  у /profile, без изменений.
---

# Profile Orchestrator

## Назначение

Evidence-driven дирижёр системы. Отличие от legacy `/profile`: вместо
безусловного последовательного запуска всех 22 `find-*` skill'ов —
маршрутизация по фактическим сигналам baseline-измерения и профайлера к
максимум 3 пакетам анализаторов, единый JSONL-контракт находок вместо 22
промежуточных Markdown-отчётов и однократный кэшируемый индекс проекта
вместо повторного discovery в каждом skill'е. Это снижает и latency, и
token usage всего прогона, не меняя механику measurement / profiler /
checkpoints / rollback / guard hook.

Вход: путь к корню Java-проекта (по умолчанию — текущая директория).
Флаги: `--full` (добавить pack `cleanup`; лимит «максимум 3 packs»
сохраняется — cleanup занимает один из трёх слотов), `--full-audit`
(явный полный аудит: все packs; документированный наследник legacy
поведения `/profile`, никогда не по умолчанию), `--resume` (как у
`/profile`).

Выход: тот же, что у `/profile` (ветка/коммиты/PR при доступном git,
иначе правки в рабочем дереве + чекпоинты), но единственный финальный
Markdown-отчёт — **`PROFILEREPORT.md`** в корне проекта.

## Workflow

```
discovery
  -> baseline measurement
  -> profiler
  -> build project index          (однократно, кэш по Git SHA)
  -> route analysis packs         (max 3, по evidence)
  -> run only selected detectors  (JSONL findings, <= 10 на детектор)
  -> aggregate and deduplicate JSONL findings
  -> apply recommendations        (только confidence >= 0.70)
  -> incremental measurement      (после каждого фикса)
  -> final report                 (PROFILEREPORT.md)
```

## Analysis packs

| Pack | Legacy skills (детекторы) |
|---|---|
| `data-access` | find-query-issues, find-missing-batching, find-orm-fetch-strategy-issues, find-over-fetching-api, find-unbounded-data-loading, find-missing-caching |
| `cpu-hotpath` | find-algorithm-inefficiency, find-inefficient-api-usage, find-redundant-computation, find-redundant-checks, find-reflection-in-hot-path, find-regex-issues |
| `memory-gc` | find-gc-pressure, find-data-layout-waste, find-resource-management-issues, find-unbounded-cache-or-queue |
| `concurrency` | find-concurrency-issues, find-transaction-locking-issues, find-cache-locality-issues |
| `io-observability` | find-logging-overhead, find-exceptions-as-control-flow |
| `cleanup` | find-dead-code |

## Политика запуска (жёсткие правила)

- Максимум **3 analysis packs** за один стандартный прогон.
- `cleanup` запускается только при явном `--full` / `full_scan` /
  `--full-audit` — никогда по evidence.
- Evidence отсутствует или не дал сигналов → fallback: `data-access` +
  `cpu-hotpath` (роутер делает это сам и помечает `fallback_used: true`).
- Каждый детектор добавляет не более **10 findings** за прогон.
- В apply-recommendations передаются только дедуплицированные находки с
  `confidence >= 0.70` и непустым `suggested_fix` (фильтрует
  `findings_to_queue.py` — не пропускай его).
- **Early stop:** если уже записана находка с `confidence >= 0.85`,
  которая объясняет primary regression (та же метрика/сценарий, что и
  главный сигнал evidence), — не запускай оставшиеся детекторы/packs,
  переходи к агрегации и фиксам. Не применяется при `--full` /
  `--full-audit` (пользователь явно попросил широкий прогон).
- Никогда не запускай все 22 детектора по умолчанию.
- Детекторы не пишут Markdown — только JSONL. Промежуточные `*_report.md`
  не создаются; `PROFILEREPORT.md` — единственный финальный
  Markdown-отчёт.

## Артефакты прогона (все — в `<project-root>/.profile-run/`)

| Файл | Кто пишет | Что содержит |
|---|---|---|
| `project-index.json` | `build_project_index.py` | структурный индекс проекта, кэш по `git_sha` |
| `evidence.json` | этот оркестратор (шаг 4) | компактные числовые сигналы из measurement/profiler |
| `analysis-plan.json` | `route_analysis.py` | выбранные packs, скоринг, findings-контракт |
| `findings.jsonl` | детекторы (append) | по одному JSON-объекту находки на строку |
| `queue.json` | `findings_to_queue.py` | очередь фиксов в legacy-формате Фазы 3 `/profile` |
| `run-state.json`, `ACTIVE`, `checkpoints/`, `snapshot-tmp/` | как в `/profile` | без изменений |

Скрипты этого skill'а: `~/.claude/skills/profile-orchestrator/scripts/`
(`build_project_index.py`, `route_analysis.py`, `findings_to_queue.py`,
`render_profile_report.py`). Скрипты очереди/чекпоинтов — из skill'а
`profile`: `~/.claude/skills/profile/scripts/` (`queue_next.py`,
`queue_update.py`, `queue_summary.py`, `checkpoint_save.py`,
`checkpoint_revert.py`) — используются как есть. Интерпретатор Python —
как в `profile/SKILL.md`: `python3` / `py -3` / `python` (3.10+).

## Фаза 0 — подготовка

Полностью по `profile/SKILL.md`, Фаза 0 (git-проверки, ветка,
`.gitignore` с `.profile-run/`, `run-state.json`, resume-логика). Одно
отличие: в `run-state.json` дополнительно пиши `"orchestrator":
"profile-orchestrator"` и `"mode": "standard"|"full"|"full-audit"`.

## Фаза 1 — baseline и маршрутизация

1. `java-performance-discovery` → `performance_discovery.md`.
2. `java-performance-measurement`, режим `initial` →
   `.performance/initial/result.json`, `.performance/latest/result.json`.
3. `profiler`, режим `initial` → `.profiler/initial/findings.json`,
   `.profiler/latest/findings.json`.
4. **Project index** (однократно):
   ```bash
   python3 ~/.claude/skills/profile-orchestrator/scripts/build_project_index.py --project-root .
   ```
   Повторный вызов при неизменном Git SHA переиспользует кэш; после
   собственных правок кода в этом же прогоне пересборка не нужна — индекс
   структурный, а очередь уже построена.
5. **Собери `.profile-run/evidence.json`** — компактный JSON только из
   чисел/коротких списков, прочитанных из
   `.performance/latest/result.json` и `.profiler/latest/findings.json`
   (не вставляй сырые отчёты целиком):
   ```json
   {
     "baseline": {"sql_count": 248, "p95_ms": 145.0, "cpu_pct": 35},
     "profiler": {"gc_pause_ms": 30, "heap_growth_mb": 12,
                  "blocked_ms": 0, "exception_count": 4,
                  "cpu_hotspots": ["ReportService.buildDaily"]}
   }
   ```
   Клади туда те сигналы, которые реально есть в результатах; известные
   роутеру ключи: `sql_count`/`jdbc_samples` (data-access),
   `cpu_hotspots`/`cpu_pct` (cpu-hotpath),
   `allocation_rate`/`gc_pause_ms`/`heap_growth_mb` (memory-gc),
   `blocked_ms`/`lock_contention` (concurrency),
   `logging_samples`/`exception_count` (io-observability); допустим и
   camelCase, и плоский JSON без `baseline`/`profiler`.
6. **Router:**
   ```bash
   python3 ~/.claude/skills/profile-orchestrator/scripts/route_analysis.py \
     --project-root . --evidence .profile-run/evidence.json [--full|--full-audit]
   ```
   → `.profile-run/analysis-plan.json`. Прочитай `selected_packs` и
   `skills` — это единственный список детекторов на запуск.
7. **profiler-find-problem** — вызывай только если baseline-прогон
   профайлера дал находки (`.profiler/latest/findings.json` непуст). В
   этом workflow попроси его записать результат теми же JSONL-строками в
   `.profile-run/findings.jsonl` (`category` — по смыслу находки,
   `detector: "profiler-find-problem"`), а не `profiler_report.md` —
   Markdown-отчёт в оркестрированном прогоне не нужен.
8. Запусти **только выбранные детекторы**, последовательно, pack за
   pack'ом в порядке `selected_packs`. Каждый вызов — через `Skill` с
   аргументами:
   `detector mode; pack=<pack>; plan=.profile-run/analysis-plan.json; index=.profile-run/project-index.json; evidence=.profile-run/evidence.json`.
   Детектор сам проверит план, прочитает индекс вместо повторного
   discovery и допишет `<= 10` строк в `.profile-run/findings.jsonl`.
   После каждого детектора проверяй early stop (см. политику выше).
9. Если git доступен — один коммит на всю фазу, как в `/profile` Фаза 1
   шаг 6. Обнови `run-state.json: phase1Complete: true`.

## Фаза 2 — агрегация и очередь

```bash
python3 ~/.claude/skills/profile-orchestrator/scripts/findings_to_queue.py \
  --project-root . --merge-from .profile-run/queue.json
```

Скрипт сам: отбрасывает `confidence < 0.70` и находки без
`suggested_fix`, дедуплицирует (точные дубли + QG-merge по `file:line` в
пределах 3 строк), ограничивает 10 находками на pack, сортирует по
severity/confidence и переносит статусы при resume. Затем создай маркер
`.profile-run/ACTIVE` (guard hook — как в `/profile`) и обнови
`run-state.json: phase2Complete: true`. Пустая очередь → сразу Фаза 4.

## Фаза 3 — цикл исправлений

Выполняй в точности Фазу 3 из `profile/SKILL.md` (снимок «до» →
`apply-recommendations` → сборка → incremental measurement/profiler по
`verificationTrack` → BETTER/SAME: `checkpoint_save.py` + коммит;
WORSE/MIXED: откат и retry с фидбэком, максимум 3 попытки; те же статусы
`queue_update.py`), с одним отличием — **вход apply-recommendations**: у
элемента очереди есть поле `finding` (полный JSON-объект контракта) —
передавай его inline в аргументах `Skill`-вызова
(`apply-recommendations` понимает такой вход, см. его раздел «Вход из
profile-orchestrator»), а не ссылку на `*_report.md`.

## Фаза 4 — финальные измерения и отчёт

1. `java-performance-measurement`, режим `final`.
2. `profiler`, режим `final`.
3. Рендер единственного финального отчёта:
   ```bash
   python3 ~/.claude/skills/profile-orchestrator/scripts/render_profile_report.py --project-root .
   ```
   → `PROFILEREPORT.md` в корне проекта (дедупликация, сортировка по
   severity/confidence, невалидные JSONL-строки игнорируются). Затем
   допиши в конец `PROFILEREPORT.md` разделы: итоговые метрики
   до/после из `final`-прогонов measurement/profiler, сводку очереди
   (`queue_summary.py`), список чекпоинтов и инструкцию отката
   (`checkpoint_revert.py --project-root . --last N`) — как в `/profile`
   Фаза 4 шаг 4. Не создавай других Markdown-отчётов.
4. Дальше — git/push/PR в точности по `profile/SKILL.md` Фаза 4, шаги
   5-11, с заменой `PROFILE_REPORT.md` → `PROFILEREPORT.md` (в т.ч.
   `--body-file PROFILEREPORT.md`). Удаление маркера
   `.profile-run/ACTIVE` обязательно в обоих исходах (git есть/нет).

## Безопасность

Всё из раздела «Безопасность» `profile/SKILL.md`, плюс никогда не:
- запускай детектор, чей pack не в `selected_packs` (кроме явной просьбы
  пользователя запустить конкретный skill);
- пропускай построение project index или evidence.json «для скорости» —
  роутер без evidence честно уйдёт в fallback, но не выдумывай evidence;
- позволяй детектору писать Markdown-отчёт или сканировать проект заново
  — вход детектора: индекс + evidence + конкретные файлы;
- передавай в apply-recommendations находки с `confidence < 0.70` или без
  `suggested_fix`;
- создавай `*_report.md` — единственный финальный Markdown:
  `PROFILEREPORT.md`.

## Перед завершением

Проверь:
- `project-index.json`, `evidence.json`, `analysis-plan.json`,
  `findings.jsonl` существуют в `.profile-run/` (findings.jsonl может
  отсутствовать только если детекторы не нашли ничего — тогда в
  PROFILEREPORT.md об этом сказано явно);
- запускались только детекторы из `selected_packs`, `<= 3` packs (или
  задокументированный `--full-audit`);
- очередь строилась `findings_to_queue.py`, а не legacy
  `build_queue.py`;
- инварианты Фазы 3 из `profile/SKILL.md` соблюдены (чекпоинт на каждый
  принятый фикс, verify перед принятием, лимит попыток);
- `PROFILEREPORT.md` — единственный созданный Markdown-отчёт, содержит
  находки, метрики final-прогонов и инструкцию отката;
- маркер `.profile-run/ACTIVE` удалён;
- последняя строка ответа — URL PR либо путь к `PROFILEREPORT.md`.
