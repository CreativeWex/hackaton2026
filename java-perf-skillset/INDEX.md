# Java Performance Skillset — Index

**Версия:** 2.0  
**Дата:** 2026-07-29  
**Статус:** ✅ Production Ready

---

## 📦 Что включено

### Основные скилы (3 режима):

1. **`profile-short/`** — Краткий анализ критичных ошибок
   - Время: 2-5 минут
   - Детекторов: 4 (N+1, batching, hotspots, redundant computation)
   - Выход: `PROFILEREPORT.md`
   - Файлы: `SKILL.md`

2. **`profile/`** — Полный анализ (legacy)
   - Время: 10-20 минут
   - Детекторов: 22 (все категории)
   - Выход: `PROFILEREPORT.md`
   - Файлы: `SKILL.md`, `scripts/`, `references/`

3. **`profile-static/`** — Статические анализаторы
   - Время: 1-2 минуты
   - Инструменты: CheckStyle, PMD, SpotBugs
   - Выход: `STATICREPORT.md`
   - Файлы: `SKILL.md`, `scripts/`, `linters/`

### Поддерживающие компоненты:

4. **`profile-orchestrator/`** — Smart routing system
   - Файлы: `SKILL.md`, `scripts/`
   - Содержит: build_project_index.py, route_analysis.py, findings_to_queue.py, render_profile_report.py

5. **`profiler/`** — Runtime profiler
   - Файлы: `SKILL.md`, `scripts/`, `references/`

6. **`profiler-find-problem/`** — Анализ профайлера
   - Файлы: `SKILL.md`

### Документация:

- **`GETTING_STARTED.md`** — Полное руководство для новичков

- **`INSTALL.md`** — Инструкции установки
- **`INDEX.md`** — Этот файл

### Дополнительно:

- **`hooks/`** — Git hooks для интеграции
- **`skills/`** — канонический источник установки: 31 skill, копируются целиком

---

## 🚀 Установка (3 шага)

### Шаг 1: Скопировать скилы
```bash
cp -r skills/* ~/.claude/skills/
```

### Шаг 2: Проверить установку
```bash
ls ~/.claude/skills/ | grep profile
# Должны быть: profile, profile-short, profile-static, профайлер...
```

### Шаг 3: Готово!
```bash
cd /your/java/project
/profile-short .
```

---

## 📋 Чек-лист установки

- [ ] Скопирована вся 31 папка из `skills/` (3 режима, оркестратор, 22 детектора, measurement/discovery/profiler, apply-recommendations)
- [ ] Проверены скрипты в `skills/profile-static/scripts/` (исполняемые)
- [ ] Проверены Python скрипты в `skills/profile-orchestrator/scripts/`
- [ ] Линтеры присутствуют в `skills/profile-static/linters/`:
  - [ ] `checkstyle-10.21.0-all.jar` (19 MB)
  - [ ] `pmd-bin-7.8.0/` (папка с bin/)
  - [ ] `spotbugs-4.8.6/` (папка с bin/)
  - [ ] `rulesets/` (checkstyle-smells.xml, pmd-smells.xml)
- [ ] Окружение готово (Java 21+, Maven, Python 3.10+)

---

## 📚 Документация по файлам

### Для начинающих:
1. Прочитай `GETTING_STARTED.md` (15 мин чтения)
2. Посмотри `README.md` (2 мин)
3. Запусти `/profile-short . ` на своем проекте

### Для опытных:
1. `skills/profile/SKILL.md` — legacy профилер (полная документация)
2. `skills/profile-orchestrator/SKILL.md` — smart routing (детали routing)
3. `skills/profile-short/SKILL.md` — краткий режим (параметры)
4. `skills/profile-static/SKILL.md` — статические проверки (конфигурация)

### Для интеграции:
- `hooks/profile-guard.sh` — git hook пример
- `INSTALL.md` — установка и конфигурация
- `skills/profile/references/queue-schema.md` — схема данных

---

## 🎯 Быстрые команды

```bash
# Краткий анализ (2-5м)
/profile-short --project-root .

# Полный анализ (10-20м)
/profile --project-root . --full

# Статические проверки (1-2м)
/profile-static --project-root .

# Только критичные (стиль)
/profile-static . --severity high,critical

# Продолжить прерванный
/profile-short --resume
```

---

## 📊 Структура skillset

```
java-perf-skillset/
│
├─ GETTING_STARTED.md    ← Начни отсюда
├─ INSTALL.md            ← Установка
├─ INDEX.md              ← Этот файл
├─ README.md
│
├─ hooks/                ← Git integration
│  └─ profile-guard.sh
│
└─ skills/               ← 31 skill, копируются целиком в ~/.claude/skills/
   ├─ profile/                 ← Legacy full profiler (SKILL.md + scripts/ + references/)
   ├─ profile-orchestrator/    ← Smart routing orchestrator (scripts: build_project_index,
   │                             route_analysis, findings_to_queue, render_profile_report)
   ├─ profile-short/           ← Краткий анализ (обёртка над orchestrator)
   ├─ profile-static/          ← Статические анализаторы
   │  ├─ linters/              ← CheckStyle, PMD, SpotBugs + rulesets/ + versions.lock
   │  └─ scripts/              ← orchestrate.sh, run-*.sh, normalize-findings.py,
   │                             render-static-report.py
   ├─ profiler/                ← Runtime profiler
   ├─ profiler-find-problem/   ← Анализ результатов профайлера
   ├─ java-performance-discovery/
   ├─ java-performance-measurement/
   ├─ apply-recommendations/   ← Единственный skill, меняющий код
   └─ find-*/                  ← 22 детектора (по одному на категорию)
```

---

## ✅ Верификация установки

Запусти это чтобы проверить установку:

```bash
# 1. Проверь что скилы видны
ls ~/.claude/skills/profile* 2>/dev/null | wc -l
# Должно быть: 6 (или больше если есть другие)

# 2. Проверь Python скрипты
python3 ~/.claude/skills/profile-orchestrator/scripts/build_project_index.py --help 2>/dev/null && echo "✓ Python OK"

# 3. Проверь линтеры
test -f ~/.claude/skills/profile-static/linters/checkstyle/checkstyle-10.21.0-all.jar && echo "✓ CheckStyle OK"
test -d ~/.claude/skills/profile-static/linters/pmd/pmd-bin-7.8.0 && echo "✓ PMD OK"
test -d ~/.claude/skills/profile-static/linters/spotbugs/spotbugs-4.8.6 && echo "✓ SpotBugs OK"

# 4. Проверь Java и Python
java -version 2>&1 | grep "21" && echo "✓ Java 21 OK"
python3 --version && echo "✓ Python OK"
```

---

## 🐛 Часто встречаемые проблемы

### "Skill not found"
```bash
# Проверь что скилы скопированы
ls ~/.claude/skills/ | grep profile
# Должны быть: profile, profile-short, profile-static, etc.
```

### "java.lang.UnsupportedClassVersionError"
```bash
# Нужна Java 21+
java -version
# Должно быть: openjdk version "21.x.x"
```

### "Python not found"
```bash
python3 --version
# Должно быть: Python 3.10+
```

### "CheckStyle JAR not found"
```bash
# Проверь что скопировалась папка linters/
ls ~/.claude/skills/profile-static/linters/checkstyle/
# Должен быть: checkstyle-10.21.0-all.jar (19 MB)
```

---

## 📞 Поддержка

### Если что-то не работает:

1. Прочитай `GETTING_STARTED.md`
2. Посмотри `README.md`
3. Проверь `INSTALL.md` инструкции
4. Запусти верификацию выше
5. Посмотри специфичный `SKILL.md` для нужного режима

### Документация по пакетам:

- **data-access** — N+1, batching, fetching issues
- **cpu-hotpath** — algorithm inefficiency, redundant computation
- **memory-gc** — memory leaks, GC pressure
- **concurrency** — thread safety, locking issues
- **io-observability** — logging, exception handling
- **cleanup** — dead code, unused variables

---

## 🎓 Рекомендуемый путь обучения

**День 1: Основы (30 мин)**
1. Прочитай `README.md` (5 мин)
2. Запусти `/profile-short . ` на своем проекте (5 мин)
3. Посмотри `PROFILEREPORT.md` (10 мин)
4. Примени одно исправление (10 мин)

**День 2: Углубленное изучение (1-2 часа)**
1. Прочитай `GETTING_STARTED.md` (30 мин)
2. Запусти `/profile-static . ` (10 мин)
3. Посмотри `profile/SKILL.md` детали (30 мин)
4. Попробуй `/profile . --full` (20 мин)

**День 3: Интеграция (1 час)**
1. Настрой git hooks (`hooks/profile-guard.sh`)
2. Добавь `/profile-static` в CI/CD
3. Создай template для PROFILEREPORT.md в своей документации

---

## 📈 Что дальше?

После установки и первого использования:

1. **Интегрируй в CI/CD** — добавь `/profile-static` в pre-commit
2. **Автоматизируй проверки** — запускай `/profile-short` при каждом PR
3. **Релизный процесс** — используй `/profile . --full` перед релизом
4. **Мониторинг** — сохраняй PROFILEREPORT.md в истории проекта

---

## 📝 Версионирование

| Версия | Дата | Что изменилось |
|--------|------|---|
| 2.0 | 2026-07-29 | Добавлены /profile-short и /profile-static, трехуровневая система |
| 1.1 | 2026-07-28 | Добавлен profile-orchestrator |
| 1.0 | 2026-07-27 | Исходная версия с /profile |

---

## 🙏 Спасибо за использование

Этот skillset создан для того чтобы сделать анализ производительности Java приложений быстрым, простым и автоматизированным.

**Happy profiling!** 🚀

---

**Для вопросов:** Смотри документацию в каждом скилле (SKILL.md)
