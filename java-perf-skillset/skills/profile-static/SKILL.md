---
name: profile-static
description: Статический анализ Java-проекта тремя встроенными линтерами (CheckStyle, PMD, SpotBugs) — третий режим системы профилирования. Обязательно используй этот skill, когда пользователь вызывает /profile-static, просит прогнать линтеры, статические проверки стиля/smells/багов или быструю проверку кода без запуска приложения. Проектно-независим (линтеры вендорены в skill), выход — единый STATICREPORT.md в корне проекта за 1-2 минуты. Не запускает приложение и не меняет код; для runtime-профилирования используй /profile или /profile-short.
---

# Profile Static — Статические анализаторы кода

## Назначение

Третий режим системы анализа неоптимального кода (наряду с `/profile` и
`/profile-short`): быстрая статическая проверка Java-проекта тремя
вендореными линтерами, без запуска приложения и без измерений.

1. **CheckStyle** (10.21.0) — структурные smells: сложность, размер, опасные конструкции
2. **PMD** (7.8.0) — design/bestpractices/errorprone smells, dead code
3. **SpotBugs** (4.8.6) — реальные баги по байткоду: NPE, утечки ресурсов, concurrency

Вход: путь к Java-проекту (Maven или Gradle).
Выход: единый `STATICREPORT.md` в корне проекта.
Время: ~15 сек на 100 файлов, 1-2 минуты на большом проекте.

## Запуск

Вся механика — один скрипт (линтеры запускаются параллельно):

```bash
bash ~/.claude/skills/profile-static/scripts/orchestrate.sh <project-root> [severity] [mode]
```

- `severity` — минимальный уровень в отчёте: `all` (по умолчанию) |
  `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | `INFO`
- `mode` — `all` (по умолчанию) | `checkstyle-only` | `pmd-only` | `spotbugs-only`

Примеры вызова пользователем:

```bash
/profile-static --project-root /path/to/project                # все три линтера
/profile-static --project-root . --checkstyle-only             # только CheckStyle
/profile-static --project-root . --severity HIGH               # только HIGH и CRITICAL
```

Маппинг флагов на аргументы orchestrate.sh: `--severity X` → второй
аргумент; `--<tool>-only` → третий аргумент.

## Структура skill'а (фактическая)

```
~/.claude/skills/profile-static/
├── SKILL.md
├── linters/
│   ├── checkstyle/checkstyle-10.21.0-all.jar
│   ├── pmd/pmd-bin-7.8.0/
│   ├── spotbugs/spotbugs-4.8.6/
│   ├── rulesets/
│   │   ├── checkstyle-smells.xml      (curated smell-подмножество)
│   │   └── pmd-smells.xml             (design/bestpractices/errorprone)
│   ├── versions.lock                  (pinned версии + URL + SHA-256)
│   └── checksums.sha256
└── scripts/
    ├── orchestrate.sh                 (точка входа: параллельный запуск + отчёт)
    ├── run-checkstyle.sh              (XML → нормализованный JSON)
    ├── run-pmd.sh                     (PMD 7 `check` → нормализованный JSON)
    ├── run-spotbugs.sh                (байткод-анализ → нормализованный JSON)
    ├── normalize-findings.py          (общая схема находок для всех трёх)
    └── render-static-report.py        (агрегация → STATICREPORT.md)
```

## Контракт находок

Каждый runner пишет `<project-root>/.profile-run/<tool>-findings.json` в
общей схеме (нормализует `normalize-findings.py`):

```json
{"tool": "checkstyle|pmd|spotbugs", "file": "src/main/java/...",
 "line": 42, "column": 5, "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO",
 "rule": "CyclomaticComplexity", "message": "..."}
```

Severity-маппинг: CheckStyle error→HIGH, warning→MEDIUM; PMD priority
1→CRITICAL … 5→INFO; SpotBugs rank 1-4→CRITICAL, 5-9→HIGH, 10-14→MEDIUM,
15-20→LOW.

## Требования и деградация

- **Java 11+** в PATH — нужна всем трём линтерам.
- **Python 3.10+** (`python3`/`python`/`py`) — нормализация и отчёт.
- **SpotBugs требует скомпилированный код**: orchestrate.sh сам вызывает
  `mvn compile` / `./gradlew classes`, если `target/classes` (или
  `build/classes/java/main`) отсутствует. Если сборка не удалась —
  SpotBugs пропускается, отчёт строится по остальным линтерам.
- Падение одного линтера не срывает прогон: отчёт агрегирует то, что есть.

## Жёсткие ограничения

- Не редактируй файлы проекта — единственные создаваемые файлы:
  `STATICREPORT.md` и `.profile-run/*-findings.json`.
- Не меняй версии линтеров (pinned в `linters/versions.lock`, сверяй
  SHA-256 при обновлении).
- Rulesets — только встроенные `checkstyle-smells.xml` / `pmd-smells.xml`;
  SpotBugs идёт со встроенными правилами (`-maxRank 15`).
- Фиксы находок — не в этом skill'е: сортированный STATICREPORT.md отдай
  пользователю; автоматическое применение — через `apply-recommendations`
  только по явной просьбе.

## Troubleshooting

- **"CheckStyle JAR not found"** — проверь `linters/checkstyle/checkstyle-10.21.0-all.jar`.
- **"Compiled classes not found"** — запусти `mvn compile` (или `gradle classes`) и повтори.
- **PMD ругается на exclude в ruleset** — имена правил меняются между
  мажорными версиями PMD; поправь `linters/rulesets/pmd-smells.xml`.
- **Много ложных срабатываний** — сузь отчёт фильтром (`--severity HIGH`),
  rulesets в skill'е не редактируй.

## Перед завершением

Проверь:
- `STATICREPORT.md` создан в корне проекта и содержит сводную таблицу по
  трём линтерам;
- ни один файл проекта, кроме `STATICREPORT.md` и
  `.profile-run/*-findings.json`, не изменён;
- если какой-то линтер упал — это явно сказано в ответе;
- последняя строка ответа — путь к `STATICREPORT.md` и суммарное число находок.
