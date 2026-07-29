# Java Performance Analysis Skillset

Полный набор инструментов для анализа производительности Java приложений.
**Три режима анализа** + **встроенные статические анализаторы**.

---

## 🚀 Быстрый старт

### Установка

1. **Скопируй папки в `.claude/skills/`:**
```bash
cp -r profile* ~/.claude/skills/
```

2. **Проверь установку:**
```bash
ls ~/.claude/skills/ | grep profile
```

Должны появиться:
- `profile/` — основной анализатор (legacy)
- `profile-orchestrator/` — smart routing orchestrator
- `profile-short/` — краткий анализ
- `profile-static/` — статические анализаторы
- `profiler/` — runtime profiler
- `profiler-find-problem/` — анализ находок

### Первый запуск

```bash
cd /path/to/your/java/project
/profile-short --project-root .
```

Результат: **PROFILEREPORT.md** в корне проекта

---

## 📋 Три режима анализа

### 1. **`/profile-short`** — Краткий прогон (2-5 мин)

Найти **критичные ошибки производительности** быстро.

```bash
/profile-short --project-root .
```

**Фокус:** 
- N+1 queries (data-access)
- Unbatched writes
- Algorithm inefficiency
- Redundant computation

**Для:** PR checks, fast feedback

---

### 2. **`/profile`** — Полный прогон (10-20 мин)

Полный анализ **всех 22 детекторов**.

```bash
/profile --project-root .
```

**Фокус:** 
- Все категории проблем
- Memory/GC
- Concurrency
- I/O observability
- Dead code cleanup

**Для:** Release candidate, comprehensive audit

---

### 3. **`/profile-static`** — Статические анализаторы (1-2 мин)

Быстрые проверки **стиля кода и багов** без запуска приложения.

```bash
/profile-static --project-root .
```

**Инструменты:**
- ✅ **CheckStyle** — style violations
- ✅ **PMD** — code smells & bugs
- ✅ **SpotBugs** — potential bugs

**Варианты:**
```bash
# Только CheckStyle
/profile-static --project-root . --checkstyle-only

# Только критичные (high, critical)
/profile-static --project-root . --severity high,critical
```

**Для:** Pre-commit checks, CI/CD

---

## 📊 Сравнение режимов

| Аспект | /profile-short | /profile | /profile-static |
|--------|---|---|---|
| **Время** | 2-5 мин | 10-20 мин | 1-2 мин |
| **Detectors** | 4 (критичные) | 22 (все) | 3 (CheckStyle, PMD, SpotBugs) |
| **Глубина** | Shallow | Deep | Static only |
| **Requires run** | Yes | Yes | No (compile only) |
| **Output** | PROFILEREPORT.md | PROFILEREPORT.md | STATICREPORT.md |
| **Ideal for** | PR reviews | Releases | Code style |

---

## 🏗️ Архитектура

### Трехуровневая система

```
Java Performance Analysis System
│
├─ /profile-short          ← Evidence-driven short analysis
│  └─ max 2 packs: data-access + cpu-hotpath
│
├─ /profile                ← Full legacy analysis (22 detectors)
│  └─ all 6 packs
│
└─ /profile-static         ← Static checks (no runtime)
   ├─ CheckStyle (style)
   ├─ PMD (smells)
   └─ SpotBugs (bugs)
```

### Packs (Детекторы):

1. **data-access** — Database queries, batching, caching
2. **cpu-hotpath** — Algorithm complexity, redundant computation
3. **memory-gc** — Memory leaks, GC pressure
4. **concurrency** — Thread safety, locking
5. **io-observability** — Logging overhead, exceptions
6. **cleanup** — Dead code

---

## 📝 Примеры использования

### Пример 1: Быстрая проверка перед PR

```bash
# Только критичные проблемы (2 мин)
cd my-project
/profile-short --project-root .
# Проверь PROFILEREPORT.md
git add PROFILEREPORT.md && git commit -m "perf: fix critical issues"
```

### Пример 2: Pre-commit hooks

```bash
#!/bin/bash
# .git/hooks/pre-commit
cd $(git rev-parse --show-toplevel)
/profile-static --project-root . --severity high,critical
if [ $? -ne 0 ]; then
  echo "Fix static analysis issues before commit"
  exit 1
fi
```

### Пример 3: Release preparation

```bash
# Полный анализ перед релизом (20 мин)
/profile --project-root . --full
# Смотри PROFILEREPORT.md
# Все исправления автоматически применены и проверены
```

### Пример 4: Параллельные проверки

```bash
# Статические анализаторы не требуют runtime
/profile-static --project-root . &

# Запусти profiling параллельно
/profile-short --project-root . 

wait
# Оба завершены, есть два отчета
```

---

## 📂 Структура скиллов

```
java-perf-skillset/
├── profile/                    # Legacy full profiler
│   ├── SKILL.md
│   ├── scripts/                # Основные скрипты
│   └── references/
│
├── profile-orchestrator/       # Smart routing
│   ├── SKILL.md
│   └── scripts/
│       ├── build_project_index.py
│       ├── route_analysis.py
│       ├── findings_to_queue.py
│       └── render_profile_report.py
│
├── profile-short/              # Short analysis
│   └── SKILL.md
│
├── profile-static/             # Static analyzers
│   ├── SKILL.md
│   ├── linters/
│   │   ├── checkstyle/
│   │   ├── pmd/
│   │   ├── spotbugs/
│   │   └── rulesets/
│   └── scripts/
│       ├── orchestrate.sh
│       ├── run-checkstyle.sh
│       ├── run-pmd.sh
│       ├── run-spotbugs.sh
│       └── render-static-report.py
│
├── profiler/                   # Runtime profiler
│   ├── SKILL.md
│   ├── scripts/
│   └── references/
│
└── profiler-find-problem/      # Profiler analysis
    └── SKILL.md
```

---

## ⚙️ Требования

### Обязательные:
- **Java 21+** (Temurin или OpenJDK)
- **Maven 3.8+** (или используй `./mvnw`)
- **Python 3.10+** (для скриптов анализа)

### Опциональные:
- **Git** (для коммитов, чекпоинтов, PR)
- **Prometheus metrics** (для визуализации)

### Проверка окружения:

```bash
java -version          # должен быть Java 21+
mvn -v                 # Maven 3.8+
python3 --version      # Python 3.10+
```

---

## 🔍 Детали каждого режима

### /profile-short — Фазы

1. **Baseline** — снять baseline метрики (sql_count, elapsed_ms, heap)
2. **Profiler** — записать JFRTrace
3. **Analyze** — запустить only critical detectors (N+1, batching, hotspots)
4. **Apply** — автоматически применить fixes
5. **Verify** — перемерить и убедиться improvement
6. **Report** — PROFILEREPORT.md

### /profile — Фазы (как legacy /profile)

1. **Discovery** → **Baseline** → **Profiler**
2. **Route Analysis** → выбрать все 6 packs
3. **Run All Detectors** (22 штуки)
4. **Apply Recommendations**
5. **Incremental Measurement**
6. **Final Report**

### /profile-static — Параллельный запуск

- CheckStyle (2 сек)
- PMD (5 сек)
- SpotBugs (8 сек) — requires `mvn compile`
- Parallel execution, sequential report

---

## 📊 Выводы (Output)

### /profile-short и /profile

**PROFILEREPORT.md** содержит:
- Summary (total issues, critical/high/medium)
- Detailed findings (с file:line, description, fix)
- Before/after metrics
- Checkpoints and rollback instructions
- Applied fixes summary

### /profile-static

**STATICREPORT.md** содержит:
- CheckStyle issues (style violations)
- PMD issues (code smells)
- SpotBugs issues (potential bugs)
- Severity breakdown
- Actionable recommendations

---

## 🎯 CI/CD Integration

### GitHub Actions example

```yaml
name: Performance Check

on: [pull_request]

jobs:
  profile:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-java@v3
        with:
          java-version: '21'
      
      # Quick check
      - name: Profile Short
        run: /profile-short --project-root .
      
      # Static checks
      - name: Profile Static
        run: /profile-static --project-root .
      
      - name: Upload Reports
        uses: actions/upload-artifact@v3
        with:
          name: performance-reports
          path: |
            PROFILEREPORT.md
            STATICREPORT.md
```

---

## 🆘 Troubleshooting

### "java: command not found"
```bash
export JAVA_HOME=/path/to/jdk-21
# или используй: ./mvnw (Maven Wrapper)
```

### "SpotBugs requires compiled code"
```bash
mvn clean compile
/profile-static --project-root .
```

### "Port 8080 already in use"
```bash
# Kill existing Java process
pkill -f "java.*sensorhub"
# или используй скрипт: ./scripts/kill-app.sh
```

### "No findings found"
- Это нормально — приложение может быть оптимизировано
- Проверь что базовые метрики собираются: `PROFILEREPORT.md`

---

## 📚 Дальше читай

- `profile/SKILL.md` — полная документация legacy profiler
- `profile-orchestrator/SKILL.md` — smart routing система
- `profile-short/SKILL.md` — краткий режим
- `profile-static/SKILL.md` — статические анализаторы

---

## 👥 Для коллег

### Что это дает?

1. **Автоматический поиск** узких мест производительности
2. **Быстрые проверки** (2-5 мин вместо часов ручного анализа)
3. **Унифицированный отчет** PROFILEREPORT.md
4. **Автоматические исправления** с верификацией
5. **Встроенные статические проверки** (CheckStyle, PMD, SpotBugs)

### Как начать?

```bash
# 1. Скопировать скилы
cp -r profile* ~/.claude/skills/

# 2. Перейти в папку проекта
cd /your/java/project

# 3. Запустить краткий анализ
/profile-short --project-root .

# 4. Прочитать отчет
cat PROFILEREPORT.md
```

**Готово!** 🎉

---

## 📝 Заметки

- Все скилы полностью независимы и могут использоваться отдельно
- Система работает с любым Java проектом (Spring Boot, plain Java, etc.)
- Все findings пишутся в JSONL формат в `.profile-run/findings.jsonl`
- Автоматические чекпоинты позволяют откатить любое исправление
- Git интеграция опциональна (работает и в git repo, и в обычной папке)

---

**Версия:** 2.0 (2026-07-29)  
**Автор:** Claude Code  
**License:** MIT
