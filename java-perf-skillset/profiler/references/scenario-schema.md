# Схема `profiler/scenario.yaml`

Единственный источник правды о том, какой смешанной нагрузкой профилировать
проект и по каким порогам судить о находках. Файл коммитится в Git вместе с
остальным содержимым `profiler/`.

## Полная структура

```yaml
version: 1
id: <stable-scenario-id>       # стабильный ID, не меняется между запусками

load:
  duration_s: 60                # минимальная длительность устойчивого окна нагрузки
  concurrency: 8                # параллельных воркеров; не выше пула потоков/соединений проекта
  targets:                      # смешанный набор целей, круговым перебором
    - method: GET
      path: /api/example?param=value
    - method: GET
      path: /api/other

snapshots:
  count: 4                      # снимков heap/histogram/threads/actuator за окно, минимум 3
  minMonotonicPointsForLeak: 3  # подряд растущих точек, чтобы считать тренд утечкой

thresholds:
  heapGrowthNoiseMb: 5          # рост между соседними точками ниже этого — шум
  threadGrowthNoise: 3          # то же для числа живых потоков
  gcPauseMaxMs: 500             # выше — finding gc_pause
  connectionsPendingMax: 0      # выше — finding connection_starvation

comparison:
  magnitudeNoisePercent: 10     # |delta| <= noise -> SAME
  magnitudeImprovementPercent: 20
  magnitudeRegressionPercent: 20

commands:                       # только реально существующие команды
  build: <command>
  start: <command>
  readiness: <command>
  collect: profiler/collect.sh
  stop: <command>
  reset: <command-or-null>
```

Правила:

- `id` стабилен: смена ID делает историю несравнимой (fingerprint включает
  содержимое файла).
- `load.targets` — только то, что discovery подтвердил безопасным для
  конкурентного вызова (см. `performance_discovery.md`, раздел «Профиль
  нагрузки для диагностики»). Не добавляй сюда цели самостоятельно.
- `load.concurrency` не выше отражённых в конфигурации пределов пула потоков
  сервера/пула соединений к БД, если это не намеренный стресс-тест пула.
- `snapshots.count` >= 3 — меньше не даёт статистически надёжного тренда
  (см. `references/detection-rules.md`).
- Все команды — реально существующие в текущем репозитории; вымышленные
  запрещены. `build`/`start`/`readiness`/`stop` обычно совпадают с теми, что
  уже определены для `java-performance-measurement` в `performance_discovery.md`.
- Изменение содержимого файла меняет profile fingerprint — старые находки
  станут `NOT_COMPARABLE`. Это ожидаемое поведение.

## Пример: Spring Boot HTTP-сервис

```yaml
version: 1
id: sensorhub-mixed-load

load:
  duration_s: 60
  concurrency: 8
  targets:
    - method: GET
      path: /api/reports/daily?from=2026-04-01&to=2026-04-07
    - method: GET
      path: /api/measurements?page=0&size=50
    - method: GET
      path: /api/stations?page=0&size=20
    - method: GET
      path: /api/reports/top?limit=10

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
  build: mvn -B clean package -DskipTests
  start: profiler/../perf/start-app.sh
  readiness: grep -q "seed: stations=" perf/.app-load.log
  collect: profiler/collect.sh
  stop: perf/kill-app.sh
  reset: curl -sf -X POST http://localhost:8080/internal/reset
```

Примечание: переиспользование `start`/`stop`/`readiness` из `perf/` (созданного
`java-performance-measurement`) — это выбор конкретного проекта, а не
требование skill'а. `profiler` не зависит от того, что `java-performance-measurement`
уже отработал — он читает те же команды из `performance_discovery.md`
самостоятельно и, если своих `start-app.sh`/`kill-app.sh` под диагностику ещё
нет, создаёт собственные в `profiler/`.
