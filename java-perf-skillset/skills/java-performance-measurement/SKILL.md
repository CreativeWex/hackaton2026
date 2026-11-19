---
name: java-performance-measurement
description: >
  Создаёт, запускает и сравнивает performance-измерения Java-проектов.
  Обязательно используй этот skill, когда пользователь просит измерить,
  замерить или сравнить производительность Java-проекта, создать baseline,
  выполнить initial/incremental/final performance measurement, сгенерировать
  нагрузочные скрипты (JMH, k6, CLI), либо когда в корне проекта есть файл
  performance_discovery.md. Skill определяет способ запуска приложения,
  создаёт скрипты в perf/, сохраняет историю замеров в .performance/ и
  выдаёт Markdown-отчёт с вердиктом BETTER/WORSE/SAME/MIXED/INCONCLUSIVE/
  NOT_COMPARABLE/FAILED/BASELINE_CREATED.
---

# Java Performance Measurement

## Назначение

Ты отвечаешь только за этап измерения производительности Java-проекта.

Вход:
- путь к корню анализируемого Java-проекта (`<project-root>`);
- режим: `initial`, `incremental` или `final`;
- файл `<project-root>/performance_discovery.md`;
- исходный код и конфигурация проекта.

Выход:
- подготовленные скрипты в `<project-root>/perf/`;
- результаты в `<project-root>/.performance/`;
- один итоговый Markdown-отчёт за запуск.

Жёсткие ограничения:
- Не анализируй, почему код стал быстрее или медленнее.
- Не изменяй production-код, бизнес-логику, public API и тестируемый Java-код.
- Создавай или изменяй только файлы в `perf/`, `.performance/` и, при
  необходимости, `.gitignore` (для исключения `.performance/`).
- `perf/` должен быть пригоден для коммита в Git.
- `.performance/` не должна коммититься и должна быть в `.gitignore`.

Вспомогательные ресурсы этого skill:
- `scripts/compare_results.py` — агрегация повторов, сравнение с reference,
  вычисление вердикта. Вызывай его из `perf/run-performance.sh`.
- `scripts/render_report.py` — генерация Markdown-отчёта из `result.json`.
- `references/scenario-schema.md` — точная схема `perf/scenario.yaml`
  и примеры для JMH, HTTP/k6 и CLI. Читай при генерации scenario.yaml.
- `references/report-format.md` — шаблоны отчётов initial/incremental/final.
  Читай при генерации или проверке report.md.

## Обязательное чтение discovery

Перед созданием любых файлов прочитай:

`<project-root>/performance_discovery.md`

По нему пойми способ запуска проекта и критический performance-path.

Затем проверь фактические файлы проекта:
- `pom.xml`, `mvnw`, `.mvn/`;
- `build.gradle`, `build.gradle.kts`, `gradlew`, `gradle/`;
- `Dockerfile`, `compose.yaml`, `docker-compose.yml`;
- `src/main/resources/application*.yml`, `application*.properties`;
- README;
- OpenAPI/protobuf-контракты;
- существующие integration tests;
- существующие JMH benchmarks;
- существующие k6, Gatling, JMeter или shell scripts.

`performance_discovery.md` — основное описание намерений, но при конфликте
между discovery-файлом и фактическим проектом приоритет имеет фактическая
конфигурация проекта.

Никогда не выдумывай:
- endpoint;
- payload;
- startup command;
- readiness-check;
- способ остановки приложения;
- допустимую нагрузку;
- правило очистки состояния между повторами.

Если этих данных нет ни в `performance_discovery.md`, ни в OpenAPI, ни в
существующих тестах — создай `<project-root>/perf/NEEDS_INPUT.md` с точным
перечнем недостающих данных (конкретные вопросы) и остановись. Не создавай
фальшивый сценарий.

Примеры критически недостающей информации:
- неизвестен способ безопасно поднять приложение;
- неизвестен входной endpoint, CLI command или benchmark class;
- неизвестен формат минимально валидного запроса;
- неизвестна команда остановки long-running приложения;
- неизвестно, нужно ли очищать состояние между повторами.

## Режимы

### initial

Первичный замер, создание baseline.

1. Создай или обнови скрипты в `perf/`.
2. Выполни измерение не менее 5 раз.
3. Используй median каждой метрики.
4. Сохрани агрегированный результат в `.performance/initial/result.json`.
5. Скопируй его в `.performance/latest/result.json`.
6. Создай `.performance/initial/report.md`.

Вердикт: `BASELINE_CREATED`.

### incremental

Сравнение текущего кода с последним валидным замером.

Reference: `.performance/latest/result.json`.

1. Если reference отсутствует — остановись и сообщи, что сначала нужен `initial`.
2. Выполни текущий замер не менее 5 раз.
3. Проверь совместимость scenario/environment fingerprint.
4. Сравни текущий агрегированный результат с `latest`.
5. Сохрани новый запуск в `.performance/runs/<run-id>/`
   (run-id: `<timestamp>-<git-sha>`).
6. Обнови `.performance/latest/result.json` только если новый замер валиден
   (вердикт не `FAILED`, не `NOT_COMPARABLE`, не `INCONCLUSIVE`).
7. Создай `report.md` в каталоге текущего запуска.

Вердикт: `BETTER`, `WORSE`, `SAME`, `MIXED`, `INCONCLUSIVE`,
`NOT_COMPARABLE` или `FAILED`.

### final

Сравнение текущего кода с исходным baseline.

Reference: только `.performance/initial/result.json`.

1. Не перезаписывай initial baseline.
2. Выполни финальный замер не менее 5 раз.
3. Проверь совместимость fingerprint.
4. Сравни текущий результат с initial.
5. Сохрани отчёт в `.performance/final/<run-id>/report.md`
   (рядом — `result.json` и raw artifacts).

## Выбор типа измерения

Используй `jmh`, если discovery указывает на:
- Java-библиотеку;
- конкретный алгоритм;
- parser, serializer, mapper;
- работу с коллекциями;
- конкретный метод или класс, вызываемый из benchmark;
- существующие JMH benchmarks.

Используй `http` (k6), если discovery указывает на HTTP-сервис
(Spring Boot / Jakarta / Quarkus / Micronaut) и известны все из:
endpoint, HTTP method, payload, expected response/status, startup command,
readiness check — из discovery, OpenAPI или интеграционных тестов.

Используй `cli`, если discovery указывает на batch/command-line
Java-приложение, обработку файла или одноразовый Java job.

Не создавай Kafka, RabbitMQ, gRPC, WebSocket или DB load scenarios,
если contract, test data и условие завершения обработки не описаны явно.

### JMH

- Используй существующий JMH module и benchmark classes, если они есть;
  не меняй benchmark implementation без необходимости.
- Если JMH отсутствует, но discovery однозначно описывает измеряемый
  Java-метод — можно создать отдельный benchmark module; production classes
  не менять.
- Используй реальные или заранее определённые deterministic test data.
- Не создавай benchmark, измеряющий пустой вызов или только
  конструирование объекта.
- Обязательно: warmup iterations >= 5; measurement iterations >= 5;
  forks >= 3; raw JMH results в JSON; конкретный include pattern.

### HTTP (k6)

- Фиксированный и воспроизводимый профиль нагрузки.
- Для long-running приложения warm-up не менее 2 минут.
- Основной период измерения не менее 5 минут, если discovery не требует иного.
- Request checks на expected status/response.
- Сохраняй k6 JSON summary.
- Deterministic test payloads (в `perf/payloads/`).
- Заголовок `X-Performance-Run-Id`, если приложение принимает
  произвольные headers.
- Не направляй нагрузку на production URL без явного разрешения в discovery.

### CLI

Измеряй:
- wall-clock duration;
- exit code;
- при возможности peak RSS или JVM metrics;
- корректность ожидаемого output.

Не включай build time в измерение CLI workload.

## Создаваемые файлы в проекте

```text
perf/
  scenario.yaml         # декларативное описание сценария
  run-performance.sh    # оркестратор: initial|incremental|final
  run-one.sh            # ровно один measurement-repeat
  normalize-result.py   # raw tool output -> нормализованный JSON
  payloads/             # deterministic test payloads (для http)
  README.md             # как запускать и что где лежит

.performance/
  initial/              # baseline: result.json, report.md, raw/
  latest/               # последний валидный result.json
  runs/                 # incremental: <run-id>/result.json, report.md, raw/
  final/                # final: <run-id>/report.md, result.json, raw/
```

Добавь `.performance/` в `.gitignore`, если она ещё не исключена.

## `perf/scenario.yaml`

Точная схема и примеры — в `references/scenario-schema.md`. Каркас:

```yaml
version: 1
id: <stable-scenario-id>
type: jmh | http | cli

repeat:
  count: 5
  aggregation: median
  maxVariationPercent: 10

comparison:
  noiseThresholdPercent: 5
  regressionThresholdPercent: 10
  improvementThresholdPercent: 10

metrics:
  - id: <metric-id>
    unit: <unit>
    direction: lower_is_better | higher_is_better
    primary: true

commands:
  build: <command>
  start: <command-or-null>
  readiness: <command-or-null>
  measure: <command>
  stop: <command-or-null>
  reset: <command-or-null>
```

Правила:
- стабильный scenario id (не меняется между запусками);
- только проверенные, реально существующие в репозитории команды;
- не указывай вымышленные команды.

Направление метрик:
- `lower_is_better`: latency, duration, errors, allocation;
- `higher_is_better`: throughput, operations/sec.

## Скрипты в проекте

### `perf/run-performance.sh`

```bash
./perf/run-performance.sh initial
./perf/run-performance.sh incremental
./perf/run-performance.sh final
```

Обязан:
1. Проверить наличие `performance_discovery.md`.
2. Прочитать `perf/scenario.yaml`.
3. Выполнить build строго вне измеряемого участка.
4. Запустить ровно указанное число повторов (>= 5).
5. Перед каждым повтором выполнить reset, только если он определён
   в scenario.yaml.
6. Для каждого повтора вызвать `perf/run-one.sh`.
7. Нормализовать каждый raw result через `perf/normalize-result.py`.
8. Агрегировать метрики и выбрать reference по mode
   (вызов `compare_results.py` из этого skill).
9. Создать `result.json`.
10. Создать `report.md` (вызов `render_report.py` из этого skill).
11. Вывести путь к итоговому `report.md` последней строкой stdout.
12. Не удалять raw artifacts при ошибках.

### `perf/run-one.sh`

Ровно один performance-repeat:
- создаёт каталог `raw/run-N`;
- запускает приложение, если необходимо;
- ждёт readiness;
- выполняет warm-up, если определён;
- запускает один измерительный прогон;
- гарантированно останавливает приложение через `trap`;
- сохраняет stdout/stderr и raw tool results;
- не включает build time в измерение;
- не удаляет raw data при ошибке.

### `perf/normalize-result.py`

- принимает путь к raw tool output;
- извлекает только метрики, описанные в scenario.yaml;
- записывает нормализованный JSON (формат ниже);
- завершается с ошибкой, если обязательная метрика отсутствует;
- не подставляет 0 и не маскирует ошибки.

## Формат нормализованного результата

Каждый повтор нормализуется в единый JSON:

```json
{
  "schemaVersion": 1,
  "scenarioId": "example",
  "measurementType": "http",
  "runId": "2026-07-28T12-00-00Z",
  "gitSha": "unknown",
  "metrics": {
    "throughput_rps": 120.5,
    "latency_p95_ms": 145.0,
    "latency_p99_ms": 290.0,
    "error_rate_percent": 0.01
  }
}
```

Агрегированный `result.json` должен хранить:
- samples по каждой метрике;
- median, min, max, mean, standard deviation;
- variationPercent (coefficient of variation, %);
- environment fingerprint;
- scenario fingerprint;
- reference run;
- verdict;
- Git SHA;
- пути к raw artifacts.

## Повторы и погрешность

- Минимум 5 повторов, если discovery не задаёт иной минимум.
- Агрегация — median.
- Если variation любой primary metric превышает `maxVariationPercent` —
  вердикт `INCONCLUSIVE`.
- Не называй изменение улучшением или ухудшением, если абсолютная
  относительная дельта не превышает `noiseThresholdPercent`.

## Совместимость (fingerprint)

`scenarioFingerprint` строится из:
- содержимого `perf/scenario.yaml`;
- типа измерения;
- версии Java;
- JVM options;
- OS/architecture;
- CPU count;
- memory limits, если доступны;
- версии инструмента JMH/k6;
- checksum тестовых payloads;
- команд запуска и измерения.

Если fingerprint текущего запуска и reference различаются —
вердикт `NOT_COMPARABLE`. Не вычисляй better/worse при `NOT_COMPARABLE`.

## Вердикт

Только один из статусов:
`BASELINE_CREATED`, `BETTER`, `WORSE`, `SAME`, `MIXED`,
`INCONCLUSIVE`, `NOT_COMPARABLE`, `FAILED`.

Правила:
- `BASELINE_CREATED`: успешный initial-замер.
- `SAME`: изменения всех primary metrics в пределах `noiseThresholdPercent`.
- `BETTER`: значимое улучшение выше `improvementThresholdPercent`
  и нет регрессий выше `regressionThresholdPercent`.
- `WORSE`: регрессия выше `regressionThresholdPercent`.
- `MIXED`: одновременно значимое улучшение и значимая регрессия.
- `INCONCLUSIVE`: variation выше допустимого или недостаточно валидных повторов.
- `NOT_COMPARABLE`: scenario/environment fingerprint отличаются от reference.
- `FAILED`: ошибка build, start, readiness, measurement, reset
  или normalization.

Приоритет:
`FAILED` > `NOT_COMPARABLE` > `INCONCLUSIVE` > `MIXED` > `WORSE` > `BETTER` > `SAME`.

## Итоговый отчёт

Шаблоны — в `references/report-format.md`. Каждый запуск обязан создать
краткий Markdown-отчёт, содержащий:

1. Итоговый verdict.
2. Режим запуска: initial, incremental, final.
3. Текущий Git SHA.
4. Reference Git SHA, если есть.
5. Scenario ID и measurement type.
6. Repeat count и aggregation.
7. Информацию о сравнимости fingerprint.
8. Таблицу: Metric / Reference / Current / Delta / Variation / Verdict.
9. Текстовое объяснение итогового статуса.
10. Пути к result.json и raw artifacts.
11. Список созданных или изменённых файлов.

Не интерпретируй причину изменения производительности.
Не пиши общих рекомендаций по оптимизации.

## Безопасность

Никогда не:
- выполняй destructive commands без явного указания в discovery;
- удаляй базы данных, Docker volumes, файлы пользователя или target data;
- используй production credentials;
- отправляй данные во внешние сервисы;
- запускай нагрузку против public/production URL без явного разрешения;
- генерируй shell-команды из неконтролируемых значений HTTP payload;
- отключай TLS verification без явного требования discovery.

## Перед завершением

Проверь:
- все созданные shell/python scripts executable (`chmod +x`);
- `shellcheck` запущен для shell scripts, если установлен;
- Python-скрипты совместимы с Python 3.10+ (`python3 -m py_compile`);
- все пути в скриптах корректно quoted;
- скрипты работают из project root;
- сгенерированный scenario соответствует performance_discovery.md
  и фактическому проекту;
- `.performance/` добавлена в `.gitignore`;
- Markdown-отчёт реально создан, его путь — последняя строка stdout
  `run-performance.sh`.

Если что-то невозможно выполнить из-за недостающих данных — создай
`perf/NEEDS_INPUT.md`, объясни блокер и не выдумывай решение.
