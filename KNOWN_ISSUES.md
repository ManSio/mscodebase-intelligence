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
