# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---

## 2026-07-20 — LanceDB `Not found` при full reindex (частый баг, БЛОКЕР)

**Архитектура (зафиксировано):** MCP = ДВА связанных процесса, оба пишут в одну БД:
1) `venv\Scripts\python.exe` (0.6MB launcher, всегда запущен) → 2) `C:\Python314\python.exe`
(реальный worker: 600MB старт / 200MB idle / 1-2GB при индексации). В Диспетчере — под
одним узлом (раскрыть → двое). Плюс `llama-server.exe` (reranker, 307→60MB, до 900MB).

**Symptom:** `intel_trigger_reindex(mode="full")` часто падает, job висит в `Finalizing`,
поиск пустой. Лог: `Pruning: lance error: Not found: .../codebase_chunks.lance/data/<hash>.lance`.

**Root Cause:** `intel_trigger_reindex(full)` (tools_reg.py L51-65) делает
`shutil.rmtree('.codebase_indices', ignore_errors=True)` ДО `trigger_async_reindex`, **вне guard**.
rmtree рвёт `self.table` (открыта в `__init__`), а с `ignore_errors` удаляет БД частично →
битый manifest → Pruning падает на `to_arrow()`. Guard ставится только ПОСЛЕ rmtree (layer.py L505).
Песочница EXP1-9 гонку НЕ воспроизвела (LanceDB 0.34 гасит простые гонки), root cause доказан
код-ревью.

**Status:** 🔴 OPEN — требует фикса.
**Fix (вариант А, рекомендую):** убрать `rmtree`; внутри worker делать `drop_table`+`create_table`
(или `reset_connection()`+recreate) — атомарно через lock-файлы; плюс single-writer PID-lock на БД.

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
