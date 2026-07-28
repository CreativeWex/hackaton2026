---
name: profiler
description: >
  Ищет в запущенном Java-проекте проблемы рантайма — утечки памяти, дедлоки,
  утечки потоков, длинные GC-паузы, голодание пула соединений — под
  устойчивой смешанной нагрузкой, и сравнивает находки до/после исправлений.
  Обязательно используй этот skill, когда пользователь просит
  профилировать Java-проект, найти утечку памяти/дедлок, проверить, помогло
  ли исправление утечки/дедлока, создать baseline находок или выполнить
  initial/incremental/final прогон профайлера. Требует
  performance_discovery.md (создаётся skill'ом java-performance-discovery) —
  без него не запускается. Не путать с java-performance-measurement: тот
  сравнивает числовую метрику одного сценария (latency, throughput, JMH),
  этот — набор диагностических находок по всему приложению под смешанной
  нагрузкой. Skill создаёт скрипты в profiler/, сохраняет историю в
  .profiler/ и выдаёт Markdown-отчёт с вердиктом
  BETTER/WORSE/SAME/MIXED/INCONCLUSIVE/NOT_COMPARABLE/FAILED/BASELINE_CREATED.
---

# Profiler

## Назначение

Ты отвечаешь за диагностику рантайма Java-проекта: утечки памяти, дедлоки,
утечки потоков, долгие GC-паузы, голодание пула соединений. Третий skill в
системе из трёх:

1. `java-performance-discovery` — анализирует проект, пишет
   `performance_discovery.md` (в т.ч. раздел «Профиль нагрузки для
   диагностики» — твой основной вход).
2. `java-performance-measurement` — числовые метрики одного сценария
   (latency/throughput/JMH). Независим от тебя, работает с другим разделом
   того же файла, пишет в `perf/`/`.performance/`.
3. `profiler` (этот skill) — находки по всему приложению под смешанной
   нагрузкой, пишет в `profiler/`/`.profiler/`.

Вход:
- путь к корню Java-проекта (`<project-root>`);
- режим: `initial`, `incremental` или `final`;
- файл `<project-root>/performance_discovery.md`, раздел «Профиль нагрузки
  для диагностики»;
- исходный код и конфигурация проекта.

Выход:
- скрипты в `<project-root>/profiler/`;
- находки и история в `<project-root>/.profiler/`;
- один итоговый Markdown-отчёт за запуск.

Жёсткие ограничения:
- Не анализируй и не объясняй причину находки (не пиши "утечка потому что
  кэш без eviction") — только факт и улики. Причину и исправление вносит
  другой skill, читающий твой артефакт находок.
- Не исправляй код сам. Не изменяй production-код, бизнес-логику, public
  API и тестируемый Java-код.
- Создавай или изменяй только файлы в `profiler/`, `.profiler/` и, при
  необходимости, `.gitignore` (для исключения `.profiler/`).
- `profiler/` должен быть пригоден для коммита в Git.
- `.profiler/` не должна коммититься и должна быть в `.gitignore`.

Вспомогательные ресурсы этого skill:
- `scripts/analyze-findings.py` — разбирает сырые снимки (`jcmd GC.heap_info`,
  `GC.class_histogram`, `Thread.print`, снимки Actuator-метрик) одного
  прогона в `findings.json`. Технология детектирования не зависит от
  проекта — это устройство самого JDK/Actuator, а не специфика конкретного
  приложения, поэтому скрипт общий, не создаётся заново в каждом проекте.
- `scripts/compare-findings.py` — сопоставляет находки текущего прогона с
  reference по стабильному `id`, вычисляет вердикт по каждой находке и
  общий. Вызывай его из `profiler/run-profiler.sh`.
- `scripts/render-report.py` — генерация Markdown-отчёта из результата
  сравнения.
- `references/scenario-schema.md` — точная схема `profiler/scenario.yaml`.
  Читай при генерации scenario.yaml.
- `references/detection-rules.md` — точные правила, по которым
  `analyze-findings.py` решает, что перед ним утечка/дедлок/голодание пула.
  Читай, если нужно объяснить пользователю, почему находка сработала, или
  настроить пороги.
- `references/report-format.md` — шаблоны отчётов initial/incremental/final.

## Обязательное чтение discovery

Перед созданием любых файлов прочитай `<project-root>/performance_discovery.md`,
раздел «Профиль нагрузки для диагностики»: список целей смешанной нагрузки,
рекомендуемую конкурентность, минимальную длительность, правило reset между
прогонами. Также прочитай раздел «Запуск приложения» — build/start/readiness/
stop, они у тебя общие с `java-performance-measurement`.

Если раздел «Профиль нагрузки для диагностики» отсутствует, помечен
`НЕИЗВЕСТНО` целиком или не содержит хотя бы двух безопасных для конкурентного
вызова целей — не выдумывай смешанный набор сам. Создай
`<project-root>/profiler/NEEDS_INPUT.md` с точным перечнем недостающих данных
и остановись. Причина жёсткости: неверно угаданная конкурентная цель (например,
не-идемпотентный POST без reset) может испортить состояние БД так, что все
последующие находки будут ложными.

Никогда не выдумывай:
- какие endpoint'ы/команды безопасно вызывать конкурентно;
- допустимую конкурентность;
- правило reset между прогонами;
- пороги (что считать утечкой/долгой паузой) сверх разумных дефолтов из
  `references/detection-rules.md` — если discovery или сам проект
  (`PROFILING.md`-подобные файлы) задаёт другие пороги явно, приоритет у них.

## Режимы

Те же три режима и те же правила обновления `latest`, что в
`java-performance-measurement` — по аналогии, чтобы поведение было предсказуемо
для того, кто уже работал с тем skill'ом.

### initial

Первый прогон, создание baseline находок.

1. Создай/обнови скрипты в `profiler/`.
2. Прогони диагностику: подними приложение, создай устойчивую смешанную
   нагрузку заданной длительности и конкурентности, сними снимки (heap,
   histogram, thread dump, actuator) в равномерных точках — не менее 3.
3. Разбери снимки в находки (`analyze-findings.py`).
4. Сохрани `.profiler/initial/findings.json`.
5. Скопируй его в `.profiler/latest/findings.json`.
6. Создай `.profiler/initial/report.md`.

Вердикт: `BASELINE_CREATED` (если сам прогон не упал — иначе `FAILED`).

### incremental

Сравнение текущих находок с последним валидным прогоном.

Reference: `.profiler/latest/findings.json`.

1. Если reference отсутствует — остановись, сообщи, что сначала нужен `initial`.
2. Прогони диагностику так же, как в `initial`.
3. Проверь совместимость profile/environment fingerprint (см. ниже).
4. Сопоставь находки с reference по `id`, вычисли вердикт по каждой и общий.
5. Сохрани новый прогон в `.profiler/runs/<run-id>/` (run-id:
   `<timestamp>-<git-sha>`).
6. Обнови `.profiler/latest/findings.json` только если прогон валиден
   (вердикт не `FAILED`, не `NOT_COMPARABLE`, не `INCONCLUSIVE`).
7. Создай `report.md` в каталоге текущего прогона.

Вердикт: `BETTER`, `WORSE`, `SAME`, `MIXED`, `INCONCLUSIVE`, `NOT_COMPARABLE`
или `FAILED`.

### final

Сравнение с исходным baseline — для итогового резюме (например, в PR).

Reference: только `.profiler/initial/findings.json`.

1. Не перезаписывай initial baseline.
2. Прогони диагностику так же, как в `initial`.
3. Проверь совместимость fingerprint.
4. Сравни с initial.
5. Сохрани отчёт в `.profiler/final/<run-id>/report.md` (рядом —
   `findings.json` и raw-снимки).

## Как проходит один диагностический прогон

В отличие от `java-performance-measurement` (короткие независимые повторы по
одному сценарию), здесь **один прогон = одно устойчивое окно нагрузки** с
несколькими снимками внутри него — потому что утечка/дедлок это свойство
процесса во времени, а не одной операции. Поэтому здесь нет "выполни не
менее 5 раз": вместо статистики по повторам используется **внутренняя
согласованность тренда** (см. `references/detection-rules.md`) — находка
"утечка" требует нескольких подряд растущих точек внутри одного окна, а не
статистики по нескольким окнам. Единичный подозрительный всплеск на одной
точке находкой не считается.

Порядок:
1. build — вне измеряемого окна;
2. start приложения, дождаться readiness;
3. запустить заданное число конкурентных воркеров, каждый — по кругу дёргает
   цели из «профиля нагрузки для диагностики»;
4. в N равномерных точках по ходу окна (не менее 3, `snapshots.count` из
   scenario.yaml): `jcmd <pid> GC.run` дважды подряд (гарантия, что мусор
   молодого поколения ушёл — единичная сборка этого не гарантирует) →
   `GC.heap_info`; `GC.class_histogram` (минимум первая и последняя точка);
   `Thread.print` (или `/actuator/threaddump`); снимок нужных Actuator-метрик
   (`jvm.gc.pause`, `hikaricp.connections.pending`, `jvm.threads.live`);
5. дождаться завершения окна, остановить воркеров;
6. stop приложения;
7. не удалять raw-снимки при ошибке.

## Выбор целей и конкурентности

Бери ровно то, что зафиксировано в `performance_discovery.md`. Не поднимай
конкурентность выше `hikari.maximum-pool-size`/`server.tomcat.threads.max`
(или их эквивалентов для другого стека) без явного указания discovery, что
это специально стресс-тест пула — иначе находки "голодание пула" будут
искусственными, а не реальными.

## Создаваемые файлы в проекте

```text
profiler/
  scenario.yaml       # декларативное описание: цели, конкурентность, snapshots, пороги
  collect.sh           # один диагностический прогон: start -> нагрузка -> снимки -> stop
  run-profiler.sh      # оркестратор: initial|incremental|final
  README.md            # как запускать и что где лежит

.profiler/
  initial/             # baseline: findings.json, report.md, raw/
  latest/              # последний валидный findings.json
  runs/                 # incremental: <run-id>/findings.json, report.md, raw/
  final/                # final: <run-id>/report.md, findings.json, raw/
```

Добавь `.profiler/` в `.gitignore`, если она ещё не исключена.

## `profiler/scenario.yaml`

Точная схема и пример — в `references/scenario-schema.md`. Каркас:

```yaml
version: 1
id: <stable-scenario-id>

load:
  duration_s: 60
  concurrency: 8
  targets:
    - method: GET
      path: /api/example
    - method: GET
      path: /api/other

snapshots:
  count: 4
  minMonotonicPointsForLeak: 3

thresholds:
  heapGrowthNoiseMb: 5
  threadGrowthNoise: 3
  gcPauseMaxMs: 500
  connectionsPendingMax: 0

comparison:
  magnitudeNoisePercent: 10
  magnitudeImprovementPercent: 20
  magnitudeRegressionPercent: 20

commands:
  build: <command>
  start: <command>
  readiness: <command>
  collect: profiler/collect.sh
  stop: <command>
  reset: <command-or-null>
```

Правила: те же, что у `java-performance-measurement` для `scenario.yaml` —
стабильный `id`, только реально существующие команды, ничего не выдумывать.

## `profiler/collect.sh`

Единственный проектно-специфичный исполняемый скрипт (в отличие от
`analyze-findings.py`/`compare-findings.py`/`render-report.py` — они общие,
живут в этом skill'е, а не копируются в проект). Обязан:
- поднять приложение по командам из `performance_discovery.md`/scenario.yaml,
  дождаться readiness;
- запустить `load.concurrency` параллельных воркеров, каждый по кругу вызывает
  `load.targets`, суммарно не короче `load.duration_s`;
- в `snapshots.count` равномерных точках сохранить raw-снимки в
  предсказуемой структуре, которую понимает `analyze-findings.py`:
  ```text
  $RAW_DIR/
    meta.json                 # {"pid":, "startedAt":, "snapshotTimestamps":[...], "durationS":, "concurrency":}
    heap/snapshot-N.txt       # jcmd <pid> GC.run; GC.run; GC.heap_info
    histogram/snapshot-N.txt  # jcmd <pid> GC.class_histogram (минимум N=1 и N=last)
    threads/snapshot-N.txt    # jcmd <pid> Thread.print (или actuator threaddump)
    actuator/snapshot-N.json  # {"gcPauseMaxMs":, "connectionsPending":, "threadsLive":, "heapUsedBytes":}
  ```
- гарантированно остановить приложение и воркеров через `trap`, даже при
  ошибке;
- не удалять raw-снимки при ошибке.

Если в проекте нет `jcmd` в PATH (не тот JDK) — не имитируй его вывод и не
пропускай снимок молча: `collect.sh` должен упасть с понятной ошибкой,
`compare-findings.py`/`run-profiler.sh` в этом случае должны дать вердикт
`FAILED`, а не частичный/выдуманный результат.

## Формат находки

Один прогон (`analyze-findings.py`) даёт:

```json
{
  "schemaVersion": 1,
  "mode": "initial",
  "scenarioId": "example",
  "runId": "2026-07-28T12-00-00Z",
  "gitSha": "unknown",
  "findings": [
    {
      "id": "heap-growth",
      "category": "heap_leak",
      "severity": "high",
      "magnitude": 42.3,
      "magnitudeUnit": "mb",
      "evidence": { "usedMbBySnapshot": [180.1, 195.4, 210.8, 222.4], "topGrowthClasses": [...] }
    }
  ]
}
```

Точные правила, какая находка какой категории и с каким `id`/`severity`
рождается — в `references/detection-rules.md`. Не изобретай новые категории
находок вне зафиксированных там (`heap_leak`, `thread_leak`, `deadlock`,
`gc_pause`, `connection_starvation`) без крайней необходимости — если нужна
новая категория, сначала опиши её правило в `references/detection-rules.md`
этого skill'а, а не только в коде.

## Совместимость (fingerprint)

Как в `java-performance-measurement`: `profileFingerprint` строится из
содержимого `scenario.yaml` (targets, concurrency, duration, snapshots,
thresholds) + команд + версии Java + JVM-опций + OS/архитектуры. Если
fingerprint текущего прогона и reference различаются — вердикт
`NOT_COMPARABLE`, сравнение находок не производится.

## Вердикт

По каждой находке при `incremental`/`final` (сопоставление по `id`):
- `RESOLVED` — была в reference, отсутствует сейчас;
- `IMPROVED` — есть в обоих, `magnitude` меньше более чем на
  `comparison.magnitudeImprovementPercent`;
- `SAME` — есть в обоих, разница `magnitude` в пределах
  `comparison.magnitudeNoisePercent` (или обе без `magnitude`, как `deadlock`
  — присутствие в обоих прогонах всегда `SAME`, не `IMPROVED`/`WORSE`, пока
  не исчезнет полностью);
- `WORSE` — есть в обоих, `magnitude` больше более чем на
  `comparison.magnitudeRegressionPercent`;
- `NEW` — отсутствовала в reference, появилась сейчас.

Общий вердикт прогона:
- `FAILED` — сам прогон не удался (build/start/readiness/collect/stop/
  разбор находок);
- `NOT_COMPARABLE` — fingerprint не совпадает с reference;
- `INCONCLUSIVE` — снято меньше снимков, чем требует `snapshots.count`, либо
  внутри окна недостаточно точек для надёжного тренда;
- иначе комбинация per-finding вердиктов: есть `NEW` или `WORSE` и есть
  `RESOLVED` или `IMPROVED` → `MIXED`; есть только `NEW`/`WORSE` → `WORSE`;
  есть только `RESOLVED`/`IMPROVED` → `BETTER`; ничего не изменилось →
  `SAME`.

Приоритет:
`FAILED` > `NOT_COMPARABLE` > `INCONCLUSIVE` > `MIXED` > `WORSE` > `BETTER` > `SAME`.

Для `initial` — `BASELINE_CREATED`, если прогон не упал.

## Итоговый отчёт

Шаблоны — в `references/report-format.md`. Обязательные элементы — как у
`java-performance-measurement` (verdict, режим, Git SHA, reference Git SHA,
scenario ID, совместимость fingerprint, путь к findings.json и raw), но
вместо таблицы метрик — таблица находок: Finding / Category / Severity /
Reference magnitude / Current magnitude / Verdict.

Не интерпретируй причину находки и не пиши рекомендаций по исправлению —
это зона другого skill'а, который читает `findings.json`.

## Безопасность

Никогда не:
- запускай конкурентную нагрузку на цели, для которых discovery не
  подтвердил безопасность (идемпотентность/наличие reset);
- поднимай конкурентность выше отражённых в конфигурации пределов пула
  потоков/соединений без явного указания discovery;
- запускай нагрузку против public/production URL;
- используй production credentials;
- отправляй heap dump'ы или другие снимки во внешние сервисы — только в
  `.profiler/.../raw/` внутри проекта;
- удаляй БД/volumes/файлы пользователя между прогонами сверх того, что
  явно предписывает `reset` из scenario.yaml.

## Перед завершением

Проверь:
- `profiler/collect.sh` executable (`chmod +x`) и работает из project root;
- снято не меньше `snapshots.count` снимков, meta.json корректен;
- `findings.json` создан, при `incremental`/`final` — с сопоставлением и
  вердиктом;
- `.profiler/` добавлена в `.gitignore`;
- Markdown-отчёт создан, его путь — последняя строка stdout
  `run-profiler.sh`;
- raw-снимки не удалены даже при ошибке.

Если данных для безопасного смешанного профиля не хватает — создай
`profiler/NEEDS_INPUT.md`, объясни блокер и не выдумывай решение.
