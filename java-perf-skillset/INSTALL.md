# Java Performance Skillset — установка

Это инструкция для Claude Code, который её выполняет — не для человека
напрямую. Если ты Claude Code и получил эту папку с просьбой "установи
скилл" — следуй шагам ниже по порядку, сверяясь с чеклистом в конце.

## Что это

29 персональных skill'ов Claude Code, вместе образующих замкнутую систему
анализа и исправления неоптимального кода в Java-проектах:

```
/profile-orchestrator (предпочтительная точка входа; /profile — legacy-алиас)
  ├─ java-performance-discovery   — анализирует проект, пишет performance_discovery.md
  ├─ java-performance-measurement — JMH/HTTP/CLI измерения, initial/incremental/final
  ├─ profiler                     — утечки памяти/дедлоки под нагрузкой
  ├─ profiler-find-problem        — находит причину и место в коде по находкам profiler
  ├─ profile-orchestrator         — дирижёр: однократный project index (кэш по Git SHA),
  │                                 evidence-driven выбор максимум 3 analysis packs,
  │                                 единый JSONL-контракт находок, очередь фиксов,
  │                                 итоговый PROFILEREPORT.md
  ├─ find-* (22 детектора)        — статический анализ кода по категориям
  │                                 (алгоритмы, N+1, кэши, GC-давление, конкурентность…);
  │                                 запускаются только выбранные роутером, пишут JSONL
  │                                 в .profile-run/findings.jsonl, не Markdown
  ├─ apply-recommendations        — применяет одну рекомендацию к коду, проверяет сборку
  └─ profile                      — legacy-алиас: делегирует прогон profile-orchestrator'у;
                                    его Фазы 0/3/4 и scripts/ (очередь, чекпоинты) —
                                    общая механика цикла исправлений
```

Подробно про каждый — в `skills/<имя>/SKILL.md`. Начни оттуда, если нужно
понять, что конкретно делает один skill, эта инструкция — только про
установку.

## Что нужно на машине до установки

- Claude Code (у тебя уже есть, раз ты это читаешь).
- Java-проект, на котором это будет запускаться: JDK, Maven/Gradle —
  требования зависят от конкретного проекта, `java-performance-discovery`
  сам разберётся при первом запуске.
- Python 3.10+ — используется несколькими skill'ами (`profiler`,
  `profile`, `profile-orchestrator` — индекс проекта, роутер, очередь,
  финальный отчёт) для детерминированной агрегации/сравнения результатов.
  Проверь: `py -3 --version` (Windows), `python3 --version` или
  `python --version`. Осторожно на Windows: `python`/`python3` могут быть
  заглушками Microsoft Store, которые печатают мусор или открывают Store
  вместо запуска — `py -3` надёжнее. Если версии нет — поставь перед первым
  запуском `/profile`, иначе часть шагов упадёт.
- `diff`/`patch` (GNU diffutils/patch) — на Linux/macOS уже есть, на
  Windows идут в комплекте с Git for Windows (Git Bash) — если Claude Code
  на Windows работает не через Git Bash, поставь их отдельно.
- Git — не обязателен (система работает и без него, откат тогда идёт
  только через чекпоинты `profile`, не через git), но с ним лучше: ветка +
  коммит на каждый принятый фикс + Pull Request в конце.
- `gh` CLI, установлен и авторизован (`gh auth status`) — опционально,
  нужен только для автоматического создания PR в конце `/profile`. Без
  него всё остальное работает, PR просто не откроется сам.

## Шаги установки

### 1. Скопируй все 29 папок скиллов в `~/.claude/skills/`

Для каждой подпапки в `skills/` этого пакета — скопируй её целиком в
`~/.claude/skills/<то же имя>/`. Если у пользователя уже есть skill с
таким именем — спроси явно, заменять ли (не перезаписывай молча чужой
кастомный skill с совпадающим именем).

```bash
mkdir -p ~/.claude/skills
cp -r skills/* ~/.claude/skills/
```

(Windows/PowerShell: `Copy-Item -Recurse -Force skills\* $HOME\.claude\skills\`)

### 2. Скопируй hook-скрипт

```bash
mkdir -p ~/.claude/hooks
cp hooks/profile-guard.sh ~/.claude/hooks/profile-guard.sh
chmod +x ~/.claude/hooks/profile-guard.sh
```

Это technical guardrail: пока идёт `/profile`, физически блокирует запись
в `src/test/**`, `harness/**`, `scripts/**`, `judge/**`, `perf/**`,
`.performance/**`, `profiler/**`, `.profiler/**`, `*_report.md`,
`performance_discovery.md` — независимо от того, следует ли
`apply-recommendations` своей собственной инструкции. Вне активного
прогона `/profile` — no-op, на обычную работу не влияет.

### 3. Впиши hook в `~/.claude/settings.json` — ОБЯЗАТЕЛЬНО слиянием, не перезаписью

**Сначала прочитай существующий `~/.claude/settings.json`** (если файла
нет — создай с содержимым `{}`). Добавь в `hooks.PreToolUse` следующий
элемент, **сохранив всё остальное содержимое файла как есть** — не
затирай чужие настройки/другие hooks/permissions:

```json
{
  "matcher": "Edit|Write|MultiEdit",
  "hooks": [
    {
      "type": "command",
      "command": "bash ~/.claude/hooks/profile-guard.sh",
      "statusMessage": "Checking /profile path guard..."
    }
  ]
}
```

Если в файле уже есть `hooks.PreToolUse` с другими элементами (другой
`matcher`) — добавь этот элемент в тот же массив, не заменяй массив
целиком. Если уже есть элемент с точно таким же `matcher` от другого
источника — спроси пользователя, как объединить, не перезаписывай молча.

После правки — проверь, что `~/.claude/settings.json` остаётся валидным
JSON (прочитай и распарси перед тем как считать шаг выполненным).

### 4. Проверка окружения (read-only, ничего не меняет)

Прогони и покажи результат пользователю, не переходи к шагу 5 молча, если
что-то из обязательного отсутствует:

```bash
java -version
(py -3 --version || python3 --version || python --version)
diff --version | head -1
patch --version | head -1
(git --version) || echo "git недоступен — /profile будет работать в режиме без ветки/коммитов/PR"
(gh --version && gh auth status) || echo "gh недоступен/не авторизован — PR в конце не откроется автоматически"
```

## Проверка после установки

Прежде чем сказать пользователю "готово", убедись:

- `~/.claude/skills/` содержит все 29 папок из `skills/` этого пакета
  (сверь по списку в начале этого файла);
- `~/.claude/hooks/profile-guard.sh` существует и исполняем;
- `~/.claude/settings.json` — валидный JSON, содержит hook из шага 3, и
  **при этом сохранил всё, что было в файле до установки**;
- Python и `diff`/`patch` реально найдены в PATH (шаг 4) — если нет, явно
  скажи пользователю, что нужно доустановить, прежде чем `/profile` можно
  будет запускать.

## Как пользоваться после установки

В терминале Claude Code, находясь в корне Java-проекта:

```
/profile-orchestrator
```

(legacy `/profile` тоже работает — делегирует прогон сюда же с `--full`.)

Дальше — полностью автономно (может идти часы): discovery → baseline
измерение → baseline профилирование → однократный project index (кэш по
Git SHA в `.profile-run/project-index.json`) → компактный
`.profile-run/evidence.json` → роутер выбирает максимум 3 analysis packs
(`.profile-run/analysis-plan.json`; без evidence — fallback
`data-access` + `cpu-hotpath`) → только выбранные детекторы пишут
находки в `.profile-run/findings.jsonl` (единый JSONL-контракт, без
промежуточных Markdown-отчётов) → агрегация/дедупликация → очередь
фиксов → по одной применяет, проверяет измерением, коммитит или
откатывает → в конце единственный сводный отчёт `PROFILEREPORT.md` и,
если есть git+remote+gh, Pull Request.

Migration note: `*_report.md`-отчёты детекторов и `PROFILE_REPORT.md`
устарели и больше не создаются — оставшиеся от старых прогонов файлы
никем не читаются, их можно удалить.

Если прогон прервался (закрыли сессию, упало окружение) — просто снова
`/profile-orchestrator` в той же папке, продолжит с места остановки
(`.profile-run/run-state.json` хранит прогресс).

Откатить последний автоматический фикс (или несколько) отдельно от
`/profile`, в любой момент:

```bash
python3 ~/.claude/skills/profile/scripts/checkpoint_revert.py --project-root . --last 1
```

(на Windows — `py -3` вместо `python3`)
