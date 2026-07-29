# Profile Static — Статические анализаторы кода

## Назначение

Встроенный skill для быстрой статической проверки Java проектов через три лучших открытых линтера:

1. **CheckStyle** — проверка стиля кода (именования, форматирование, соглашения)
2. **PMD** — поиск code smells и потенциальных багов (невысокая сложность)
3. **SpotBugs** — поиск настоящих багов (null pointers, resource leaks, concurrency issues)

Вход: путь к Java-проекту (любой размер, Spring Boot / plain Java).
Выход: единый `STATICREPORT.md` в корне проекта с агрегированными находками.

## Быстрый старт

```bash
# Все три линтера
/profile-static --project-root /path/to/project

# Только CheckStyle
/profile-static --project-root /path/to/project --checkstyle-only

# Только PMD
/profile-static --project-root /path/to/project --pmd-only

# Только SpotBugs
/profile-static --project-root /path/to/project --spotbugs-only

# С фильтром (игнорировать некритичные)
/profile-static --project-root /path/to/project --severity high,critical
```

## Линтеры и правила

### CheckStyle (v10.21.0)
- **Ruleset:** `src/main/resources/linting/checkstyle-smells.xml`
- **Проверяет:** именование классов/методов/полей, форматирование, длину строк, сложность, документацию
- **Выход:** строка кода + вид нарушения
- **Интеграция:** как Maven plugin или через JAR

### PMD (v7.8.0)
- **Ruleset:** `src/main/resources/linting/pmd-smells.xml`
- **Проверяет:** неиспользуемые переменные, пустые catch'и, дублирование кода, сложные методы
- **Выход:** строка кода + вид проблемы
- **Интеграция:** как Maven plugin или через CLI

### SpotBugs (v4.8.6)
- **Правила:** встроенные (no custom ruleset)
- **Проверяет:** null pointer dereferences, resource leaks, unsynchronized access, weak crypto
- **Выход:** строка кода + категория баги (critical/high/medium)
- **Интеграция:** как Maven plugin или через CLI

## Architektura skill'а

```
~/.claude/skills/profile-static/
├── SKILL.md                          (этот файл)
├── linters/
│   ├── checkstyle/
│   │   └── checkstyle-10.21.0-all.jar
│   ├── pmd/
│   │   └── pmd-bin-7.8.0/
│   ├── spotbugs/
│   │   └── spotbugs-4.8.6/
│   └── rulesets/
│       ├── checkstyle-smells.xml
│       └── pmd-smells.xml
├── scripts/
│   ├── run-checkstyle.sh
│   ├── run-pmd.sh
│   ├── run-spotbugs.sh
│   └── render-static-report.py
└── templates/
    └── staticreport.md.jinja
```

## Интеграция с /profile и /profile-short

Могут быть вызваны **параллельно** с режимами профилирования:

```bash
# Параллельно: profiling + static checks
/profile --project-root . --with-static

# После профилирования автоматически
/profile-short --project-root . --then-static
```

## Выход — STATICREPORT.md

Единый отчет со сводкой:

```markdown
# Static Analysis Report: PROJECT_NAME

## Summary
- CheckStyle: 12 issues (3 critical, 5 high, 4 medium)
- PMD: 8 issues (2 critical, 6 high)
- SpotBugs: 5 issues (2 critical, 3 high)

**Total: 25 issues | Critical: 7 | High: 14 | Medium: 4**

## CheckStyle Issues
[sorted by severity, location]

## PMD Issues  
[sorted by severity, location]

## SpotBugs Issues
[sorted by severity, location]

## Recommended Fixes
[grouped by file, actionable]
```

## Использование findings в apply-recommendations

Находки можно применить автоматически через `apply-recommendations` skill:

```json
{
  "id": "CS-001",
  "category": "static",
  "detector": "checkstyle",
  "severity": "medium",
  "confidence": 0.95,
  "location": {"file": "src/main/java/...", "line": 42},
  "finding": "MethodName should match pattern '^[a-z][a-z0-9]*$'",
  "suggested_fix": "Rename method from 'MethodName' to 'methodName'"
}
```

## Производительность

| Линтер | Файлов | Время | Зависит от |
|--------|--------|-------|-----------|
| CheckStyle | 100 | ~2 сек | размер проекта |
| PMD | 100 | ~5 сек | сложность кода |
| SpotBugs | 100 | ~8 сек | зависит от компиляции |
| **Всего** | 100 | **~15 сек** | параллелизация |

На большом проекте (500+ файлов) может занять 1-2 минуты.

## Жесткие ограничения

- Не редактируй файлы проекта кроме создания STATICREPORT.md
- Не добавляй новые rulesets — только используй встроенные checkstyle-smells.xml и pmd-smells.xml
- Не меняй версии линтеров (они кэшированы в versions.lock)
- Если линтер падает, попробуй очистить target/: `mvn clean`
- SpotBugs требует откомпилированного кода (`mvn compile` перед запуском)

## Безопасность

- Линтеры запускаются в песочнице (не имеют доступа вне проекта)
- Rulesets содержат только статические проверки (no code execution)
- Findings записываются в STATICREPORT.md (нет remote calls)

## Примеры

### Пример 1: Быстрая проверка при PR
```bash
/profile-static --project-root . --severity high,critical --output brief
# ~15 сек, только критичные проблемы в консоль
```

### Пример 2: Полная проверка перед release
```bash
/profile-static --project-root . --all-severities
# ~30 сек, полный отчет в STATICREPORT.md
```

### Пример 3: Совместно с профилированием
```bash
/profile --project-root . --full --then-static
# Профилирование (10-20 мин) + статические проверки (15 сек) = полный анализ
```

## Troubleshooting

**Ошибка: "CheckStyle JAR not found"**
- Убедись что `~/.claude/skills/profile-static/linters/checkstyle/checkstyle-10.21.0-all.jar` существует

**Ошибка: "PMD not found in PATH"**
- Используй полный путь: `~/.claude/skills/profile-static/linters/pmd/pmd-bin-7.8.0/bin/pmd`

**Ошибка: "SpotBugs requires compiled code"**
- Запусти `mvn clean compile` перед /profile-static

**Слишком много ложных срабатываний в CheckStyle**
- Отредактируй `checkstyle-smells.xml` в директории проекта (локальный override)

## Следующие шаги

1. Создать `run-checkstyle.sh`, `run-pmd.sh`, `run-spotbugs.sh` скрипты
2. Написать `render-static-report.py` для агрегации результатов
3. Интегрировать с apply-recommendations для автоматических фиксов
4. Добавить параллелизацию для больших проектов
