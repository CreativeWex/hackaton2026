# Схема `.profile-run/`

## `run-state.json`

Пишется в конце Фазы 0, обновляется в конце Фаз 1 и 2. Единственный
источник истины о том, можно ли продолжить прерванный прогон
(`--resume`/повторный `/profile`) и с какого места:

```json
{
  "gitAvailable": true,
  "branch": "profile/2026-07-28T18-00-00Z",
  "baseBranch": "main",
  "startedAt": "2026-07-28T18-00-00Z",
  "phase1Complete": true,
  "phase2Complete": true
}
```

`gitAvailable` определяется один раз в Фазе 0 и не меняется до конца
прогона. `false` → `branch`/`baseBranch` — `null`, Фаза 1 не коммитит,
Фаза 3 не делает git-коммитов (только чекпоинты — см. ниже), Фаза 4
заканчивается на `PROFILE_REPORT.md` без push/PR.

Если файла нет — обычный старт (Фаза 0). Если есть — (при `gitAvailable:
true`) `git checkout <branch>` и продолжение с той фазы, которая ещё не
`Complete` (см. Фазу 0 в `SKILL.md`).

## `checkpoints/<seq>-<queueId>/`

Пишется `scripts/checkpoint_save.py` при каждой принятой находке —
**независимо от `gitAvailable`**, это основной механизм точечного отката,
не резервный. `seq` — монотонно растущий номер (4 цифры, `0001`, `0002`,
...), `queueId` — тот же, что в `queue.json` (спецсимволы заменены на `_`).

```
checkpoints/
  0001-algorithm_inefficiency_report.md__list-contains-in-loop/
    meta.json
    patches/
      src__main__java__Foo.java.patch
  0002-query_issues_report.md__n-plus-1-stations/
    meta.json
    patches/
      ...
```

`meta.json`:
```json
{
  "schemaVersion": 1,
  "seq": 1,
  "queueId": "algorithm_inefficiency_report.md::list-contains-in-loop",
  "label": "список станций через .contains() в цикле",
  "files": [
    {"relpath": "src/main/java/Foo.java", "patchFile": "src__main__java__Foo.java.patch"}
  ]
}
```

Каждый `.patch` — обычный unified diff (`a/<relpath>` / `b/<relpath>`
заголовки, формат совместим с `git apply`/`patch -p1`). Откат —
`scripts/checkpoint_revert.py --project-root . --last N` (самые свежие
чекпоинты первыми) или `--queue-id <id>` (конкретный). Механика: `patch -R
-p1` в строгом обратном хронологическом порядке; на первом конфликте
(более поздний чекпоинт задел те же строки) — стоп, ничего дальше (то есть
ничего *старше*) не трогается, `.orig`/`.rej`, которые оставляет `patch`
при неудаче, автоматически подчищаются, рабочее дерево при конфликте
остаётся ровно таким, каким было до попытки отката.

**Известное ограничение**: файл, который фикс создал с нуля вне списка
`location` находки (не в снимке "до"), не попадёт в патч — при откате
такой файл не удалится. На практике редкость: находки почти всегда правят
уже существующий, уже отмеченный код.

## `queue.json`

Создаётся `scripts/build_queue.py` в Фазе 2, обновляется `scripts/queue_update.py`
на протяжении Фазы 3. Не коммитится (внутреннее состояние оркестратора,
`.profile-run/` — в `.gitignore`).

```json
{
  "schemaVersion": 1,
  "reportsSeen": ["profiler_report.md", "algorithm_inefficiency_report.md"],
  "totalFindings": 2,
  "items": [
    {
      "queueId": "algorithm_inefficiency_report.md::list-contains-in-loop",
      "reportFile": "algorithm_inefficiency_report.md",
      "producerSkill": "find-algorithm-inefficiency",
      "verificationTrack": "measurement",
      "status": "pending",
      "attempts": [],
      "findingId": "list-contains-in-loop",
      "label": "...",
      "severity": "high",
      "confidence": "high",
      "symptom": "...",
      "location": "...",
      "recommendedFix": "...",
      "verification": "...",
      "evidence": "...",
      "commitSha": "abc1234"
    }
  ]
}
```

## Поля находки

- `queueId` — `<reportFile>::<findingId>`, уникальный ключ (простой
  `findingId` уникален только внутри одного отчёта).
- `verificationTrack` — `measurement` (`find-*`) или `profiler`
  (`profiler_report.md`, а также утечечные категории
  `resource_management_report.md`/`unbounded_cache_or_queue_report.md`,
  чей эффект виден только под длительной смешанной нагрузкой) — жёстко
  задано таблицей в `build_queue.py`, не зависит от текста поля
  `verification` самой находки.
- `status` — один из:
  - `pending` — ещё не взята в работу;
  - `in_progress` — оркестратор сейчас работает над ней (используется,
    чтобы отличить прерванный на середине прогон от завершённого);
  - `committed` — принята, есть `commitSha`;
  - `skipped-resolved` — на момент фикса находка уже была неактуальна;
  - `skipped-blocked` — конфликт с проектным правилом;
  - `skipped-3-attempts` — три попытки, ни одна не прошла verify без
    регрессии (или `apply-recommendations` сам объявил, что безопасного
    пути нет);
  - `skipped-infra` — `NOT_COMPARABLE`/`FAILED` при верификации либо
    `Build/test: SKIPPED` у фиксера (нет команды сборки) — это не вина
    правки, попытка не расходуется.
- `attempts` — список объектов `{attemptNumber, verdict, metric?,
  deltaPercent?, note?}`, по одному на каждую неудачную (или последнюю,
  успешную) попытку. `verdict` — одно из `BETTER|SAME|WORSE|MIXED|
  INCONCLUSIVE|NOT_COMPARABLE|FAILED|BUILD_FAILED|BUILD_SKIPPED|
  NO_SAFE_APPROACH` (последние три — не вердикты measurement/profiler, а
  исходы самого `apply-recommendations`).
- `commitSha` — проставляется только при `status: committed`.
- `mergedFrom` (опционально) — если несколько находок из **разных**
  `find-*`/`profiler-find-problem` указывали на пересекающееся место в коде
  (тот же файл, строки в пределах `LOCATION_WINDOW_LINES` = 3 друг от
  друга), `build_queue.py` схлопывает их в одну (QG-merge): побеждает
  находка с более высоким `severity`→`confidence`, остальные попадают сюда
  списком `{queueId, producerSkill, label}` вместо того, чтобы становиться
  отдельными элементами очереди. Без этого один и тот же цикл "для каждой
  станции — отдельный запрос" мог бы одновременно всплыть в
  `find-query-issues` (N+1), `find-missing-batching` и
  `find-inefficient-api-usage` — три отдельных прогона фикс→verify по сути
  на одно и то же место, причём второй и третий с высокой вероятностью
  просто увидели бы, что находка уже неактуальна (см. `apply-recommendations`,
  «Если находка уже неактуальна»), потратив полный цикл впустую.
  Находки без разбираемого `` `file.java:NN` `` в `location` никогда не
  сливаются — нет координат, нет основания считать их одним дефектом.

## Анти-starvation порядок (`--family-quota`, по умолчанию 3)

После сортировки по приоритету `build_queue.py` не даёт более
`family-quota` находок одного `producerSkill` подряд — если сортировка по
severity/confidence сложила бы, скажем, 20 находок `find-query-issues`
раньше единственной находки `find-gc-pressure`, после третьей подряд
`find-query-issues` в очередь подтягивается ближайшая по приоритету
находка **другого** skill'а, а прерванная серия продолжается после нее.
Это не блокирует ни одну находку — только меняет порядок внутри и так уже
приоритетно отсортированного списка; если альтернативного skill'а не
осталось вовсе, серия продолжается без ограничения (quota — предпочтение
разнообразия, а не жёсткий потолок, который мог бы когда-либо не пропустить
реальный фикс). `--family-quota 0` отключает это поведение полностью.

## Инварианты, которые Фаза 3 обязана поддерживать

- Любая находка в терминальном статусе (`committed`/`skipped-*`) больше не
  выбирается `queue_next.py`.
- `attempts.length` никогда не превышает 3.
- Диф каждой неудачной попытки нигде не хранится в `queue.json` (может
  быть большим) — только вердикт/метрика/заметка; сам диф передаётся в
  retry-вызов `apply-recommendations` напрямую в аргументах, не через файл.
