# Java Performance Skillset

Замкнутая система из 29 skill'ов Claude Code, которая **сама находит
неэффективный код в Java-проекте, сама чинит его и сама доказывает
измерением, что стало лучше** — а если стало хуже, сама откатывает правку
и пробует другой подход. Одна команда — `/profile-orchestrator` (или
legacy-алиас `/profile`) — на входе, ветка с коммитами-фиксами, Pull
Request и единственный сводный отчёт `PROFILEREPORT.md` с цифрами
«до/после» на выходе.

Анализ — **evidence-driven**: вместо безусловного запуска всех 22
статических детекторов роутер по фактическим сигналам baseline-измерения
и профайлера выбирает максимум 3 пакета анализаторов, детекторы читают
однократно построенный кэшируемый индекс проекта (не повторяя discovery)
и пишут находки в единый JSONL-контракт вместо 22 промежуточных
Markdown-отчётов — это кратно снижает latency и token usage прогона.

Ключевое отличие от «попросить LLM оптимизировать код»: ни один фикс не
принимается на веру. Каждая правка проходит цикл
**фикс → сборка/тесты → измерение → вердикт**, и только вердикт «не хуже»
(по метрикам, а не по мнению модели) позволяет её оставить.

## Как это работает

```
/profile-orchestrator (evidence-driven оркестратор; /profile — legacy-алиас)
│
├─ Фаза 1 — baseline и маршрутизация (read-only)
│   ├─ java-performance-discovery    → performance_discovery.md (как собрать/запустить/мерить)
│   ├─ java-performance-measurement  → baseline метрик (latency, sql_count, throughput…)
│   ├─ profiler                      → baseline находок рантайма (утечки, дедлоки, GC-паузы)
│   ├─ build_project_index.py        → .profile-run/project-index.json (кэш по Git SHA)
│   ├─ evidence.json                 → компактные числовые сигналы measurement/profiler
│   ├─ route_analysis.py             → .profile-run/analysis-plan.json (максимум 3 packs)
│   └─ только выбранные find-*       → .profile-run/findings.jsonl (JSONL, ≤10 на детектор)
│       (+ profiler-find-problem, если профайлер дал находки — тоже в findings.jsonl)
│
├─ Фаза 2 — очередь: findings_to_queue.py — только дедуплицированные
│   находки confidence ≥ 0.70 c конкретным suggested_fix, приоритизация
│   по severity/confidence, QG-merge дублей одного дефекта по file:line
│
├─ Фаза 3 — цикл исправлений, по одной находке:
│   снимок "до" → apply-recommendations правит код → сборка/тесты →
│   повторное измерение → BETTER/SAME: чекпоинт + git-коммит
│                       → WORSE/MIXED: откат, retry с фидбэком (до 3 попыток)
│
└─ Фаза 4 — final-измерения против исходного baseline,
    render_profile_report.py → PROFILEREPORT.md (единственный финальный
    Markdown-отчёт), push ветки и Pull Request (если есть git+remote+gh)
```

### Analysis packs и маршрутизация

Роутер (`scripts/route_analysis.py`) читает `.profile-run/evidence.json`
и выбирает **не более 3** пакетов анализаторов:

| Pack | Сигналы evidence | Детекторы (legacy find-*) |
|---|---|---|
| `data-access` | `sql_count`, `jdbc_samples` | find-query-issues, find-missing-batching, find-orm-fetch-strategy-issues, find-over-fetching-api, find-unbounded-data-loading, find-missing-caching |
| `cpu-hotpath` | `cpu_hotspots`, `cpu_pct` | find-algorithm-inefficiency, find-inefficient-api-usage, find-redundant-computation, find-redundant-checks, find-reflection-in-hot-path, find-regex-issues |
| `memory-gc` | `allocation_rate`, `gc_pause_ms`, `heap_growth_mb` | find-gc-pressure, find-data-layout-waste, find-resource-management-issues, find-unbounded-cache-or-queue |
| `concurrency` | `blocked_ms`, `lock_contention` | find-concurrency-issues, find-transaction-locking-issues, find-cache-locality-issues |
| `io-observability` | `logging_samples`, `exception_count` | find-logging-overhead, find-exceptions-as-control-flow |
| `cleanup` | только явный `--full`/`--full-audit` | find-dead-code |

Ключи принимаются и в snake_case, и в camelCase; evidence — плоский JSON
или `{"baseline": {...}, "profiler": {...}}`. **Fallback:** если
evidence отсутствует/не дал сигналов, роутер выбирает `data-access` +
`cpu-hotpath` (и помечает `fallback_used: true` в плане). `--full`
добавляет `cleanup`, не превышая лимит 3 packs; `--full-audit` — явный
задокументированный полный аудит всеми packs (наследник старого
поведения `/profile`, никогда не по умолчанию). Если детектор уже записал
находку с confidence ≥ 0.85, объясняющую primary regression, оставшиеся
детекторы не запускаются (early stop; не действует при `--full`).

Каждый этап — отдельный, самостоятельно используемый skill: можно запустить
только discovery, только измерение, только один `find-*` или только фиксер
— `/profile` лишь дирижирует ими.

## Состав пакета

```
java-perf-skillset/
├── README.md            ← этот файл (для человека)
├── INSTALL.md           ← инструкция установки (исполняется Claude Code)
├── schemas/
│   └── finding.schema.json ← единый JSONL-контракт находок (.profile-run/findings.jsonl)
├── scripts/             ← тонкие обёртки CLI (канонические реализации —
│                          в skills/profile-orchestrator/scripts/)
│   ├── build_project_index.py   ← кэшируемый индекс проекта (по Git SHA)
│   ├── route_analysis.py        ← evidence-driven выбор analysis packs
│   ├── findings_to_queue.py     ← findings.jsonl → очередь фиксов
│   └── render_profile_report.py ← findings.jsonl → PROFILEREPORT.md
├── hooks/
│   └── profile-guard.sh ← PreToolUse-hook: физически блокирует запись фиксера
│                          в запрещённые пути во время прогона /profile
└── skills/              ← 29 skill'ов, по папке на каждый (SKILL.md + scripts/ + references/)
```

### Пайплайн (7 skill'ов)

| Skill | Что делает | Вход → Выход |
|---|---|---|
| `profile-orchestrator` | **Предпочтительная точка входа**: evidence-driven оркестратор всего цикла — индекс, роутинг ≤3 packs, JSONL findings, очередь, чекпоинты, коммиты, PR | проект → ветка + `PROFILEREPORT.md` + PR |
| `java-performance-discovery` | Разведка проекта: как собрать, запустить, что и чем мерить | исходники → `performance_discovery.md` |
| `java-performance-measurement` | Создаёт и гоняет измерения (JMH / k6-HTTP / CLI), сравнивает с baseline | discovery-файл → `perf/`, `.performance/`, вердикт BETTER/WORSE/SAME/… |
| `profiler` | Утечки памяти/потоков, дедлоки, GC-паузы, голодание пула — под смешанной нагрузкой | discovery-файл → `profiler/`, `.profiler/findings.json` |
| `profiler-find-problem` | По находкам profiler находит в коде причину и место, формулирует фикс | `findings.json` → строки в `findings.jsonl` (standalone — `profiler_report.md`) |
| `apply-recommendations` | Единственный skill, который меняет код: применяет одну находку, проверяет сборку, откатывает при провале | inline-находка контракта (или legacy `*_report.md`) → правка кода |
| `profile` | **Legacy-алиас**: делегирует прогон profile-orchestrator'у; его Фазы 0/3/4 (подготовка, цикл фиксов, git/PR) — нормативная механика, скрипты очереди/чекпоинтов используются без изменений | проект → ветка + `PROFILEREPORT.md` + PR |

### Статический анализ (22 детектора `find-*`)

Каждый ищет свою категорию проблем, работает строго read-only и
**append'ит находки строками JSONL в `.profile-run/findings.jsonl`** —
единый контракт (`schemas/finding.schema.json`: `id`, `category`,
`severity`, числовой `confidence`, `location`, краткий `evidence`,
`suggested_fix`, `verify`), который понимают и фиксер, и оркестратор.
Отдельных Markdown-отчётов детекторы больше не создают. Запускаются
только детекторы выбранных роутером packs (не более 3), каждый — не
более 10 находок за прогон; вместо повторного discovery детектор читает
`.profile-run/project-index.json` и только выбранные целевые файлы:

| Skill | Категория | Pack |
|---|---|---|
| find-query-issues | N+1, индексы, пагинация, анти-паттерны SQL | data-access |
| find-missing-batching | round-trip'ы в цикле вместо batch | data-access |
| find-orm-fetch-strategy-issues | EAGER/LAZY, fetch join, декартово произведение | data-access |
| find-over-fetching-api | избыточный сетевой payload, нет проекций | data-access |
| find-unbounded-data-loading | выборка без лимита, файл целиком в память | data-access |
| find-missing-caching | пересчёт детерминированного, пересоздание тяжёлых объектов | data-access |
| find-algorithm-inefficiency | O(n²), неверные структуры данных | cpu-hotpath |
| find-inefficient-api-usage | findAll()+фильтр в памяти, лишние выборки | cpu-hotpath |
| find-redundant-computation | loop-invariant, лишние проходы и копии | cpu-hotpath |
| find-redundant-checks | дублирующиеся проверки, в т.ч. между слоями | cpu-hotpath |
| find-reflection-in-hot-path | рефлексия/AOP/мегаморфные вызовы в горячем пути | cpu-hotpath |
| find-regex-issues | ReDoS, компиляция regex в цикле | cpu-hotpath |
| find-gc-pressure | аллокации в горячем цикле, автобоксинг | memory-gc |
| find-data-layout-waste | boxed-примитивы, неоптимальные типы в схеме БД | memory-gc |
| find-resource-management-issues | незакрытые соединения/дескрипторы, клиент на каждый запрос | memory-gc |
| find-unbounded-cache-or-queue | кэши без вытеснения, очереди без предела | memory-gc |
| find-concurrency-issues | блокирующий код в реактивном, локи, пулы | concurrency |
| find-transaction-locking-issues | длинные транзакции, порядок блокировок | concurrency |
| find-cache-locality-issues | локальность кэша CPU, false sharing | concurrency |
| find-logging-overhead | дорогие аргументы лога, лог в горячем цикле | io-observability |
| find-exceptions-as-control-flow | исключения как поток управления | io-observability |
| find-dead-code | мёртвый код и недостижимые ветви | cleanup (только `--full`) |

`find-dead-code` — единственный, чьи находки не про скорость (JIT сам
устраняет мёртвый код): он включён для гигиены кода, его находки честно
помечаются `severity: low` и не претендуют на эффект в метриках.

**Почему 22 отдельных детектора, а не один «найди всё»?** Каждая
категория получает изолированный контекст и полное внимание модели (один
проход — одна категория, меньше пропусков) и свой триггер для точечного
ручного запуска («найди N+1» не заставляет анализировать регулярки). При
этом запускать все 22 подряд больше не нужно: роутер выбирает только
релевантные evidence пакеты, а все находки идут в общий
`findings.jsonl`. Дубли — когда один и тот же цикл находят и
find-query-issues, и find-missing-batching — схлопывает
`findings_to_queue.py` (точные дубли + QG-merge по пересечению
`file:line` в пределах 3 строк).

## Быстрый старт

1. Установка (один раз): открыть Claude Code в папке этого пакета и
   попросить «установи по INSTALL.md» — Claude сам скопирует skill'ы в
   `~/.claude/skills/`, hook в `~/.claude/hooks/` и пропишет его в
   `settings.json` слиянием, ничего не затирая.
2. В корне Java-проекта (Maven или Gradle):

   ```
   /profile-orchestrator
   ```

   (legacy `/profile` продолжает работать — он делегирует прогон сюда же
   с `--full`). Флаги: `--full` — добавить pack `cleanup` (лимит 3 packs
   сохраняется), `--full-audit` — явный полный аудит всеми packs.
   Дальше — автономно (полный прогон занимает часы: каждое принятие фикса
   — это сборка + измерение). Прерванный прогон продолжается повторным
   вызовом в той же папке.
3. Результат: ветка `profile/<timestamp>` с коммитом на каждый принятый
   фикс (в сообщении — метрика до/после), `PROFILEREPORT.md` в корне —
   единственный финальный человекочитаемый отчёт, Pull Request (если
   настроены git remote и `gh`).
4. Откат любого автоматического фикса — в любой момент, даже без git:

   ```bash
   python3 ~/.claude/skills/profile/scripts/checkpoint_revert.py --project-root . --last 1
   ```

   (на Windows — `py -3` вместо `python3`)

Skill'ы можно использовать и по отдельности, без `/profile`: «найди N+1 в
этом проекте» запустит только `find-query-issues`, «примени рекомендации
из отчёта» — только `apply-recommendations`.

## Артефакты прогона (все — в `<project-root>/.profile-run/`)

| Файл | Что содержит |
|---|---|
| `project-index.json` | однократный структурный индекс проекта: `git_sha` (кэш-ключ), `build_tool`, `modules`, `frameworks` (Spring/JPA/Kafka…), `source_files`, `repositories`, `entities`, `entrypoints`. Повторный запуск `build_project_index.py` при неизменном Git SHA переиспользует кэш (`--force` — пересобрать; без git — fallback `git_sha: "nogit"`, кэш не переиспользуется) |
| `evidence.json` | компактные числовые сигналы из baseline measurement/profiler для роутера |
| `analysis-plan.json` | выбранные packs (≤3), скоринг сигналов, режим (`standard`/`full`/`full-audit`), `fallback_used`, findings-контракт |
| `findings.jsonl` | находки всех детекторов, по одному JSON-объекту на строку (`schemas/finding.schema.json`) |
| `queue.json`, `checkpoints/`, `run-state.json`, `ACTIVE` | как раньше у `/profile`: очередь фиксов, обратимые чекпоинты, состояние resume, маркер guard-hook'а |

`.profile-run/` — внутреннее состояние, добавляется в `.gitignore`
проекта (Фаза 0). Единственный финальный человекочитаемый отчёт —
`PROFILEREPORT.md` в корне проекта.

## Миграция со старых `*_report.md`

Раньше каждый `find-*` перезаписывал собственный Markdown-отчёт
(`query_issues_report.md` и т.д.) в корне проекта, а очередь строил
`build_queue.py` по этим отчётам. Теперь:

- детекторы **не создают** `*_report.md` — только строки в
  `.profile-run/findings.jsonl`; очередь строит `findings_to_queue.py`;
- старые `*_report.md`, оставшиеся в проекте от прежних прогонов, никем
  не читаются (renderer их игнорирует) — их можно удалить вручную;
- `apply-recommendations` по-прежнему умеет legacy-вход «файл отчёта +
  id» для отчётов, созданных вне этой системы, но оркестратор передаёт
  находки inline JSON-объектом;
- сводный отчёт называется `PROFILEREPORT.md` (прежний
  `PROFILE_REPORT.md` больше не создаётся).

## Как система защищается от собственных ошибок

1. **Verify-цикл вместо доверия.** Фикс принимается только после
   повторного измерения с вердиктом «не хуже» (пороги шума/регрессии
   заданы в scenario.yaml). Регрессия → автоматический откат и до 2 retry
   с передачей фиксеру дифа неудачной попытки и регрессировавшей метрики.
2. **Чекпоинты независимо от git.** Каждый принятый фикс сохраняется как
   обратимый unified-diff в `.profile-run/checkpoints/` — точечный откат
   работает и там, где git'а нет вообще.
3. **Hook как технический барьер.** `profile-guard.sh` (PreToolUse) во
   время активного прогона физически блокирует запись в тесты, скрипты
   измерений и сами отчёты — даже если модель проигнорирует инструкции.
   Вне прогона hook — no-op.
4. **Честная неуверенность.** Находки `confidence: low/unknown` по дизайну
   не имеют рекомендации и не попадают в очередь фиксов — система не
   правит то, в чём не уверена.
5. **Состояние на диске, не в контексте.** Очередь, вердикты и прогресс
   живут в файлах (`queue.json`, `run-state.json`) — многочасовой прогон
   переживает сжатие контекста и обрыв сессии.

## Ограничения

- **Время**: полный `/profile` — часы, не минуты (каждый фикс = сборка +
  полноценное измерение). Это цена доказуемости результата.
- **Git**: не обязателен, но без него нет ветки/коммитов/PR — только
  правки в рабочем дереве + чекпоинты. При доступном git требуется чистое
  рабочее дерево на старте.
- **Окружение**: JDK + Maven/Gradle проекта, Python 3.10+, GNU
  `diff`/`patch`; `gh` — только для автосоздания PR. На Windows hook
  требует Git Bash (ставится с Git for Windows).
- **Каналы измерения**: точность вердиктов зависит от того, что проект
  даёт измерять (см. «Каналы измерения» в discovery). Без видимости SQL
  находки «про число запросов» не поднимаются выше `confidence: low` — об
  этом система предупреждает заранее, а не делает вид, что измерила.
- **Статический анализ** даёт ложные срабатывания по своей природе —
  поэтому find-* никогда не правят код сами, а всё, что попадает в фиксы,
  проходит verify-цикл.
- Файл, созданный фиксом с нуля вне зафиксированных в находке путей, не
  попадает в чекпоинт (задокументированное ограничение механизма отката).

## Переиспользуемость и перенос

- Формат skill'а — открытый: `SKILL.md` (обычный Markdown-промпт с
  frontmatter) + Python-скрипты **без внешних зависимостей** (stdlib
  only). Портирование в другой агент с файловыми инструментами (GigaCode /
  core-агент) — перенос текста промпта и скриптов, привязки к Claude Code
  минимальны (hook — единственная platform-specific часть, и она
  опциональный барьер, не функциональность).
- Контракт между skill'ами — простые файлы: `performance_discovery.md`,
  единый JSONL-контракт находок `.profile-run/findings.jsonl`
  (`schemas/finding.schema.json`), `result.json`/`findings.json` с
  задокументированными схемами (`references/*.md` внутри skill'ов). Любой
  внешний инструмент может производить или потреблять эти артефакты — ещё
  один статический анализатор достаточно научить append'ить строки того
  же JSONL-формата, и его находки поедут по общему конвейеру фикс→verify
  без изменений в остальной системе.
- Кому полезно: разработчикам (авто-PR с оптимизациями), перф-инженерам
  (готовый measurement/profiler-харнесс), ревьюерам (отчёты find-* как
  чек-лист), командам платформы (публикация пакета как единого артефакта
  в InSourceHub).

## Следующие шаги развития

- Параллельный запуск независимых read-only `find-*` (сейчас — строго
  последовательно) для ускорения Фазы 1.
- JFR (Java Flight Recorder) как дополнительный источник снимков profiler
  вместо только `jcmd`.
- Расширение measurement на Kafka/gRPC-сценарии (сейчас сознательно
  ограничено JMH/HTTP/CLI — там, где контракт восстановим из репозитория).
- CI-режим: `/profile` как job с бюджетом времени и PR-комментарием вместо
  локального прогона.
- Публикация в InSourceHub как переиспользуемого пакета с версионированием
  формата отчётов.
