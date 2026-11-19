# Схема `perf/scenario.yaml`

Единственный источник правды о том, что и как измеряется.
Файл коммитится в Git вместе с остальным содержимым `perf/`.

## Полная структура

```yaml
version: 1                     # версия схемы, всегда 1
id: <stable-scenario-id>       # стабильный ID, не меняется между запусками
type: jmh | http | cli         # тип измерения

repeat:
  count: 5                     # число повторов, минимум 5
  aggregation: median          # только median
  maxVariationPercent: 10      # допустимый coefficient of variation, %

comparison:
  noiseThresholdPercent: 5     # |delta| <= noise  -> SAME
  regressionThresholdPercent: 10
  improvementThresholdPercent: 10

metrics:                       # хотя бы одна метрика с primary: true
  - id: <metric-id>            # snake_case, совпадает с ключом в metrics JSON
    unit: <unit>               # ms, rps, ops_s, s, percent, mb, ...
    direction: lower_is_better | higher_is_better
    primary: true              # primary-метрики определяют вердикт

commands:                      # только реально существующие команды
  build: <command>             # обязателен; выполняется вне измерения
  start: <command-or-null>     # null для jmh/cli без long-running процесса
  readiness: <command-or-null> # команда с exit code 0 при готовности
  measure: <command>           # обязателен; один измерительный прогон
  stop: <command-or-null>      # обязателен, если start не null
  reset: <command-or-null>     # очистка состояния перед повтором
```

Правила:

- `id` стабилен: смена ID делает историю несравнимой.
- Все команды проверены в текущем репозитории; вымышленные команды запрещены.
- `direction`: `lower_is_better` — latency, duration, errors, allocation;
  `higher_is_better` — throughput, operations/sec.
- Если `start` задан, `stop` обязателен (плюс `trap` в `run-one.sh`).
- `reset` выполняется перед каждым повтором, только если он не null.
- Изменение содержимого файла меняет scenario fingerprint —
  старые замеры станут `NOT_COMPARABLE`. Это ожидаемое поведение.

## Пример: JMH

```yaml
version: 1
id: json-mapper-serialize-jmh
type: jmh

repeat:
  count: 5
  aggregation: median
  maxVariationPercent: 8

comparison:
  noiseThresholdPercent: 3
  regressionThresholdPercent: 7
  improvementThresholdPercent: 7

metrics:
  - id: throughput_ops_s
    unit: ops_s
    direction: higher_is_better
    primary: true
  - id: allocation_b_op
    unit: b_op
    direction: lower_is_better
    primary: false

commands:
  build: ./mvnw -q -pl benchmarks -am package -DskipTests
  start: null
  readiness: null
  measure: >
    java -jar benchmarks/target/benchmarks.jar
    'com.example.bench.JsonMapperBenchmark.serialize'
    -wi 5 -i 5 -f 3 -rf json -rff "$RAW_DIR/jmh-result.json"
  stop: null
  reset: null
```

Примечания:
- warmup `-wi` >= 5, iterations `-i` >= 5, forks `-f` >= 3 — минимумы.
- Каждый «повтор» skill — это полный запуск JMH со своим JSON-выводом.
- `normalize-result.py` извлекает `primaryMetric.score` (и GC-профайлер,
  если включён) из JMH JSON.

## Пример: HTTP / k6

```yaml
version: 1
id: orders-api-create-order
type: http

repeat:
  count: 5
  aggregation: median
  maxVariationPercent: 10

comparison:
  noiseThresholdPercent: 5
  regressionThresholdPercent: 10
  improvementThresholdPercent: 10

metrics:
  - id: throughput_rps
    unit: rps
    direction: higher_is_better
    primary: true
  - id: latency_p95_ms
    unit: ms
    direction: lower_is_better
    primary: true
  - id: latency_p99_ms
    unit: ms
    direction: lower_is_better
    primary: false
  - id: error_rate_percent
    unit: percent
    direction: lower_is_better
    primary: true

commands:
  build: ./mvnw -q package -DskipTests
  start: >
    java -jar target/orders-service.jar
    --server.port=8080 --spring.profiles.active=perf
  readiness: curl -sf http://localhost:8080/actuator/health
  measure: >
    k6 run perf/k6-scenario.js
    --summary-export "$RAW_DIR/k6-summary.json"
  stop: 'kill "$APP_PID"'
  reset: null
```

Примечания:
- k6-скрипт хранится в `perf/`, payloads — в `perf/payloads/`.
- Warm-up >= 2 минут для long-running приложения; основной период
  измерения >= 5 минут, если discovery не задаёт иное.
- Профиль нагрузки фиксированный (constant VUs или constant arrival rate).
- В requests добавляется header `X-Performance-Run-Id`, если приложение
  принимает произвольные headers.
- Никогда не указывай production URL без явного разрешения в discovery.

## Пример: CLI

```yaml
version: 1
id: report-generator-batch
type: cli

repeat:
  count: 7
  aggregation: median
  maxVariationPercent: 12

comparison:
  noiseThresholdPercent: 5
  regressionThresholdPercent: 10
  improvementThresholdPercent: 10

metrics:
  - id: duration_s
    unit: s
    direction: lower_is_better
    primary: true
  - id: peak_rss_mb
    unit: mb
    direction: lower_is_better
    primary: false

commands:
  build: ./gradlew -q installDist
  start: null
  readiness: null
  measure: >
    /usr/bin/time -v build/install/report-generator/bin/report-generator
    --input perf/payloads/input-fixed.csv
    --output "$RAW_DIR/report-output.csv"
  stop: null
  reset: 'rm -f "$RAW_DIR/report-output.csv"'
```

Примечания:
- Build выполняется до измерения; в measure входит только сам workload.
- Wall-clock и peak RSS берутся из вывода `/usr/bin/time -v`
  (или `time -l` на macOS — normalize-result.py учитывает платформу).
- Дополнительно проверяется exit code и корректность ожидаемого output.
