# PENDING_LEDGER — P0 «индекс есть, статус пуст» (2026-11-07)

> Реестры (`AGENT_DIARY.md`, `tools/knowledge/PATTERNS.md`) содержат
> незакоммиченные правки другой сессии, поэтому здесь — предложение, а не
> запись в реестр (§21.3).

## Что было

- Phase 3 (`dense_off=true`, с 2026-10-24) держит чанки в
  `<project>/.mscodebase/chunks.db`: **7 314 чанков / 487 файлов**.
- `IndexStatusReporter.get_status()` читал только `table.count_rows()` (LanceDB),
  который пуст → `total_chunks=0`.
- `require_ready_project()` (`src/mcp/tools/base.py:428`) блокировал
  `search_code`, `get_symbol_info`, 6 LSP-тулов и 5 write-действий.
- Автоиндексация видела 0, вызывала `index_project()`, а тот под тем же флагом
  возвращал 0 → состояние не могло самоисправиться.

## Что сделано

- `IndexStatusReporter` принимает `chunk_store`, берёт максимум из LanceDB и
  SQLite, отдаёт `store: sqlite|lancedb|none`, не делает stale-scan по LanceDB,
  когда читает SQLite.
- `index_project()` при `dense_off` запускает текстовую полную индексацию
  (`_index_text_only_project`: чанки → SQLite/FTS5 + AST-граф, без эмбеддингов)
  вместо `return 0`.
- Коммиты: `97a32f1` (фикс), `3515795` (гейт §19.1 + date-dependent тесты),
  `30adbee` (33 папки экспериментов / 265 файлов).
- Числа: `get_status()` → `total_chunks=7314, unique_files=487, status=active,
  store=sqlite` (было `0 / empty`). Полный прогон: 2 174 passed, 6 skipped.

## Предложение в AGENT_DIARY.md

```markdown
## [2026-11-07] P0 — индекс есть, статус пуст: Phase 3 читали не тот store

**Симптом:** `search_code`/`get_symbol_info`/LSP/write — «Index is empty»,
health critical, автоиндексация каждый старт «completed (0 files)».
**Root Cause:** Phase 3 хранит чанки в SQLite, а `get_status()` считал
`LanceDB.count_rows()` (=0); `index_project()` под `dense_off` возвращал 0.
**Fix:** `97a32f1` — статус берёт максимум из двух store, под `dense_off`
работает текстовая полная индексация. **Guard:** `tests/test_status_sqlite_store.py`
(3 контроля + «без store гейт блокирует»).
**Число:** 7 314 чанков / 487 файлов при `total_chunks=0` до фикса.
```

## Предложение в KNOWN_ISSUES.md

```markdown
## 2026-11-07 — P0: статус индекса читал LanceDB при индексе в SQLite — 🟢 fixed
- Phase 3: 7 314 чанков в `.mscodebase/chunks.db`, `total_chunks=0` →
  все поисковые/LSP/write-тулы блокировались 13 дней.
- Fix `97a32f1`; тест `tests/test_status_sqlite_store.py`.
```

## Что осталось вне этой задачи

- `tools/factory/` + `tests/test_factory.py` — untracked, решение владельца.
- `scripts/check_write_bytes.py`, `scripts/recurrence.py` — guard P-19, untracked.
- 6 frozen-манифестов (E49, E52–E54, E56, E57) нарушают «≥2 ожидаемых провала»;
  внесены в закрытый allowlist `audit_protocol_guards.py`, задним числом не
  правятся (§17).

## НАБЛЮДЕНИЕ — третье срабатывание §19.9 (2026-11-07)

Полный reindex (`ca32c377`) снова запустил `AutoDocUpdater` и **дописал 242
строки** в трекнутый `KNOWN_ISSUES.md` (197 → 439 строк), из-за чего
`scripts/check_known_issues.py` начал падать и блокировать коммит. Это **третье**
событие того же класса (дневник: +267 и +241 строки, 2026-09-30).

- Изменение откатано: `git checkout -- KNOWN_ISSUES.md` (197 строк, гейт OK).
- Причина не устранена: автодок по-прежнему пишет в реестры.
- Предложение (нужно решение владельца): `AutoDocUpdater` не должен трогать
  `KNOWN_ISSUES.md` / `AGENT_DIARY.md` вообще — это реестры, а не README. Плюс
  пострефреш-проверка `git status` с предупреждением в лог.

**Число:** 3 события, ни одно не поймано гейтом — каждое ловилось глазами.

## НАБЛЮДЕНИЕ — Phase 3 отключил hot-reload (2026-11-07)

Символ `_read_head_sha`, добавленный в `scripts/verify_diary.py` коммитом
`8553802` ДО старта сервера, не находился ни `get_symbol_info`, ни
`search_code`: индекс описывал дерево до коммита.

- **Root cause:** `FreshnessChecker._read_indexed_state()` читал
  `table.to_lance()` — LanceDB, пустую в Phase 3. Пустое состояние → ранний
  `return 0` («индекс ещё не построен»), то есть hot-reload молчал всегда.
- **Fix `0a95f68`:** `SQLiteChunkStore.indexed_state()` + приоритет SQLite в
  чекере; изменённые/новые файлы подхватываются в пределах интервала 30 с
  после первого поиска.
- **Класс:** тот же, что P0 со статусом (один store мигрировали, читателя
  оставили на старом). Тест: `tests/test_freshness_sqlite.py`.

## АУДИТ ЦЕПОЧКИ + ЧИСТКА (2026-11-07, вечер)

**Мусор:** удалено 8.15 GB (12.79 → 4.64 GB): `isolated/`-копии в
`experiments/microtask_vs_single/runs` (8.3 GB, node_modules + session DB,
результаты 2 MB сохранены), 304 `__pycache__`, 2 `.pytest_cache`,
`.coverage`, `llama_server_stderr.log` (15 MB), `spike.db`,
`.git/next-index-9724.lock` (22.09).

**Найдено и исправлено (`08f4854`):**
- `structural_search` таймаутил 15 с: `rglob` по venv/models/experiments →
  обход с обрезкой; теперь 167 файлов / 2.7 с.
- `predict_change` таймаут 120 с: `_git` ждал DEFAULT_TIMEOUT=300 и держал
  index-lock → 20 с + `GIT_OPTIONAL_LOCKS=0` + stdin=DEVNULL.
- 6 LSP-тулов: бюджет 15 с меньше холодного старта basedpyright → 60 с.
- `stale_detector`: 7 с вне MCP, таймаут 60 с внутри → бюджет 90 с +
  логирование root/elapsed (гипотеза проверяется по логу, не угадывается).

**Найдено, не исправлено:** `graph_query(related)` и `intel_get_hotspots`
пустые, пока `CommitMemory` не обновлён (кеш 2 записи); `codebase git log`
по умолчанию отдаёт 10 коммитов из кеша.

**Самопойманный инцидент (P-19, 4-й):** правка `lsp_tools.py` через
PowerShell `Get-Content -Raw | Set-Content -Encoding utf8` перекодировала
кириллицу в мохибейк; поймано тестами `test_lsp_tools.py` (2 падения),
откачено `git checkout`, правка повторена через `edit`, 10/10 зелёные.
Guard работает: тест заметил то, что глазами не видно.



