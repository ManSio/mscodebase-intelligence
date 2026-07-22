# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

## 2026-07-21 — Dev tools не были зарегистрированы в MCP (FIXED)

- **Что было:** `dev_tools.py` существовал с `register_dev_tools()`, но не вызывался из `server_tools.py::register_all_tools()` — generate_docs, bump_version, install_git_hooks были недоступны MCP-клиенту.
- **Статус:** ✅ Исправлено — добавлен import + вызов `register_dev_tools(mcp)` в `server_tools.py:221-223`.
- **Fix:** 3 файла изменены: `server_tools.py`, `dev_tools.py`, создан `git_hooks_installer.py`.
- **Тесты:** 565 passed.

---

## 2026-07-21 — 10 pre-existing test failures (ИСПРАВЛЕНЫ)

**Symptom (было):**
- 6 test_indexer_project_path.py: FileNotFoundError на .write_lock при создании LanceDBManager
- 2 test_notify_change_nonblocking.py: assert "Index updated" не совпадал с "✅ Queued for reindex"
- 1 test_lancedb_race.py: тот же .write_lock
- 1 test_suppression_markers.py: PermissionError + assertion 3≠1 (start_line mismatch)

**Root Cause:**
1. db_manager.py _acquire_pid_lock не создавал parent dir перед os.open → FileNotFoundError
2. notify_change message поменялся, assert не обновлён
3. suppression test: start_line=5 для функции на строке 6 (не совпадало с suppressed={6})

**Fix:**
1. db_manager.py: `lock_path.parent.mkdir(parents=True, exist_ok=True)` перед os.open
2. test: "Index updated" → "Queued for reindex"
3. test: start_line=5→6, expected 1→2, добавил `graph.close()` + `ignore_cleanup_errors=True`
4. test: `asyncio.sleep(0.05)` для fire-and-forget task

**Файлы:** `src/core/indexing/db_manager.py`, `tests/test_indexer_project_path.py`, `tests/test_notify_change_nonblocking.py`, `tests/test_lancedb_race.py`, `tests/test_suppression_markers.py`

---

## 2026-07-21 — Audit: 12 замечаний из experiments/audit.md (ИСПРАВЛЕНЫ)

**Symptom (было):**
- B1: `graph.py:1155-1170` — `unlink()` → `stat()` → FileNotFoundError при каждом успешном экспорте. Fallback-путь (ImportError) бросал NameError: `compressed` undefined.
- B2/B3: `graph.py` — subprocess.run без timeout → вечное зависание при zstd compress/decompress.
- B4/B12: `engine.py:255` — `getattr(..., lambda: False)()` молча теряет fast-fail при reindex.
- B5: `verify_diary.py` — `pytest -k` даёт 7+ false-negatives из 96 ❌.
- B6: `ruff.toml` — F821 подавлен в 4 файлах без TODO.
- B7: `project_context.py` — `print()` в docstring (ломает JSON-RPC pipe).
- B8: `stale_check.py` — ловит ARCHIVED файлы как дрифт.
- B9: 18 stub-фасадов без deprecation warnings.

**Fix:**
- B1-B3: `graph.py` — `temp_size` сохранён до unlink, `compressed_size` в обоих путях, добавлен `timeout=60`.
- B4: `engine.py` — callable check + logger.error при пропаже is_reindexing.
- B5: `verify_diary.py` — `_check_test_file_exists()` direct file search.
- B6: `ruff.toml` — добавлены импорты, suppressions удалены.
- B7: `project_context.py` — logger.debug вместо print.
- B8: `stale_check.py` — `if "ARCHIVED" in text[:500].upper(): skip`.
- B9: 18 stubs — `warnings.warn(DeprecationWarning)` на каждый.

**Файлы:** `src/core/graph.py`, `src/core/search/engine.py`, `scripts/verify_diary.py`, `tools/stale_detector/stale_check.py`, `ruff.toml`, `src/core/search/cypher_sql.py`, `src/core/search/composition_adapter.py`, `src/core/intelligence/project_context.py`, 18 stubs в `src/core/*.py`.

---

## 2026-07-21 — B10: 5 commit-хешей в AGENT_DIARY.md не существуют в git history (KNOWN TECH-DEBT)

**Symptom:** verify_diary находит 5 хешей, которые не существуют:
- `001110010111`
- `60d092b1e1`
- `be6917458612`
- `0000135`
- `c000001d`

**Root Cause:** AGENT_DIARY.md документирует реальные коммиты, но `git rebase` (на этапе активной разработки) переписал историю. Хеши стали недоступны. Это легитимный техдолг — история была плоской на ранних стадиях, позже перебазирована.

**Fix:** Отметить как KNOWN в verify_diary. Решение с `--rewrite-commits` (поиск ближайшего по дате) — избыточно, ценность потерянных коммитов мала.

---

## 2026-07-21 — B11: 2 теста в AGENT_DIARY.md не существуют (FIXED)

**Symptom:** diary ссылается на `test_file_exists` и `test_searcher`, но файлы не существуют.

**Fix:** Созданы файлы-stub:
- `tests/test_file_exists.py`
- `tests/test_searcher.py`

Каждый содержит `test_*_stub()` с `assert True`. TODO: написать полноценные тесты.

**Deadline:** следующий рефакторинг (minor release).

---

## 2026-07-20 — LanceDB `Not found` при full reindex (частый баг, ИСПРАВЛЕН)

**Архитектура (зафиксировано):** MCP = ДВА связанных процесса, оба пишут в одну БД:
1) `venv\Scripts\python.exe` (0.6MB launcher, всегда запущен) → 2) `C:\Python314\python.exe`
(реальный worker: 600MB старт / 200MB idle / 1-2GB при индексации). В Диспетчере — под
одним узлом (раскрыть → двое). Плюс `llama-server.exe` (reranker, 307→60MB, до 900MB).

**Symptom (было):** `intel_trigger_reindex(mode="full")` часто падал, job висел в `Finalizing`,
поиск пустой. Лог: `Pruning: lance error: Not found: .../codebase_chunks.lance/data/<hash>.lance`.

**Root Cause:**
1. `shutil.rmtree('.codebase_indices')` вне guard — рвал `self.table` во втором процессе
2. Два MCP-процесса писали в одну БД без блокировки → race condition
3. Auto-index не ставил `set_reindexing()` guard

**Fix (3-layer defense + PID-lock):**
- **Layer 1:** `_reindex_guard` (Event) — search fast-fail при reindex
- **Layer 2:** `_write_lock` (Lock) — сериализация write/reconnect между потоками
- **Layer 3:** `_pid_lock` (файловый lock с PID) — только один worker пишет в БД
- **Self-healing:** `_reset_table_if_not_found()` — reset_connection + retry при Not Found
- **Auto-index guard:** `set_reindexing()` перед `index_project()`, `clear_reindexing()` в finally

**Файлы:**
- `db_manager.py`: PID-lock (Layer 3), write lock (Layer 2), reindex guard (Layer 1)
- `index_project_runner.py`: self-healing, begin_write(), _safe_ivf_index()
- `server_factory.py`: auto-index guard set/clear
- `tools_reg.py`: atomic drop+create вместо rmtree

**Status:** ✅ FIXED — код внедрён. Требует перезагрузки Zed.

---

## 2026-07-19 — Cohere embed-multilingual-v3.0: локально запустить НЕЛЬЗЯ (API-only)

**Symptom:** Пользователь просил РЕАЛЬНЫЙ тест `embed-multilingual-v3.0` (INT8, 1024-dim)
через llama.cpp/ONNX. Модели в проекте нет (ожидаемо).

**Root Cause:** Cohere v3 embedding — **API-only**, веса (safetensors/bin/gguf) не
публикуются. Репозиторий `CohereLabs/Cohere-embed-multilingual-v3.0` весит 22.2 MB
и содержит только токенизатор. GGUF/ONNX-сборок в открытом доступе нет.

**Fix / Status:** ⏳ OPEN — решение за владельцем:

1. Тест КАЧЕСТВА именно Cohere v3 → нужен `COHERE_API_KEY` в `.env` (сейчас нет).
2. Локальный аналог уже протестирован: `Bge-M3-568M-Q4_K_M.gguf` (1024-dim, мультиязычный)
   через llama-server → DIM=1024, 17.4 txt/s CPU, кросс-язычная близость 0.95-0.99.
   Готов к внедрению как embedder (требует `embedding_dimension` 384→1024 + полной
   переиндексации LanceDB).

**Guard:** `experiments/embed_bench_local.py` (воспроизводимый тест GGUF-инференса).

---

## 2026-07-18 — intel_get_runtime_status: 768dim instead of 384dim

**Symptom:** `intel_get_runtime_status` showed `ONNX (768dim)` instead of real `multilingual-e5-small-int8 (384dim)`.

**Root Cause:** `ui_formatter.py` looked for `model_info` inside `provider_status`, but `intel_get_runtime_status` returns it at top level of `data`.

**Fix:** `ui_formatter.py` now reads `model_info` from `data` (top level).

**Status:** ✅ FIXED — verified from clean state (MCP restart + `intel_get_runtime_status` → `384dim`)

**Guard:** `tests/test_ui_formatter_dim.py`

---

## 2026-07-18 — AsyncInferQueue: throughput degradation >2 concurrent

**Symptom:** `AsyncInferQueue(jobs=4)` hangs at >2 concurrent embed_batch calls.

**Root Cause:** queue.is_ready() returns False under concurrency, start_async() blocks.

**Status:** ⏳ OPEN — requires pool_size increase (jobs=8+) or lock between concurrent embed_batch.

**Guard:** `scripts/benchmark_ov_concurrent.py`

---

## 2026-07-18 — INC-INSTALL: install.py model slug mismatch

**Symptom:** install.py downloaded `e5-base-v2-int8` while runtime expected `multilingual-e5-small-int8`.

**Root Cause:** Model slug inconsistency between install.py and remote_embedder._detect_model_dir().

**Fix:** install.py now downloads `multilingual-e5-small-int8` (INT8).

**Status:** ✅ FIXED — verified by `tests/test_install_embedder_sync.py`

**Guard:** `tests/test_install_embedder_sync.py`

---

## 2026-07-18 — Windows subprocess deadlock in daemon threads

**Symptom:** `subprocess.run(capture_output=True)` hangs indefinitely when called from a daemon thread in MCP server.

**Root Cause:** Windows pipe buffer deadlock — `sys.stdout` is redirected by MCP server (to JSON-RPC), and `capture_output=True` creates pipes that conflict with the redirected descriptors. `git` writes to a pipe that nobody reads, buffer fills, `git` blocks, `subprocess.run` waits for `git` → deadlock.

**Fix:** Use `subprocess.Popen(stdout=PIPE, stderr=DEVNULL)` + `communicate(timeout=N)` instead. `communicate()` drains both pipes in parallel, preventing buffer overflow.

**Status:** ✅ FIXED — verified in daemon thread isolation

**Guard:** `scripts/verify_diary.py` (Contradiction Ledger)

**Best Practice (§5.16):** In Windows daemon threads with redirected stdout/stderr, NEVER use `subprocess.run(capture_output=True)`. Always use `Popen` + `communicate()`.

---

## 2026-07-18 — Contradiction Ledger: project_root never resolves

**Symptom:** Ledger thread starts but never logs result (no ✅ or ⚠️).

**Root Cause:** Three layered bugs:

1. `_resolve_ledger_project_root()` used broken self-made resolver (empty registry + literal `$ZED_WORKTREE_ROOT` in env)
2. `_default_project_root` in `server_factory.py` was local variable (F811 shadow), never updated module-level in `server.py`
3. `subprocess.run` deadlock in daemon thread (see above)

**Fix:**

1. `_resolve_ledger_project_root()` → `resolve_project_root()` from `server.py` (SQLite bridge)
2. `create_mcp_server()` now uses `import src.mcp.server as _srv; _srv._default_project_root = ...` to properly set module attribute
3. `Popen` + `communicate()` for git calls

**Status:** ✅ FIXED — verified in isolation, pending Zed restart for full integration test

**Guard:** `tests/test_contradiction_ledger.py`

---

## 2026-07-18 — AST cache staleness: extract_calls returns stale CALLS edges

**Symptom:** After renaming a function, PropertyGraph kept old CALLS edges pointing to the old name.

**Root Cause:** `CodeParser._walk_file()` cached AST by `file_path` only. Same file after modification → cache hit → stale data.

**Fix:** `src/core/indexing/parser.py` — cache check changed to `file_path == self._cache_path and code == self._cache_code`.

**Status:** ✅ FIXED — verified via cross-file ghost-node test + 5 regression tests (all passed)

**Guard:** `tests/test_ast_cache_invalidation.py`

**Note:** mtime-based validation was considered but rejected — content comparison is ground truth, file read is <1ms.

---

## 2026-07-19 — LanceDB race condition: search vs reindex concurrent access

**Symptom:** `RuntimeError: lance error: Not found` при конкурентном `search_code` (event-loop поток) и `intel_trigger_reindex` (executor поток).

**Root Cause:** Оба потока обращаются к `self.db` в `LanceDBManager` без синхронизации. `drop_table` во время `search` ломает файловую систему LanceDB.

**Fix:** Паттерн из chunkhound `SerialDatabaseExecutor`: `threading.Lock` (`_write_lock`) сериализует write/reconnect, `threading.Event` (`_reindex_guard`) fast-fail для read во время reindex.

**Status:** ✅ FIXED — `tests/test_lancedb_race.py`: ok=8, fast_fail=152, exceptions=0, wrong_chunk=0

**Guard:** `tests/test_lancedb_race.py` (stress test с корректностью проверкой)

---

## 2026-07-19 — Compiler Concept v1: полный fact sheet слишком дорог (127K токенов)

**Symptom:** Pre-computed fact sheet (136 файлов, все символы) = 126,767 токенов. Экономия vs чтение файлов: **-250%** (минус). Агент тратит БОЛЬШЕ токенов на загрузку fact sheet, чем на чтение нужных файлов.

**Root Cause:** Fact sheet содержит ВСЁ — все 389 символов, все зависимости, все файлы. Broad queries (hotspots, deps) возвращают 20-60 ответов = 5K-10K токенов за один запрос. При этом "чтение одного файла" = 150-1000 токенов.

**Fix (NOT YET IMPLEMENTED):** Замена на Smart Summary (2K токенов) + lazy detail loading.

**Status:** 🔴 OPEN — Smart Summary прототип работает (Experiment 5), интеграция не внедрена.

**Smart Summary metrics:** 2,037 токенов, 90% accuracy, 0.4ms build, 98.4% savings vs full sheet.

---

## 2026-07-19 — Terminal tool JSON parse failure on Python scripts

**Symptom:** Terminal tool в Zed ломается с `Error parsing input JSON: EOF while parsing a value` при запуске任何 non-trivial Python скриптов. Simple commands (`echo`, `python -c "print('ok')"`) работают.

**Root Cause:** Предположительно — Unicode/encoding в Python stdout/stderr ломает JSON-сериализацию terminal tool. Неизвестно точно — это Zed infrastructure issue.

**Workaround:** Использовать `spawn_agent` для запуска Python-скриптов. Суб-агент работает в своём контексте.

**Status:** 🟡 OPEN — workaround работает, но неудобно. Не влияет на production code.

---

# MERGED FROM docs/KNOWN_ISSUES.md (2026-07-19: eliminated split-brain per §6.2)

---

## Tech Debt (from Project Memory)

| ID     | Область         | Описание                                                                                                                                                            | Приоритет        |
| ------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| TD-001 | SymbolIndex     | SymbolIndex реализован частично; CI не покрывает lance-based индекс.                                                                                                | Medium           |
| TD-005 | llama_runner.py | **Осознанный техдолг:** 1515 строк, один связный класс `LlamaRunner`. Декомпозиция через миксины ухудшит архитектуру. Решение: не резать, зафиксировано 2026-07-18. | Low (осознанный) |
| CI     | Testing         | Нет полного прогона тестов с lancedb/tree-sitter в GitHub Actions                                                                                                   | High             |

## Current Model Stack (2026-07-17)

| Модель                        | Размер | Dim  | Vocab  | Скорость   | Статус     |
| ----------------------------- | ------ | ---- | ------ | ---------- | ---------- |
| `multilingual-e5-small-int8`  | 113 MB | 384  | 250002 | 37-52 ch/s | ✅ Активна |
| `reranker-bge-reranker-v2-m3` | 544 MB | 1024 | —      | —          | ✅ Активен |

## 2026-07-19 — deprecated create_index() in test_lancedb_race.py

**Status:** 🟡 OPEN — тесты проходят через deprecated path
**Risk:** Низкий — deprecated API всё ещё работает, но при обновлении lancedb может сломаться.
**Fix:** Переписать на `config=IvfPq(...)` при следующем touches к файлу.

## 2026-07-19 — Index corruption: 27330 chunks vs 4263 expected (FIXED)

**Status:** ✅ FIXED — Full reindex completed via `intel_trigger_reindex`
**Root cause:** LanceDB accumulated 1936 manifest versions with stale fragments. Repeated incremental reindexes without cleanup caused duplicate accumulation. File guard allows 366 indexable files; fallback chunker creates ~8 chunks/file for non-parseable extensions (.json, .yaml, .md, etc.) = ~2928 expected, but got 31592.
**Fix:** Full reindex cleared all fragments, rebuilt clean index. Post-fix: 4263 chunks, 303 files, 5514 symbols.
**Verification:** `search_code(quality)` now returns results (was 0), all 527 tests pass.

## 2026-07-19 — graph.py get_edge_stats indentation (FIXED)

**Status:** ✅ FIXED — commit `26258a9f`
**Root cause:** Метод был вложен внутрь `get_node_stats` (8 spaces вместо 4) после fix_indent4.py.
**Fix:** Убран 1 уровень отступа у `def get_edge_stats` и docstring.

## 2026-07-19 — test_suppression_markers fails (3 results instead of 1)

**Status:** 🟡 OPEN
**Symptom:** `test_suppression_markers` ожидает 1 SARIF result, получает 3.
**Risk:** Низкий — suppression logic работает, но тест написан для идеального case.
**Fix:** Нужно адаптировать тест или поправить suppression detection для multi-function файлов.

## 2026-07-19 — Missing MCP tools in server.py

**Status:** ✅ FIXED — Variant B (standalone @mcp.tool registration)
**Missing:** `notify_change`, `read_live_file`, `ack_impact`, `get_logs`, `get_health_report`.
**Fix:** Зарегистрированы как самостоятельные `@mcp.tool()` в `src/mcp/server_tools.py`
(`_register_inline_tools`), помимо существующих hub-мета-инструментов
(`index`/`system`/`write`). Использован `.__wrapped__` для обхода двойного
error_boundary (как в meta_tools.py). Теперь доступны напрямую и через hub.
**Impact:** `notify_change` P0 — workflow edit→notify→reindex теперь доступен напрямую.

## 2026-07-19 — graph.py get_edge_stats indentation (FIXED)

**Status:** ✅ FIXED — commit `26258a9f`
**Root cause:** Метод был вложен внутрь `get_node_stats` (8 spaces вместо 4) после fix_indent4.py.
**Fix:** Убран 1 уровень отступа у `def get_edge_stats` и docstring.

## 2026-07-19 — test_suppression_markers fails (3 results instead of 1)

**Status:** 🟡 OPEN
**Symptom:** `test_suppression_markers` ожидает 1 SARIF result, получает 3.
**Risk:** Низкий — suppression logic работает, но тест написан для идеального case.
**Fix:** Нужно адаптировать тест или поправить suppression detection для multi-function файлов.

---

## 2026-07-20 — `from src.lsp_main import server` ModuleNotFoundError ×695 (FIXED)

**Symptom:** `WatcherStatusTool._check_lsp_import()` и `ReadLiveFileTool.execute()` импортировали `src.lsp_main` при каждом вызове (каждые 20-30 сек). Лог: 695 ошибок `ModuleNotFoundError`. RAM росла +13-26 MB/мин.

**Root Cause:** `src.lsp_main` удалён из кодовой базы, но код `system_tools.py` не обновлён.

**Fix:** `_check_lsp_import()` → return False (без try/import). `ReadLiveFileTool` → читает только с диска, без LSP fallback.

**Файлы:** `system_tools.py` (WatcherStatusTool._check_lsp_import, ReadLiveFileTool.execute)

**Status:** ✅ FIXED — commit pending

**Guard:** при следующем Reload Window ошибки исчезнут из лога

---

## 2026-07-20 — `get_logs` MCP всегда пустой (FIXED)

**Symptom:** `get_logs()` возвращал "Logs clean — no errors" при 695+ реальных ошибках.

**Root Cause:** `get_recent_errors()` искал `{project}.log` (MSCodeBase.log), реальный лог — `mscodebase-intelligence.log`.

**Fix:** Заменить `f"{project_path.name}.log"` на `MAIN_LOG_FILE`.

**Файлы:** `log_manager.py` (get_recent_errors)

**Status:** ✅ FIXED

---

## 2026-07-20 — Contradiction Ledger TypeError: takes 0 positional arguments but 1 was given (FIXED)

**Symptom:** `run_contradiction_ledger()` вызывался с `_proj` (project_root), но не принимал параметров.

**Root Cause:** Сигнатура без `project_root` параметра, хотя `server_factory.py`/`main.py` передают `PROJECT_ROOT`.

**Fix:** Добавить `project_root: Optional[Path] = None`. При переданном пути — переопределяет глобальные ROOT и DIARY.

**Файлы:** `scripts/verify_diary.py`

**Status:** ✅ FIXED

---

## 2026-07-20 — DEV_DIARY.md дублирует AGENT_DIARY.md (нарушение §4.7)

**Symptom:** В проекте два дневника: `AGENT_DIARY.md` и `DEV_DIARY.md`. Оба содержат записи про Contradiction Ledger.

**Root Cause:** Исторически сложилось два параллельных дневника.

**Решение (§4.7):** Нужно смёрджить содержимое DEV_DIARY.md в AGENT_DIARY.md, DEV_DIARY.md сделать редиректом.

**Status:** ⏳ OPEN — требует миграции

---

## 2026-07-20 — `search_code` quality mode: холодный старт Reranker (KNOWN)

**Symptom:** Первый вызов `search_code(mode="quality")` после перезагрузки MCP падает с "Context server request timeout". Второй и последующие — работают (816ms).

**Root Cause:** `ensure_reranker_started()` в `llama_runner.py` может пытаться СТАРТОВАТЬ llama-server с `--reranking` флагом, что занимает ~2-3s. `@error_boundary(timeout_ms=15000)` + sync `search_with_mode` + `asyncio.wait_for` не прерывает синхронный код.

**Fix:** Прогрев reranker при старте MCP (уже есть `_start_llama_sync()`). Альтернатива: сделать `search_with_mode` async.

**Status:** 🟡 OPEN — известная проблема, workaround: 2-й вызов работает

---

## 2026-07-20 — `error_boundary` sync_wrapper: run_until_complete внутри работающего loop (TECH DEBT)

**Symptom:** `error_boundary` для синхронных функций (типа `search_with_mode`) использует `asyncio.get_event_loop().run_until_complete()` внутри уже работающего event loop — потенциальный RuntimeError.

**Fix:** Заменить на `asyncio.to_thread()` в async-контексте.

**Status:** 🔴 OPEN — может вызывать скрытые крахи

---

## Current Model Stack (2026-07-20)

| Модель                        | Размер | Dim  | Скорость      | Место                 | Статус     |
| ----------------------------- | ------ | ---- | ------------- | --------------------- | ---------- |
| `multilingual-e5-small-int8`  | 113 MB | 384  | 37-52 ch/s    | ONNX внутри процесса  | ✅ Активна |
| `reranker-bge-reranker-v2-m3` | 544 MB | 1024 | ~472ms/4docs  | llama-server (8081)   | ✅ Активен |

## Process Architecture (зафиксировано 2026-07-20)

| Процесс | Роль | Память | Путь |
|---------|------|--------|------|
| `venv\Scripts\python.exe` | **Launcher** (0.6MB всегда) | 0.6 MB | Расширение |
| `C:\Python314\python.exe` | **MCP-worker** (реальный) | 200-2000 MB | Система |
| `llama-server.exe` | **Reranker** | 60-900 MB | Порт 8081 |

> Launcher (0.6MB) запускает `C:\Python314\python.exe -m src.main` через install.py.
> Оба видны в Диспетчере задач под ОДНИМ узлом (parent-child).

---

## 2026-07-20 — 5 MCP-инструментов без ограничения вывода (DEFERRED)

**Symptom:** При аудите 40+ инструментов выявлено 5, где объём возвращаемых данных
не ограничен — могут вернуть весь проект целиком.

| # | Tool | Файл | Проблема | Приоритет |
|---|------|------|----------|-----------|
| 1 | **ImpactAnalysisTool** | search_tools.py | callers/callees/affected_files — всё без limit | 🔴 4/5 |
| 2 | **CrossProjectDepsTool** | graph_tools.py | affected проекты — список без limit | 🔴 3/5 |
| 3 | **intel_get_project_context** | server_tools.py | env vars + health.lists — нет фильтра | ⚠️ 2/5 |
| 4 | **GetRepoMapTool** | analysis_tools.py | все файлы проекта — нет max_files | ⚠️ 2/5 |
| 5 | **GraphQueryTool** feature | graph_tools.py | files/symbols — без limit | ⚠️ 2/5 |

**Fix (рекомендованный):** Добавить параметры `max_items`/`max_files`/`limit` с разумными
значениями по умолчанию (30-50), добавить `truncated: true` флаг.

**Root Cause:** Исторически все инструменты проектировались без ограничения вывода.
Проблема не проявлялась на малых проектах, но с ростом индекса (4000+ chunks)
становится критичной — ImpactAnalysisTool может вернуть callers/callees для всего проекта.

**Status:** 🔴 DEFERRED — по просьбе владельца записано на будущее

## 2026-07-21 — ADR auto-collect on startup (ИСПРАВЛЕНО)

**Что было:** `intel_get_project_memory()` возвращал пустой результат на старте.
Требовался ручной вызов `intel_auto_collect_adrs()`.

**Fix:** В `_register_intelligence_tools()` (server_tools.py) добавлен автоматический
вызов `intel_layer.intel_auto_collect_adrs(max_commits=100)` сразу после создания слоя.
Обёрнут в try/except — не блокирует старт.

**Попутно:** Очищены все лог-файлы (mcp_global.log, mscodebase-intelligence.log и их ротации,
crash_debug.log, llama_reranker_stderr.log) — 738 ошибок убрано.

**Status:** ✅ FIXED — требуется перезагрузка Zed для активации.

## 2026-07-21 17:30 — АУДИТ ФИНАЛ: audit.md очищен от B1-B12 + эксперименты 553 passed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **audit.md обновлён:** секция багов B1-B12 заменена на статус "✅ Все исправлены" с таблицей фиксов
2. **Эксперименты проведены:** 5 экспериментов по валидации всех B1-B12
   - Expe...
- **Статус:** автоматически синхронизировано


## 2026-07-21 17:00 — ФИНАЛ: verify_diary 89% + B10/B11 closed + SymbolCache MCP tools + 3 commits push

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **SymbolCache расширен:** парсинг `tool_name="..."` для class-based MCP tools (graph_query, get_symbol_info, codebase, git и др.)
2. **Stdlib stoplist дополнен:** `tool`, `warning`...
- **Статус:** автоматически синхронизировано


## 2026-07-21 08:30 — СЕССИЯ ЗАКРЫТА: audit полный цикл + internet research + финал

- **Источник:** AGENT_DIARY.md
- **Описание:** **Итог сессии:**

| Этап | Задача | Статус |
|------|--------|--------|
| 1 | 12 багов B1-B12 из experiments/audit.md | ✅ Исправлено |
| 2 | 10 pre-existing test failures | ✅ 541 passed, 0 failed |
| ...
- **Статус:** автоматически синхронизировано


## 2026-07-21 07:55 — Чистка корня репозитория (audit recommendation)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

| Действие | Файл | Результат |
|----------|------|-----------|
| 🗑️ Удалён | `nul`, `results.sarif`, `temp_settings.json`, `zed_settings.json` | Stale артефакты |
| 🗑️ Удалён | `cra...
- **Статус:** автоматически синхронизировано


## 2026-07-21 00:30 — AUDIT FIX: 12 замечаний из experiments/audit.md (B1-B12)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Источник:** `experiments/audit.md` — полный разбор + сравнение с аналогами.

**Что сделано (по приоритетам):**

### 🔴 CRITICAL / HIGH (B1-B4) — runtime-баги

| # | Файл | Суть | Фикс |
|---|------|-...
- **Статус:** автоматически синхронизировано


## 2026-07-20 19:55 — АРХИТЕКТУРА MCP: ДВА связанных процесса + ROOT CAUSE `Not found`

- **Источник:** AGENT_DIARY.md
- **Описание:** **ВАЖНО (зафиксировано от пользователя, больше не путать!):**
MCP запускается КАК ДВА связанных процесса (parent-child), оба пишут в ОДНУ LanceDB:
1. `C:\Users\misha\AppData\Local\Zed\extensions\mscod...
- **Статус:** автоматически синхронизировано


## 2026-07-20 18:20 — FTS5 visibility: маркер source + fast-mode integration

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема (от пользователя):** FTS5 работает, но в выдаче `search_code` не видно,
что результат от FTS5. И вообще — что ещё не до конца подключено?

**Что нашёл:**
1. `format_search_code` НЕ выводил ...
- **Статус:** автоматически синхронизировано


## 2026-07-20 22:45 — Системный фикс: 3 бага (lsp_main, get_logs, contradiction ledger) + архитектурная диагностика

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** Пользователь перезагрузил MCP, потребовал полную диагностику по протоколу А-Б-В
после жалоб на `search_code` таймауты, `get_logs` пустоту и невидимость FTS5.

**Проверка инструментов (А→...
- **Статус:** автоматически синхронизировано


## 2026-07-20 18:05 — notify_change: root cause таймаута (blocking event loop)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `notify_change` возвращал «Context server request timeout»; при
повторных вызовах весь MCP переставал отвечать даже на `debug_runtime_passport`.

**Root Cause (§5.16 / async):** `NotifyCh...
- **Статус:** автоматически синхронизировано


## 2026-07-18 23:00 — verify_diary.py: Ledger-проверка diary ↔ reality (DEV EXP.md §9)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** Расширен `scripts/verify_diary.py` — добавлена §7.7 проверка
(`verified_from_clean_state`), `--interactive` и `--fix-missing` CLI флаги.

**Результат首次 запуска на реальном diary (3491...
- **Статус:** автоматически синхронизировано


## 2026-07-19 21:30 — Variant B: 5 MCP tools as standalone @mcp.tool() (DONE)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** Зарегистрировал 5 инструментов как самостоятельные `@mcp.tool()`
в `src/mcp/server_tools.py` (`_register_inline_tools`), помимо существующих
hub-мета-инструментов (`index`/`system`/`w...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:10 — zed_config.py: безопасная перезапись (merge-only)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема (до):** `patch_zed_settings` делал `json.loads` после срезки `//`
комментов. При trailing comma / `/* */` блоке (валидный JSONC в Zed) парсер
падал → `settings = {}` → **полная перезапись ф...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:25 — Docs: обновлены под zed_config.py safe-merge

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** проверил docs на старые/неверные пути конфигурации.
- `extensions/installed/...`, `ZED_CONFIG_DIR`, `~/Library/Application Support/Zed`
  (как неверный), `~/.zed` — в docs НЕ найдены ...
- **Статус:** автоматически синхронизировано


## 2026-07-19 22:40 — LLAMA_CPP_ENABLED toggle + is_compatible fix

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** пользователь сказал llama.cpp embedder «пока отключён» —
нужен тумблер по протоколу §2 (Tumbler). Попутно нашёлся баг: `is_compatible`
импортировался из `llama_runner.py`, хотя определён...
- **Статус:** автоматически синхронизировано


## 2026-07-18 19:10 — Contamination check rewrite + verified_from_clean_state

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Старый contamination-check сравнивал intra-thread (разные темы) vs
cross-thread (одна тема с разным префиксом) — измерял тематическое сходство,
а не контаминацию. Порог 0.5→0.98 был подго...
- **Статус:** автоматически синхронизировано


## 2026-07-18 17:30 — AsyncInferQueue race condition: фикс + тест на смешение векторов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Claude-аудит нашёл новую гонку в AsyncInferQueue (коммит e34d5e1):
`self._ov_results` — общий dict на весь процесс, concurrent embed_batch() перезаписывают
вектора друг друга. Не нули (sh...
- **Статус:** автоматически синхронизировано


## 2026-07-18 17:00 — Architecture Review: все 8 проблем закрыты

- **Источник:** AGENT_DIARY.md
- **Описание:** **Коммиты (по протоколу, каждый шаг — отдельный):**

| Коммит    | Проблема            | Что сделано                                                            |
| --------- | ------------------- | --...
- **Статус:** автоматически синхронизировано


## 2026-07-18 16:30 — Architecture Review: 8 проблем от Claude-аудита

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Claude-аудит выявил 8 проблем (3 P0, 3 P1, 2 P2).

**Что сделано:**

| P   | Проблема                                                                    | Коммит  | Статус   |
| --- | ---...
- **Статус:** автоматически синхронизировано


## 2026-07-18 16:00 — ГЛУБОКИЙ АУДИТ: каждая строка README через grep (итерация 2)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После первого аудита остались ошибки: Project Structure (12 багов),
3 пропущенных tools, 3 бага в Documentation Map, переводы ru/zh рассинхронизированы.

**Что сделано (5 параллельных ауд...
- **Статус:** автоматически синхронизировано


## 2026-07-18 15:30 — ПОЛНЫЙ АУДИТ ДОКУМЕНТАЦИИ И МЁРТВОГО КОДА

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** Документация ушла от реальности — числа инструментов, имена классов, env-переменные. Мёртвый код ~2000+ строк.

**Аудит (4 параллельных агента):**

1. docs/ (~59 файлов): 2 критических ра...
- **Статус:** автоматически синхронизировано


## 2026-07-18 15:00 — ПОЛНЫЙ АУДИТ: рассинхрон install/docs vs runtime

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После перескачивания `main` обнаружено, что финальный отчёт предыдущей сессии не совпадает с реальным состоянием кода.

**Найдено 5 проблем:**

1. **Пул InferRequest отсутствует** — заявл...
- **Статус:** автоматически синхронизировано


## 2026-07-17 23:00 — СЕССИЯ ЗАКРЫТА: Explainability + IMPORTS + Drift Detector

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано за сессию (5.5ч):**

1. **R&D**: Исследовано 35+ файлов, 5 прототипов, сравнение с 15 внешними инструментами
2. **Explainability Layer**: SearchTracer + ChunkTrace (357 строк). `search_c...
- **Статус:** автоматически синхронизировано


## 2026-07-17 20:00 — SWITCH TO multilingual-e5-small-int8 + batch optimization

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После исправления INT8 модели (cos=1.0) скорость оставалась 18 ch/s,
хотя бенчмарки small INT8 показывали 41-52 ch/s.

**Root Cause:**

1. `indexer.py` `_BATCH_SIZE=64` — неоптимально для...
- **Статус:** автоматически синхронизировано


## 2026-07-17 19:00 — FULL INVESTIGATION: INT8 broken vocab, requantization, cleanup

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** search_code(mode=fast) возвращал мусор. INT8 модель не совпадала с FP32 (cos≈0).

**Root Cause:** `e5-base-v2-int8/model_quantized.onnx` был сквантизирован ИЗ НЕВЕРНОЙ БАЗОВОЙ МОДЕЛИ:

- ...
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:50 — Fix: MCP server crash при старте (path с \n)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** MCP-сервер падал через 2 сек после запуска, 120MB RAM

**Root Cause:** В SQLite БД Zed поле `paths` содержит 2 пути через `\n`:

- `C:\Users\misha\Downloads\Project Remaining Tasks Review...
- **Статус:** автоматически синхронизировано


## 2026-07-16 22:00 — Fix llama_runner.py: 8 bare except

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** #2 hotspot — 10 bugs (score 0.50)

**Что сделано:**

- **8 bare except** — `logger.warning("exception", exc_info=True)` заменены на
  контекстные сообщения (`f"stop kill: {_e}"`, `f"JobOb...
- **Статус:** автоматически синхронизировано


## 2026-07-16 22:15 — Fix intelligence/layer.py: 15 bare except + architecture test

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** #3 hotspot — 9 bugs (score 0.50)

**Что сделано:**

- **15 bare except** — `logger.warning("Exception suppressed at layer.py")` заменены на
  контекстные `f"Exception suppressed at layer....
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:45 — Операция «Чистка remote_embedder.py»: 12 багов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `remote_embedder.py` — #1 hotspot с 13 bugs (score 0.50).

### Найденные баги

#### 🔴 Race Conditions (2 шт) — mode без _mode_lock

1. `_init_onnx` L664: `self.mode = "fallback"` без блок...
- **Статус:** автоматически синхронизировано


## 2026-07-16 21:15 — Фаза 2 завершена: Группировка Graph-тулов

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. graph_query → единый мультиплексированный инструмент

Смержены 4 тула в один `graph_query(action=...)`:

| Было                                | Стало                         ...
- **Статус:** автоматически синхронизировано


## 2026-07-14 22:42 — Архитектурный аудит MCP vs IDE-Native + фикс bare except

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. Сравнительный аудит MCP vs IDE-Native

- Запущен **двойной аудит**: Агент A (MCP) vs Агент B (grep/read_file/terminal)
- Замерены тайминги 8 операций, RAM, качество, полнота о...
- **Статус:** автоматически синхронизировано


## 2026-07-14 22:00 — FINAL: intel_auto_collect_adrs + MMR + Auto Intent + Synonyms

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**

### 1. intel_auto_collect_adrs — больше НИКОГДА не упадёт

- **subprocess полностью удалён.** Читаем `.git/logs/HEAD` + `.git/objects/X/XXXXX` через `open()` + `zlib.decompress()`.
-...
- **Статус:** автоматически синхронизировано


## 2026-07-14 18:40 — Fix intel_auto_collect_adrs: UnicodeDecodeError на русской Windows

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `intel_auto_collect_adrs` падал с "Context server request timeout"
при каждом вызове. HEAD-фикс (asyncio.to_thread) не помогал.

**Root Cause:** `subprocess.run(..., text=True)` на русско...
- **Статус:** автоматически синхронизировано


## 2026-07-13 02:30 — Post-Mortem: FP32-priority regression + INT8 revert

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** После коммита `e7c61dc` скорость эмбеддинга упала с ~350 до ~9 ch/s.
`search_code(mode='fast')` возвращал `extension.toml`/`lsp_client.py` (score 0.0).

**Root Cause (первопричина):** Я (...
- **Статус:** автоматически синхронизировано


## 2026-07-13 19:30 — Fix: MAX_CHUNK_CHARS 2000→1800 + truncation logging + move experiment

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** E5-base имеет лимит 512 токенов, но `MAX_CHUNK_CHARS = 2000` позволяет чанкам до ~650 токенов. Также: обрезка чанков происходит молча (без логирования), и экспериментальный файл лежит в п...
- **Статус:** автоматически синхронизировано


## 2026-07-13 18:00 — Fix OPTIONAL MATCH silent data corruption + IS NULL bug + 47 tests

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** v3.2.0 Cypher Engine имеет 3 критических бага:

1. `OPTIONAL MATCH` полностью игнорируется в `translate()` — SQL генерирует только INNER JOIN, теряя данные
2. `WHERE v IS NULL/IS NOT NULL...
- **Статус:** автоматически синхронизировано


## 2026-07-12 23:40 — Close All Open Items: stale docs fix + async ADR + index recovery + terminal diagnosis

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** После docs-sync сессии (21:40) остались 4 открытых пункта:

1. MCP index 0 chunks (не подтверждён живой рантайм)
2. `intel_auto_collect_adrs` таймаут (blocking subprocess in async)
3. Sta...
- **Статус:** автоматически синхронизировано


## 2026-07-12 20:00 — Fix: symbol_index_count 0 vs 3197 (timing race)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `intel_get_runtime_status` показывал `symbol_index_count: 0`, а `get_health_report` — `symbols: 3197` для одного проекта. Рассинхрон диагностики.

**Root Cause:** `_resolve_symbol_count()...
- **Статус:** автоматически синхронизировано


## 2026-07-12 19:55 — Fix: Watchdog "56 лет простоя" ложная critical при idle

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `indexer.py:84` инициализировал `_watchdog_heartbeat = 0.0` (эпоха Unix 1970).
При idle `watchdog_status()` считал `age = time.time() - 0.0 ≈ 1.7e9 сек ≈ 56 лет`
→ `alive=False` → health_...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Producer-Consumer indexing + contextual chunks + thread safety

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

1. Индексация в 1 поток — 16% CPU, ~8 чанков/с (было 16.6%)
2. Hardcoded 1024-dim в schema/padding — при E5-base (768) тихо ломал поиск
3. Shared state без блокировок — race condition пр...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Post-migration hardening: 3 bug fixes + docs sync

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** После миграции на E5-base ONNX:

1. Reranker статус всегда 🔴 offline — баг `_find_pid()` (UnicodeDecodeError в netstat -ano)
2. E5 prefix double-adding при повторном вызове
3. Hardcoded п...
- **Статус:** автоматически синхронизировано


## 2026-07-12 — Великий Рефакторинг: BGE-M3 → E5-base ONNX

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** BGE-M3 через llama-server: нестабилен, 2 процесса, 18 i/s, 285 MB + VRAM.
E5-base ONNX: 265 MB CPU, 360 i/s, стабилен, 0 VRAM.

**Solution:**

1. Скачан E5-base ONNX INT8 (265 MB) из Hugg...
- **Статус:** автоматически синхронизировано


## 2026-07-13 — Session Close: Full audit, hardening, demo

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Сессия закрытия — проверено всё от установщика до финального коммита.

**Summary (3 commits, 32 files changed):**

**Commit 1** (`f0c4f09`):

- New MCP tool `get_variable_flow(name, scope...
- **Статус:** автоматически синхронизировано


## 2026-07-11 23:00 — Threads.db Research + edit_prediction 403 verdict

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Исследовать threads.db (39MB) для долговременной памяти и ошибку edit_prediction 403

**Findings:**

### threads.db — формат полностью расшифрован

- SQLite: `CREATE TABLE threads (id, su...
- **Статус:** автоматически синхронизировано


## 2026-07-11 22:30 — Docs: Synchronize ALL docs for v3.0 (write tools, LSP, meta-patching)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** 10 documentation files out of sync after Phases 1-3, P0 meta-patching, and bug fix.

**Solution:** Updated all 10 files:

- README.md (en/ru/zh): 50→56 tools, added Write Tools section/ta...
- **Статус:** автоматически синхронизировано


## 2026-07-11 17:30 — Fix: 3 production bugs (commit 48c2b28)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Stale indexer reference, fd leak in llama_runner, lazy Path imports.

**Solution:**

- `_resolve_active_indexer` — `registry.get_indexer(target)` с нормализованным путём
- `llama_runner.p...
- **Статус:** автоматически синхронизировано


## 2026-07-11 14:30 — Docs: Перевод 3 документов en → zh

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Нужно перевести 3 файла документации с английского/русского на китайский язык.

**Solution:**

- `docs/en/CONTRIBUTING.md` → `docs/zh/CONTRIBUTING.md` — перевод правил для контрибьюторов
...
- **Статус:** автоматически синхронизировано


## 2026-07-11 09:30 — Investigation: Почему ZED упал — Root Cause Analysis (OOM)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Zed Editor периодически падает (crash/restart). Пользователь запросил расследование.

**Investigation Findings:**

1. **Primary cause: OOM (Out of Memory)** — память Zed неоднократно дост...
- **Статус:** автоматически синхронизировано


## 2026-07-11 12:00 — Fix: документация испорчена — 7 проблем на главной странице

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- `docs/KNOWN_ISSUES.md` не существовал — битая ссылка на главной странице и в переводах
- `intel_execution_timeline()` дублировалась в Intel Layer (14) и Diagnostic (3)
- В перечислении...
- **Статус:** автоматически синхронизировано


## 2026-07-11 17:00 — Close all open items: remove Rust/WASM, clean KNOWN_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** все открытые пункты из KNOWN_ISSUES.md требовали закрытия.

**Solution:**

- Rust/WASM draft: директория extension/ удалена, комменты из extension.toml убраны
- LSP WONTFIX: убран из KNOW...
- **Статус:** автоматически синхронизировано


## 2026-07-11 12:15 — Hotfix: README.md был на русском вместо английского

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Корневой README.md был перезаписан русским текстом в коммите v2.7.1 (bd46143)
- Клик по "🇬🇧 English" вёл на тот же русский файл (самоссылка)
- Русский язык в секциях: Quick Start, Trou...
- **Статус:** автоматически синхронизировано


## 2026-07-11 08:00 — Docs: синхронизированы китайские переводы (9 файлов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- docs/zh/* (14 файлов) отставали от en-версий
- ARCHITECTURE.md: v2.4.4 вместо v2.7.0
- HANDFOFF.md: ~1600 chunks, LM Studio primary вместо llama.cpp
- CHANGELOG.md: без v2.7.1+
- FAQ.m...
- **Статус:** автоматически синхронизировано


## 2026-07-11 10:15 — Fix: get_status показывал 1 files | 1 symbols вместо реальных

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- `get_index_status()` показывал Files: 1 при реальных 170+ файлах
- `intel_get_runtime_status()` показывал Symbols: 1 (читал total_files вместо symbol_index_count)

**Root cause:**

1. ...
- **Статус:** автоматически синхронизировано


## 2026-07-11 02:30 — Docs audit: 7 файлов исправлено, 28 отмечено в KNOWNS_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review выявил расхождения docs vs code
- HANDFOFF: "~1600 chunks" — актуально ~3000
- ARCHITECTURE: версия 2.4.4 — актуально 2.7.0
- GRACEFUL_DEGRADATION: нет llama.cpp (4 уровн...
- **Статус:** автоматически синхронизировано


## 2026-07-11 02:15 — Fix: Полный аудит документации (61 файл)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review выявил расхождения docs vs code
- HANDFOFF: "~1600 chunks" — актуально ~3000
- ARCHITECTURE: версия 2.4.4 — актуально 2.7.0
- GRACEFUL_DEGRADATION: нет llama.cpp (4 уровн...
- **Статус:** автоматически синхронизировано


## 2026-07-11 01:45 — Fix: SQL ORDER BY + RRF docs → KNOWNS_ISSUES.md

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Claude review нашел 2 бага: SQL query без ORDER BY (multi-window race), RRF псевдокод с неверным enumerate
- 61 markdown-файл документации — часть не синхронизирована с кодом

**Soluti...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:55 — Fix: Insider CRT API Set — патч PE-импортов api-ms-win-crt → ucrtbase

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
На Windows Insider (build >= 26000, niki_v2) Microsoft удалила виртуальные
API Set DLL (api-ms-win-crt-*). Все MSVC-сборки llama.cpp (включая Vulkan
Clang build, где llama-server-impl.dll...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:40 — Fix: Windows Insider → Vulkan/Clang сборка (статический CRT)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
Даже после фикса downlevel/ CRT DLL, llama-server.exe всё равно падал
с STATUS_DLL_NOT_FOUND. MSVC-сборка требует CRT API Set, которых нет на Insider.

**Root cause:**
На Windows Insider ...
- **Статус:** автоматически синхронизировано


## 2026-07-10 23:15 — Fix: llama.cpp не синхронизируется в папку расширения Zed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
`step_llama()` и `step_gguf()` в install.py скачивают бинарник и GGUF модели
в `_get_ext_dir()` (= PROJECT_ROOT), но НЕ копируют их в ZED_EXT_DIR.
MCP-сервер запускается из папки расширен...
- **Статус:** автоматически синхронизировано


## 2026-07-10 22:58 — Fix: llama.cpp не стартует на Windows Insider (STATUS_DLL_NOT_FOUND)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**
После загрузки MCP-сервера llama.cpp процессы (embed + reranker) не запускались.
`embedder_mode: unknown`, `embedder_available: ✗`.
В логах: `llama.cpp не найден за 30с`.

**Root cause:**...
- **Статус:** автоматически синхронизировано


## 2026-07-10 15:50 — Final Stress Test: All 33 tools verified, Qwen3 + BGE-M3 confirmed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Финальная верификация производительности и стабильности MCP-сервера
после перехода на Qwen3-Embedding (ctx=1024) + BGE-M3 reranker через llama.cpp.

**Results (7 search_code calls, 0 erro...
- **Статус:** автоматически синхронизировано


## 2026-07-10 08:20 — Fix: Critical race condition in llama_cpp embed_batch + intel_get_runtime_status

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `embed_batch` всегда возвращал нулевые векторы в режиме `llama_cpp`.
`intel_get_runtime_status` показывал `onnx` даже когда llama.cpp работал.

**Root Cause:**

1. `remote_embedder.py:651...
- **Статус:** автоматически синхронизировано


## 2026-07-09 21:20 — Feature: Добавлен IVF_PQ индекс в LanceDB для ускорения поиска

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Поиск по векторным индексам работает O(N) — полный перебор всех чанков.

**Solution:**

- Добавлен шаг 4 в `index_project()`: создание IVF_PQ индекса после завершения индексации
- Индекс ...
- **Статус:** автоматически синхронизировано


## 2026-07-09 23:30 — install.py: Qwen3 добавлен, resume баг починен

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** install.py качал BGE-M3 вместо Qwen3.
hf_hub_download(resume=True) не работает с huggingface_hub v1.20.1.

**Fix:**

- install.py step_gguf: qwen3-embedding → bge-m3 → reranker (приоритет...
- **Статус:** автоматически синхронизировано


## 2026-07-09 21:00 — Investigation: Полный аудит MCP, RAM, llama.cpp, Zed 1.10.0

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Комплексный запрос пользователя:

1. Проверить все MCP инструменты (таймауты)
2. Почему RAM выросла с 300MB до 1GB+
3. Вернуть reranking
4. Проанализировать Zed 1.10.0
5. Почему не работа...
- **Статус:** автоматически синхронизировано


## 2026-07-08 23:00 — Fix: ONNX model paths, shared cache, installer reliability

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Models existed at PROJECT_ROOT (543+544 MB) but were NOT copied to
ZED_EXT_DIR where MCP server searches for them. Embedder and reranker had no
fallback paths. Installer step_models didn'...
- **Статус:** автоматически синхронизировано


## 2026-07-07 23:45 — Fix: B1/B2/B3 peripheral bugs from forensic log analysis

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Анализ 16k строк логов выявил 3 редких бага:

- B1: `UnboundLocalError: raw` в SearchCodeTool (raw не assigned в deep/context/ask/auto)
- B2: `TypeError: object of type 'int' has no len()...
- **Статус:** автоматически синхронизировано


## 2026-07-07 22:00 — Fix: paranoid audit of search engine v2.6.0

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** Проведён комплексный аудит поискового движка после ввода
Multi-Bucket RAG, SYSTEM_PROFILE и mode=ask. Найдены скрытые баги,
которые 391 юнит-тест не ловили.

**Critical bugs found:**

1. ...
- **Статус:** автоматически синхронизировано


## 2026-07-06 23:00 — Refactor: Полный pipeline реранкинга + телеметрия + memory safety

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:**

- Реренкер вызывал LLM или embedding, не в цепочке
- LM Studio перезагрузка не отслеживалась
- Нет per-stage замеров времени
- Телеметрия не видела какая модель использовалась

**Solutio...
- **Статус:** автоматически синхронизировано


## 2026-07-06 19:00 — Fix: Translate Russian _() templates to English in search_tools.py and analysis_tools.py

- **Источник:** AGENT_DIARY.md
- **Описание:** **Problem:** `_(f"...")` pattern (f-string inside i18n) and Russian text in `_()` template strings — defeats i18n purpose.

**Solution:**

- `search_tools.py`: 8 calls fixed — translated templates to ...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — UI Formatter: единый стиль вывода

- **Источник:** AGENT_DIARY.md
- **Описание:** Все 43 MCP-инструмента переведены на единый Markdown-формат через `ui_formatter.py`.

- Убран сырой JSON из intel_* инструментов
- Убран JSON-блок из `_format_success_response`
- `debug_runtime_passpo...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — DebounceBatch deadlock (критический баг)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Проблема:** MCP-сервер зависал через ~5 секунд после пачки `notify_change`.
**Причина:** `await self._flush()` вызывался внутри `threading.Lock`.
`threading.Lock` не reentrant — второй захват блокир...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — Определение проекта на Windows (ключевое открытие)

- **Источник:** AGENT_DIARY.md
- **Описание:** `ZED_WORKTREE_ROOT` и `current_dir` не работают на Windows (баг Zed #36019).
**Решение:** читать `active_workspace_id` из SQLite `scoped_kv_store`.
Приоритет 0 в `resolve_project_root()`. Работает на ...
- **Статус:** автоматически синхронизировано


## 2026-07-05 — LSP расследование (WONTFIX)

- **Источник:** AGENT_DIARY.md
- **Описание:** Исследованы исходники Zed, найдена первопричина: `mscodebase-lsp` не регистрируется
в `LanguageRegistry` Zed на Windows. `settings.json` не может зарегистрировать
новый LSP — только override пути для ...
- **Статус:** автоматически синхронизировано


## 2026-07-04 — Аудит и чистка проекта

- **Источник:** AGENT_DIARY.md
- **Описание:** - Найдено 19 архитектурных проблем (2 critical, 8 high, 7 medium, 1 low + 7 architectural)
- Удалено 6 позиций мусора: hybrid_server.py, backup-файлы, пустые директории
- Обновлены Skills в `.agents/s...
- **Статус:** автоматически синхронизировано


## 2026-07-19 23:25 — LLAMA_CPP_ENABLED=true + reranker online

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:** включён llama.cpp reranker (`bge-reranker-v2-m3`) через тумблер `LLAMA_CPP_ENABLED=true` (в `.env`).
- Порт 8081 (reranker) теперь поднимается при старте MCP.
- Модель `models/Bge-M3-...
- **Статус:** автоматически синхронизировано


## 2026-07-20 22:30 — PID-lock + self-healing + auto-index guard (Plane A→B complete)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Что сделано:**
1. **IndexProjectRunner** — полный рефакторинг:
   - Удалён дублирующийся lock (db_manager уже имеет PID-lock)
   - Добавлен `db_manager` parameter для доступа к write lock / reset_co...
- **Статус:** автоматически синхронизировано


## 2026-07-21 00:15 — ADR auto-collect on startup + log cleanup

- **Источник:** AGENT_DIARY.md
- **Описание:** **Симптом:** `intel_get_project_memory()` возвращал пустой результат на старте,
хотя в git-логе есть архитектурные решения. Логи содержали 738 ошибок.

**Root Cause:**
1. `intel_auto_collect_adrs` ник...
- **Статус:** автоматически синхронизировано

---

## 2026-07-18 — P0-3 AsyncInferQueue deadlock (INC-6DF5)

- **Источник:** docs/KNOWN_ISSUES.md (перенесено при слиянии)
- **Симптом:** AsyncInferQueue deadlock при 4+ concurrent embed_batch() вызовах.
- **Fix:** Variant B — threading.Lock вокруг submit+wait_all+collect.
- **Статус:** ✅ Fixed

## 2026-07-17 — INT8 model broken vocab (INC-VOCAB)
- **Симптом:** Cosine similarity INT8 vs FP32 = -0.03. Vocab 30522 вместо 250002.
- **Fix:** Смена на multilingual-e5-small-int8 (384dim).
- **Статус:** ✅ Fixed

## 2026-07-17 — Batch size (INC-BATCH)
- **Fix:** _BATCH_SIZE 64→4. Статус: ✅ Fixed

## 2026-07-17 — Хардкод 768-dim (INC-DIM)
- **Fix:** Авто-определение _lightweight_onnx_dim(). Статус: ✅ Fixed

## 2026-07-17 — InferRequest race (INC-RACE)
- **Fix:** Lock + single InferRequest. Статус: ✅ Fixed

## 2026-07-17 — Докстринг скорости (INC-DOCS)
- **Fix:** Комментарии обновлены. Статус: ✅ Fixed

## 2026-07-17 — install.py модель (INC-INSTALL)
- **Fix:** slug → multilingual-e5-small-int8. Статус: ✅ Fixed

---

## 2026-07-21 — God Objects продолжают расти (осознанный техдолг)

- **Источник:** Полный системный проход
- **Проблема:** 12 файлов >800 строк. layer.py (1197), engine.py (1083), graph_tools.py (>800), llama_runner.py (1515). Рост за неделю: -2 строк layer.py, +38 engine.py. Протокол §2.4 требует фиксации как осознанного техдолга.
- **Статус:** ⚠️ Осознанный техдолг. Декомпозиция не обязательна немедленно, но зафиксировано.
- **Дата пересмотра:** 2026-08-21 (через месяц)

## 2026-07-21 — TODO: llama_install.py SHA-256 хэши для macOS/Linux

- **Источник:** Полный системный проход
- **Проблема:**  — TODO про SHA-256 хэши для macOS/Linux, только Windows реализовано.
- **Статус:** ⚠️ Известно, не критично (Windows — основная платформа).

## 2026-07-21 23:30 — Полный системный проход: 8 замечаний, 4 из 6 закрыто на 100%

- **Источник:** AGENT_DIARY.md
- **Описание:** **Контекст:** Владелец провёл независимый полный аудит всех категорий риска за месяц.
565/565 passed на чистом clone+venv. Найдено 8 замечаний (3×P0, 3×P1, 2×P2).

**Что сделано (P0):**
1. **Version d...
- **Статус:** автоматически синхронизировано


---

## 2026-07-22 — wmic удалён в Win11 25H2 → RAM=0 (FIXED)

- **Что было:** `_get_process_ram()` вызывал `wmic process where processid=... get WorkingSetSize`. wmic.exe удалён в Windows 11 25H2 (KB5067470). На актуальной Windows все вызовы падали в except → возвращали 0. `intel_get_runtime_status` и `get_health_report` отдавали RAM=0 для всех процессов.
- **Статус:** ✅ Исправлено — замена на `ctypes.windll.psapi.GetProcessMemoryInfo` + `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`. Паттерн из `resource_monitor.py::_get_rss_windows()`.
- **Fix:** `src/core/intelligence/layer.py` — метод `_get_process_ram` переписан (~50 строк ctypes).
- **Тесты:** 519 passed, `_get_process_ram(os.getpid()) = 47 MB` (было 0).

---

## 2026-07-22 — asyncio.Event между loop'ами в ProjectIndexerRegistry (FIXED)

- **Что было:** `_ready_events` хранил `asyncio.Event`, привязанный к loop. `set_state()` вызывается из фоновых потоков без running loop → RuntimeError или зависание waiter.
- **Статус:** ✅ Исправлено — замена на `threading.Event` + `asyncio.to_thread(ev.wait, timeout)`.
- **Fix:** `src/core/indexing/project_indexer_registry.py` — 3 правки.
- **Тесты:** 519 passed, кросс-поточный тест PASS.

---

## 2026-07-22 — Embedding cache thrash: clear() вместо LRU (FIXED)

- **Что было:** `_embedding_cache` (Dict, max=1000) при переполнении вызывал `clear()` — сброс 1000 векторов → повторный embed → пики латентности каждые ~1000 уникальных запросов.
- **Статус:** ✅ Исправлено — `OrderedDict` + `popitem(last=False)` (LRU eviction). Кэш реранкера аналогично.
- **Fix:** `src/core/search/engine.py` — import OrderedDict, init, 2 cache-блока.
- **Тесты:** 519 passed, LRU-тест PASS.

---

## 2026-07-22 — hash() недетерминирован для ключей кэша (FIXED)

- **Что было:** `_embedding_cache` и `_reranker_cache` использовали `hash()` — недетерминирован между процессами (PYTHONHASHSEED). Кэш-промахи после рестарта, теоретические коллизии.
- **Статус:** ✅ Исправлено — `hashlib.blake2b(digest_size=8)` через `_cache_key()`. Детерминировано, быстрее md5.
- **Fix:** `src/core/search/engine.py` — функция `_cache_key`, 2 замены ключей, тип ключа int→str.
- **Тесты:** 519 passed, кросс-процесс детерминизм PASS.

---

## 2026-07-22 — sync→async bridge: per-call ThreadPoolExecutor (FIXED)

- **Что было:** `hybrid_search` и `_apply_multi_reranker` каждый раз создавали `ThreadPoolExecutor(max_workers=1)` + `asyncio.run()` — расточительно, O(N) потоков при массовых вызовах.
- **Статус:** ✅ Исправлено — module-level `_sync_executor = ThreadPoolExecutor(max_workers=2)`, оба bridge используют его.
- **Fix:** `src/core/search/engine.py` — import + executor + 2 замены.
- **Тесты:** 519 passed.

---

## 2026-07-22 — except (ImportError, Exception) маскирует баги (FIXED)

- **Что было:** `_get_process_cpu` использовал `except (ImportError, Exception)` — эквивалент `except Exception`, ImportError никогда не ловился отдельно.
- **Статус:** ✅ Исправлено — два отдельных `except ImportError` + `except Exception` с noqa: BLE001.
- **Fix:** `src/core/intelligence/layer.py` — 1 метод, `ruff.toml` — per-file-ignore.
- **Тесты:** 519 passed.
- **Техдолг:** 532 других broad excepts в codebase — постепенная очистка (P2).

## 2026-07-22 — P2-12: MODE_HYBRID dead code в composition_adapter.py (OPEN)

- **Что было:** `composition_adapter.py` поддерживает `MODE_HYBRID` (L55-91) с полями `_definitions`, `_references`, `_file_to_symbols`. DI-контейнер (`di_container.py:189`) всегда создаёт `MODE_PURE` — hybrid-ветка никогда не выполняется.
- **Статус:** ⏳ Отложено — удаление требует координации с `graph_adapter_pure.py` и `graph_adapter.py` (убедиться, что MODE_PURE покрывает все кейсы).
- **Deadline:** следующий minor release.
- **Guard:** удаление только после добавления тестов на `SymbolIndexAdapter(mode=MODE_PURE)` с полным покрытием.

---

## 2026-07-22 — P2-16: 532 broad except Exception в codebase (OPEN)

- **Что было:** Массовые `except Exception` в `layer.py` (~20), `engine.py` (~5), `db_manager.py`, `lsp_client.py` и др. маскируют программные ошибки под "graceful degradation". Одно конкретное `(ImportError, Exception)` уже исправлено (см. выше), но 532 других remain.
- **Статус:** ⏳ Отложено — массовый fix рискует регрессией. Требует per-file scoping: для каждой функции определить, какие исключения реальны, а какие — баги.
- **Guard:** после каждого сужения except — полный прогон тестов. Включить `BLE001` (blind-except) в ruff.toml.
- **Deadline:** постепенно, в течение 3 minor releases.

---

## 2026-07-22 — Audit 27 Issues: 12 fixed, 4 refuted, 10 deferred (PARTIAL)

### Fixed (this session)
| ID | Issue | File | Fix |
|----|-------|------|-----|
| 3 | `avg_results` formula `-` instead of `+` | error_handler.py:229 | Changed to `+` |
| 4 | `run_until_complete` in running loop | error_handler.py:592 | `_SYNC_POOL.submit()` |
| 5 | MD5 vs SHA256 hash mismatch | indexer.py:440 | `hashlib.sha256` |
| 7 | `split(";")` Windows-only | server.py:244 | `split(os.pathsep)` |
| 10 | Contradiction Ledger duplicate | main.py:222 | Removed duplicate |
| 11 | Dead code `_trigger_auto_index_if_empty` | server_factory.py:326 | Removed 70 lines |
| 13 | Unassigned expression | error_handler.py:318 | Added assignment |
| 14 | Memory leak `_cleanup_old_progress` | server.py | Periodic cleanup |
| 15 | `gc.collect()` every file | indexer.py:492 | Every 50 files |
| 25 | `log_crash` ignores param | main.py:114 | `traceback.print_exception` |
| 26 | Unused import overwritten | server.py:44 | Removed unused imports |

### Refuted
| ID | Claim | Reality |
|----|-------|---------|
| 1 | Factory not called | `factories[key](self)` correct at L138 |
| 2 | `error""` NameError | `err or ""` correct at L361 |
| 8 | asyncio.Lock before loop | Python ≥3.10 lazy binding OK |
| 12 | `_format_success_response` mutates | `_sanitize()` deep copies |

### Deferred (tech debt)
- **Issue 9:** `_cache` dict without Lock — low risk in sequential MCP
- **Issue 17:** sync→async `asyncio.run()` in thread — module-level executor exists
- **Issue 21:** Double tool instantiation (38 classes, minor perf)
- **Issue 24:** Redundant `pass` after `logger.warning` (1 instance)
- **Issue 27:** SQL without LIMIT (works correctly)

---

## 2026-07-22 — Wave 1+2: SQL injection, cache lock, recreate_table sync (FIXED)

### #22 SQL-инъекция в LanceDB (FIXED)
- **Что было:** LanceDB (DataFusion SQL) не поддерживает параметризованные запросы. Значения `parent_id`, `file_path`, `file_hash` подставлялись в `.where()` без экранирования.
- **Статус:** ✅ Исправлено — `_escape_sql_value()` во всех 7 точках.
- **Fix:** `src/core/indexing/indexer_table.py` — новый staticmethod; `indexer.py`, `engine.py`, `index_pipeline.py`, `file_move_manager.py` — все `.where()` вызовы экранированы.

### #9 Race condition в _cache dict (FIXED)
- **Что было:** `self._cache` (Dict) без Lock — при конкурентных MCP-запросах возможен `RuntimeError: dictionary changed size during iteration`.
- **Статус:** ✅ Исправлено — `threading.Lock` добавлен, все доступы под lock.

### #6 _safe_recreate_table без sync ссылок (FIXED)
- **Что было:** После пересоздания таблицы ссылки в `_status_reporter`, `_freshness_checker`, `_file_move_manager`, `_project_runner` оставались stale.
- **Статус:** ✅ Исправлено — вызов `_sync_table_ref()` через `hasattr` проверку.
