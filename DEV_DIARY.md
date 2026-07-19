# ⚠️ ARCHIVED — см. AGENT_DIARY.md (единственный источник правды)

> **DEV_DIARY.md ЗАМЕНЁН на AGENT_DIARY.md** (2026-07-19, §6.2 compliance).
> Все записи с 2026-07-17 по 2026-07-19 перенесены в AGENT_DIARY.md.
> Этот файл оставлен только для обратной совместимости.
> НЕ ДОБАВЛЯЙТЕ НОВЫЕ ЗАПИСИ СЮДА — пишите в AGENT_DIARY.md.

---
# DEV DIARY — MSCodeBase Intelligence

> Дневник инцидентов, экспериментов и архитектурных решений.
> Синхронизировано с `AGENT_DIARY.md` и `EXPERIMENTS_LOG.md`.

---

## 2026-07-18 — AsyncInferQueue: throughput benchmark (честные цифры)

**Команда:** `python scripts/benchmark_ov_concurrent.py`
**Модель:** multilingual-e5-small-int8 (INT8, 384dim)
**Queue:** AsyncInferQueue(jobs=4)

**Результат:**
| Threads | Chunks | Time (s) | ch/s | Errors |
|---------|--------|----------|------|--------|
| 1       | 10     | 0.32     | 31   | 0      |
| 2       | 20     | 0.30     | 66   | 0-1    |
| 4+      | 40+    | зависает | —    | —      |

**Вывод:** throughput ×2 (не ×4) — queue(jobs=4) не масштабируется при >2 concurrent embed_batch.
Причина: при конкурентных вызовах queue.is_ready() возвращает False, start_async() блокируется.

**Ограничение для продакшна:** indexer (batch=4) + concurrent search (batch=1) = 5 concurrent чанков → queue(4) забивается.
Требуется либо увеличение pool_size (jobs=8+), либо лок между concurrent embed_batch (вернуть сериализацию между вызовами).

**Сравнение:**
- Старая версия (single InferRequest + lock): 52 ch/s (batch=4, 1 thread)
- Новая версия (AsyncInferQueue jobs=4): 66 ch/s (batch=10, 2 concurrent threads)
- Прирост: ~27% при 2 concurrent, но деградация при >2

**Status:** ⚠️ Частичное улучшение, требует дальнейшего тюнинга (jobs=8 или mutex).

## 2026-07-18 — AsyncInferQueue: тихая гонка (тихая подмена векторов)

**Симптом:** Claude-аудит обнаружил что `self._ov_results` — общий dict на процесс.
Concurrent embed_batch() (индексатор + поиск) перезаписывали вектора друг друга.
Не нули, не исключения — **синтаксически корректные, но чужие вектора**.

**Root Cause:** Callback писал в `self._ov_results[userdata]`, userdata=0..N-1.
Два concurrent вызова с одинаковыми индексами → перезапись.

**Fix (вариант без лока):** userdata = (index, local_results_dict).
Каждый вызов создаёт свой dict → callback изолирован → лок не нужен.
Сохранён полный параллелизм внутри одного вызова (jobs=4).

**Тест:** 4 теста (concurrent, cosine, state leak) — все PASSED.
**Коммит:** a97f0ff

---

## 2026-07-18 — Architecture Review: 8 проблем (Claude-аудит)

**Симптом:** Claude-аудит выявил 8 проблем в коде — от P0 (крашит конструктор) до P2 (рассинхрон версий).

**Что починено (6 из 8):**
- **P0 count_edges**: `PropertyGraph` не имел `count_edges()`, а `indexer.py:123` вызывал его. → Добавил метод.
- **P0 path traversal**: `autonomous_fix.apply_fix()` принимал любой `file_path` без проверки выхода за `project_root`. → `_safe_path()` + `is_relative_to()`.
- **P1 shim import**: `graph_tools.py` импортировал `CypherExecutor` через flat shim. → Прямой импорт из `src.core.search.cypher_engine`.
- **P2 version**: `pyproject.toml` 3.2.3 vs CHANGELOG 3.3.1. → Синхронизировал.
- **P2 CI test**: `test_install_embedder_sync.py` — 3 теста, гарантируют что install.py и remote_embedder.py согласны.
- **P2 bump_version.py**: Скрипт для атомарного обновления версии в pyproject.toml + 3 CHANGELOG.

**Не починено (требует архитектурного решения — см. план ниже):**
- P0 single lock: `remote_embedder.py` — один `_ov_infer_request` + `threading.Lock`. Потолок throughput.
- P1 God Objects: `layer.py` (1572 строк), `llama_runner.py` (1515 строк).

**Коммиты:** 5f50da7, 62a3d40
**Тесты:** `test_integration.py` 3 errors → 0. `test_install_embedder_sync.py` 3/3 pass.

---

## 2026-07-18 — Глубокий аудит документации (итерация 2)

**Симптом:** После первого аудита остались 20+ ошибок в README: Project Structure (12 багов),
3 пропущенных инструмента, 3 бага в Documentation Map, переводы ru/zh рассинхронизированы.

**Root Cause:** Первый аудит проверял "есть ли функция" через grep.
Итерация 2 проверяла КАЖДОЕ утверждение через чтение кода + сравнение с документацией.

**Что сделано:**
- Project Structure: полная переделка (убраны несуществующие файлы, исправлены пути)
- MCP Tools: добавлены 3 пропущенных (get_repo_map, intel_auto_collect_adrs, intel_reset_index)
- Documentation Map: 3 бага языков + добавлен CONTRIBUTING.md
- Переводы: 21 замена в ru/README.md + 28 в zh/README.md

**Коммит:** 02a79ef (+127/−117)
**Guard:** При изменении числа tools/сервисов/тестов — обновлять README + ru + zh синхронно.

---

## 2026-07-18 — Полный аудит документации и мёртвого кода

**Симптом:** Документация врала (59 tools → реальность 38), 2603 строки мёртвого кода,
env-переменные не совпадали с settings.py, переводы zh/ru рассинхронизированы.

**Root Cause:** Быстрые итерации без обновления документации. При консолидации
write tools в `codebase(action=...)` hub — README не обновлён. При смене модели
17.07 — install.py не обновлён. Legacy tools оставлены "на всякий случай".

**Что сделано:**
- Удалено 5 мёртвых файлов src/ (~1020 строк)
- Удалено 9 legacy MCP tools (7 write + 2 system)
- Удалено 7 мёртвых scripts (~1328 строк)
- README.md: 59→38 tools, env vars, architecture diagram
- server_tools.py + intelligence/layer.py: комментарии исправлены
- .env.example: синхронизирован с settings.py (+MSCODEBASE_MCP_TOOLS, +LLAMA_BACKEND)
- zh/ARCHITECTURE.md: 58→38, ru/CHANGELOG.md: 36→38
- test_write_tools.py: мигрирован на WriteTool (33 теста, +bonus bugfix)

**Коммиты:** 123e7b0, 2e5870a, a25d3ab, ffd0e27
**Guard:** При изменении числа tools — обновлять README, AGENTS.md, переводы, server_tools.py комментарии.
**Осталось (техдолг):** 17 backward-compat шимов src/core/X.py, ~80 мёртвых методов в живых модулях.

---

## 2026-07-17 — Phase 2: PropertyGraph IMPORTS (Idea 1 blocker) устранён

**Контекст:** В PropertyGraph было 0 IMPORTS-рёбер при 3517 других рёбрах.
Парсер (CodeParser) извлекал calls и assignments, но полностью игнорировал
import statements. Это блокировало Architecture Drift Detector (Idea 1).

**Что сделано:**
1. `IMPORT_NODE_MAP` — per-language отображение Tree-sitter node-типов импортов
   (20 языков: Python, Rust, TS/TSX, Go, JS, Java, C#, Ruby, PHP, Kotlin, Swift,
   C/C++, Scala, Dart, Bash)
2. `extract_imports()` — обход AST, сбор импортов с target_module
3. `_pure_add_imports()` — создание Module-узлов + IMPORTS-рёбер в PropertyGraph
4. `add_imports()` — публичный API SymbolIndexAdapter
5. Интеграция в `index_pipeline.py` — вызов при каждом индексировании файла

**Валидация:**
- `parser.extract_imports(engine.py)` → 17 импортов
- `parser.extract_imports(parser.py)` → 25 импортов
- SymbolIndexAdapter.add_imports() → корректные IMPORTS edges (mock.py → httpx)

**Архитектурный урок:** CodeParser игнорировал import-узлы AST ровно по той же
причине, что и TARGET_NODES/CALL_NODES — их просто не было в списке. Добавление
IMPORT_NODE_MAP решило проблему за один проход.

**Следующий шаг:** `intel_trigger_reindex()` для наполнения PropertyGraph
IMPORTS-рёбрами в production. После реиндекса — Cypher-запросы для
Architecture Drift Detector.

**Коммит:** `142761d` — 4 файла, +202/-6 строк

**Статус:** ✅ Phase 2 завершена

---

## 2026-07-17 — Phase 1: Explainability Layer (Idea 3) внедрён

**Контекст:** search_code был «чёрным ящиком» — агент видел финальный список
результатов, но не знал, ПОЧЕМУ каждый чанк на конкретной позиции.

**Что сделано:**
1. Создан `src/core/search/trace.py` — SearchTracer (коллектор) + ChunkTrace (per-chunk dataclass)
2. В `engine.py` добавлены tracer-хуки на 7 этапов пайплайна:
   Query Expansion → BM25 → Dense → RRF → MMR → Bucket → Co-change → Reranker
3. В `search_tools.py` — `explain: bool = False` параметр для search_code
4. Формат вывода: to_dict() для JSON, to_markdown() для агента
5. Zero-cost disable: при explain=False tracer не создаётся (0 оверхед)

**API:** `search_code(query="...", explain=True)` → результаты + блок 🔍 Explain Trace

**Коммит:** `012da96` — 4 файла, +470/-10 строк

**Статус:** ✅ Phase 1 завершена. Следующий шаг: Phase 2 — PropertyGraph IMPORTS.

---

## 2026-07-17 — R&D: 4 идеи для новых MCP-инструментов

**Контекст:** Глубокое архитектурное исследование 4 направлений развития MSCodeBase.

**Исследовано:** 35+ файлов кода, 5 прототипов, comparison matrix с 15 внешними инструментами.

**Результаты:**
| Идея | Вердикт | Сложность |
|------|---------|-----------|
| 1. Architecture Drift Detector | Блокер: 0 IMPORTS-рёбер в PropertyGraph | Средняя |
| 2. Semantic Drift Tracker | Перспективно, но требует pre-commit hook | Высокая |
| 3. Explainability Layer ✅ | Внедрено (см. выше) | Низкая |
| 4. Claim Verifier | Готовность высокая, SymbolIndex + AST + CALLS есть | Средняя |

**Ключевое открытие:** PropertyGraph содержит 2743 узла и 3517 рёбер,
но 0 (ноль!) IMPORTS-рёбер — парсер не извлекает импорты в граф.
Это блокер для Architecture Drift Detector.

**Статус:** ✅ Исследование завершено, Phase 1 реализована

---

## 2026-07-17 — Переключение на multilingual-e5-small-int8 (384-dim)

---

## 2026-07-17 — Переключение на multilingual-e5-small-int8 (384-dim)

**Контекст:** После многомесячной борьбы с «плавающими» нулевыми векторами и мусорными результатами поиска обнаружена первопричина — INT8 модель `e5-base-v2-int8` была сквантизирована из BERT-uncased (vocab=30522), а не из `intfloat/e5-base-v2` (vocab=250002). Все семантические эмбеддинги были ортогональны эталону (cos≈0), но это маскировалось гибридным поиском BM25+Vector (RRF).

**Что сделано:**
1. Загружена и развёрнута `keisuke-miyako/multilingual-e5-small-onnx-int8` (113MB, INT8, 384-dim, vocab=250002, cos=0.99 с FP32)
2. Авто-определение `embedding_dim` в `remote_embedder.py` — модель сама задаёт размерность
3. `batch_size` оптимизирован: 64→4 (52 ch/s вместо 18)
4. Очищены все копии сломанной INT8 модели (расширение, проект, кэш)

**Результат:** Поиск работает корректно. 3765 чанков, 261 файл. Скорость ~37 ch/s (batch=4). Полный реиндекс 10k чанков — ~4.5 мин.

**Файлы:** `remote_embedder.py`, `indexer.py`, `index_project_runner.py`, `layer.py`, `install.py`

**Статус:** ✅ Закрыто

---

## 2026-07-17 — Token-aware search + execute_script Вариант B

**Контекст:** Две проблемы: (1) `search_symbols` склеивал `embed_batch` и `embed_batch_async` через substring match;
(2) `execute_script` имел 6 проблем: силентная обрезка вывода, отсутствие tempdir, PYTHONPATH, graceful shutdown,
structured output и streaming.

**Что сделано:**
1. **Token-aware scoring** — новый `_match_symbol_name()` с иерархией EXACT(100) > PREFIX(85) > ALL_TOKENS(70) > PARTIAL(50) > SUBSTRING(10)
2. **Truncation marker** — `[TRUNCATED at N chars; total M chars]` вместо силентной обрезки
3. **TempDirectory** — каждый вызов `execute_script` в `tempfile.TemporaryDirectory(prefix="mscx_exec_")`, авто-очистка
4. **PYTHONPATH** — `PYTHONPATH = Path.cwd()` → `import src.xxx` работает без `sys.path.insert`
5. **Graceful shutdown** — `terminate()` → `wait(1s)` → `kill()` — паттерн из CPython docs
6. **Structured output** — возвращает `{stdout, stderr, exit_code, duration_ms, truncated, timed_out}`
7. **@error_boundary** — таймаут поднят с 65s до 140s (120s скрипт + 1s grace + 5s kill + 14s буфер)
8. **DEFENSIVE CODING PROTOCOL** — 3 правила в глобальный AGENTS.md: encoding fix, pathlib, try/except

**Результат:**
- `search_symbols` — `embed_batch` ранжируется выше `embed_batch_async`
- `execute_script` — 54 теста проходят (9+31+7+7), стресс-тест shutdown (5 сценариев) пройден
- Диагностика — чисто

**Файлы:**
- `C:\Users\misha\AppData\Roaming\Zed\AGENTS.md` — новые п.9-11
- `src/core/indexing/symbol_index.py` — token-aware search
- `tests/test_symbol_index_search.py` — 9 тестов
- `src/mcp/tools/codebase_tool.py` — Вариант B (P1-P4)
- `.agent_task_state.md` — создан (auto-generated)
- `.gitignore` — добавлен `.agent_task_state.md`

**Статус:** ✅ Закрыто (commit 5aeb723, pushed to main)

## 2026-07-17 — Сессия закрыта: Explainability + IMPORTS + Drift Detector

**Итог сессии (17:30–23:00 UTC+3):**

| Компонент | Статус | Коммит |
|-----------|--------|--------|
| R&D 4 идей, 5 прототипов, сравнение с 15 инструментами | ✅ | — |
| Explainability Layer (SearchTracer + ChunkTrace) | ✅ | `012da96` |
| PropertyGraph IMPORTS (0→788 рёбер, 20 языков) | ✅ | `142761d` |
| Architecture Drift Detector (graph_query action=drift) | ✅ | `f03204f` |
| Fallback path fix для Drift Detector | ✅ | `5058196` |

**Финальное состояние PropertyGraph:**
- 4473 nodes, 5733 edges
- 788 IMPORTS (было 0), 1072 CALLS, 1405 DEFINES, 2468 ASSIGNED_FROM

**Финальное состояние индекса:**
- 3820 chunks, 263 files, 2605 symbols

**Всего:** 5 коммитов, ~800 строк кода, 8 файлов изменено/создано.

**Статус:** ✅ Сессия закрыта

---

## 2026-07-18 — Сессия закрыта: LanceDB corruption recovery + Search stability

**Итог сессии — Полное расследование и исправление повреждений LanceDB:**

| Компонент | Статус |
|-----------|--------|
| 5 root causes найдено и исправлено | ✅ |
| `index_status.py` — stale cache fix, `count_rows()` всегда live | ✅ |
| `db_writer.py` — callback-синхронизация `_safe_recreate_table` | ✅ |
| `indexer.py` + `engine.py` — `optimize()` и `create_index()` разделены | ✅ |
| `search_tools.py` — убраны `// File:`, безопасный float format | ✅ |
| `graph_tools.py` — исправлен `EdgeType` NameError | ✅ |
| `server_factory.py` — исправлен `dict(rrf_results)` ValueError | ✅ |

**Финальное состояние индекса:**
- 3853 chunks, 265 files, 36 tools working

**Всего:** 7+ файлов изменено, все 36 инструментов работают.

**Статус:** ✅ Сессия закрыта

---

## 2026-07-18 — Тесты WriteTool + баг-фикс filter_mismatch

**Задача:** Переписать `tests/test_write_tools.py` под `WriteTool` (вместо удалённых legacy-классов).

**Сделано:**
- 6 фикстур (`rename_tool`, `move_tool` и т.д.) → 1 фикстура `write_tool`.
- 6 классов тестов переименованы: `TestWriteToolRename`, `TestWriteToolMove`, `TestWriteToolSafeDelete`, `TestWriteToolReplace`, `TestWriteToolInsertBefore`, `TestWriteToolInsertAfter`.
- `execute.__wrapped__` / `execute` → прямые вызовы `_action_*`.
- Все 33 теста проходят.

**Найден и починен баг:** `_action_replace` и `_action_insert` падали с `IndexError` при `file_path`, который не содержит символ (пустой `defs` после фильтрации). Добавлены guard-проверки (как уже были в `_action_move` / `_action_safe_delete`).

**Изменённые файлы:**
- `tests/test_write_tools.py` — полная переделка
- `src/mcp/tools/write_tools.py` — guard для `_action_replace` (L258) и `_action_insert` (L315)

---

## 2026-07-18 - FIX: intel_get_runtime_status showed 768dim instead of 384dim

**Symptom:** intel_get_runtime_status showed ONNX (768dim), but real model is multilingual-e5-small-int8 (384dim). MCP logs confirmed embedding_dim=384, but UI formatter overrode with default.

**Root Cause:** ui_formatter.py (line 206-208) looked for model_info inside provider_status. But intel_get_runtime_status returns model_info at top level of data (layer.py line 435). Result: _info = {}, _dim = 768 (default).

**Fix:** ui_formatter.py now reads model_info from data (top level):
_info = data.get("model_info", {}) or {}

**Verified from clean state:**
- Command: restart MCP + intel_get_runtime_status
- Result: multilingual-e5-small-int8 (384dim) OK
- Model loaded: llama-server.exe (510 MB RAM)
- Index: 3765 chunks (not 0)

**Guard:** added test tests/test_ui_formatter_dim.py - verifies format_runtime_status shows real dimension from model_info.

---

## 2026-07-18 - FEATURE: Chunk-level content-addressed cache (skip re-embedding)

**Цель:** Экономить ~95% повторных эмбеддингов при правке 1 функции в файле.
По умолчанию file-level md5 -> весь файл переэмбеддится. Заменено на per-chunk sha256.

**Эксперимент (песочница):** benchmark_chunk_cache.py + test_chunk_cache.py + test_real_path.py
- Sliding window: 44.7% saved (наивный чанкер смещается)
- AST-aware: 95.6% saved (как в проде)
- Real-path test (LanceDBManager + IndexPipeline): 2 embeds -> 0 (re-run) -> 1 (edit 1 fn)

**Реализация (5 файлов):**
- db_manager.py: добавлена колонка chunk_hash в схему
- indexer_table.py: миграция chunk_hash (add_columns с pa.field для LanceDB 0.34)
- index_pipeline.py: SKIP-ЛОГИКА - chunk_hash до embed_batch, переиспользует вектор из БД
- db_writer.py: запись chunk_hash в record
- indexer.py: передача table в IndexPipeline

**Bug при миграции:** LanceDB 0.34 add_columns требует pa.field, не строку.
Исправлено: self.table.add_columns(pa.field(col, pa.string())).

**Backfill:** scripts/backfill_chunk_hash.py заполнил 3789/3789 chunk_hash для
существующего индекса (иначе cache никогда не сработал бы на старых данных).

**Verified from clean state:**
- MCP перезапущен, schema имеет chunk_hash
- Backfill: 3789/3789 заполнено
- Real-path test: ALL PASSED (2->0->1 embeds)
- Живой индекс: cache сработает при следующей правке файла
  (проверка на живом индексе заблокирована embedder idle-timeout - отдельный баг)

**Guard:** sandbox/chunk_hash_exp/test_real_path.py (real LanceDB, temp dir)

---

## 2026-07-18 - FIX: Embedder idle-timeout aborting indexing

**Symptom:** Incremental indexing failed with 'Embedder not ready. Indexing aborted.'
after ONNX model was unloaded by idle-timeout (5 min).

**Root Cause:** index_project_runner.py:165 checks is_ready() BEFORE indexing.
is_ready() returned False when _onnx_session was None (unloaded). But embed_batch()
itself lazy-reloads via _init_onnx() — so the check was blocking valid work.

**Fix:** is_ready() now lazy-reloads ONNX session if mode==onnx and session is None:
- Calls _init_onnx() on idle-unload, returns True if reload succeeds
- Returns False on reload failure (safe abort, unchanged behavior)

**Verified from clean state:**
- Sandbox test: test_idle_reload.py (lazy reload + safe failure) ALL PASSED
- Live: model unloaded at 20:34:44, indexing at 20:35:50 COMPLETED (87/87)
  No 'Embedder not ready' error after fix.

**Guard:** sandbox/embedder_idle_test/test_idle_reload.py

---

## 2026-07-18 - BUGFIX: Contradiction Ledger —三层根因分析与修复

**Симптом:** Ledger thread starts but never logs result (no ✅ or ⚠️). Three layered root causes.

**Root Cause 1:** `_resolve_ledger_project_root()` used broken self-made resolver — registry empty at startup, `PROJECT_PATH` env var = literal string `$ZED_WORKTREE_ROOT` (unexpanded by shell).

**Root Cause 2:** `_default_project_root` in `server_factory.py` was local variable (`from X import Y` + `Y = val` creates local shadow, never updates module-level `server._default_project_root`).

**Root Cause 3:** `subprocess.run(capture_output=True)` deadlock in daemon thread on Windows — `sys.stdout` redirected by MCP JSON-RPC, `git` writes to pipe that nobody reads, buffer fills, deadlock.

**Fix:**
1. `_resolve_ledger_project_root()` → `resolve_project_root()` from `server.py` (SQLite bridge)
2. `create_mcp_server()` uses `import src.mcp.server as _srv; _srv._default_project_root = ...`
3. `scripts/verify_diary.py` → `subprocess.Popen(stdout=PIPE, stderr=DEVNULL)` + `communicate()`

**Verified:** Isolation test (daemon thread + Popen): `ok=True, claims=9, commits=13`

**Guard:** `tests/test_contradiction_ledger.py`

---

## 2026-07-18 - BEST PRACTICE: Windows subprocess deadlock in daemon threads (§5.16)

**Rule:** NEVER use `subprocess.run(capture_output=True)` in daemon threads on Windows. ALWAYS use `Popen(stdout=PIPE, stderr=DEVNULL)` + `communicate(timeout=N)`.

**Root cause:** MCP server redirects `sys.stdout` (JSON-RPC), `capture_output` pipes conflict with OS descriptors → `git` blocks on write, Python waits for `git` → deadlock.

**Added to:** Global AGENTS.md §5.16, Project AGENTS.md Environment section.

---

## 2026-07-18 - AUDIT: MCP tool quality issues

**Findings:**
1. `get_commit_history` doesn't exist as separate tool — wrapped in `git(action="log")`. AGENTS.md was wrong.
2. `graph_query` — `query_type="cypher"` must be `action="cypher"` (UX improvement: added hint to error message)
3. `intel_get_hotspots` returns "No data" — correct (only 10 commits in repo, <3 changes per file)
4. `get_symbol_info("embedding_dim")` → 0 usages — known limitation (tree-sitter tracks function calls, not variable references)
5. `_default_project_root` in `server_factory.py` — module-level never updated (F811 shadow bug)

**Fixed:** AGENTS.md (project + global), graph_tools.py error message, server_factory.py module attribute update.

---

## 2026-07-18 - BUG FIX: AST cache invalidation in CodeParser._walk_file()

**Symptom:** After renaming a function, PropertyGraph kept stale CALLS edges pointing to the old name. `extract_calls()` returned outdated AST data on re-index.

**Root Cause:** `_walk_file()` cached AST by `file_path` only. When the same file was modified and re-indexed, the cache hit on path match, returning stale tree. `parse_file()`/`_parse_with_tree_sitter()` read the file fresh but never updated `_walk_file()`'s cache variables.

**Fix:** Changed cache check from `file_path == self._cache_path` to `file_path == self._cache_path and code == self._cache_code`. File is always read ("<1ms overhead), but AST is only re-parsed when content actually changes.

**Why NOT mtime:** NTFS mtime can be wrong (antivirus, WSL, shutil.copy). Content comparison is ground truth. File read is <1ms, not worth optimizing.

**Impact:** PropertyGraph now gets correct CALLS edges on every re-index. Prevents "information garbage" accumulation in dependency graph.

**Guard:** `tests/test_ast_cache_invalidation.py` (5 tests: single-file rename, consumer rename, sequential renames A->B->C, same-content cache reuse, full PropertyGraph consistency with ghost-node check)

**Verified from clean state:** `pytest tests/test_ast_cache_invalidation.py -v` → 5/5 passed in 0.43s

---

## 2026-07-18 - VERIFIED: Chunk-level cache working end-to-end

**Finding:** Chunk-level cache was already fully implemented in `index_pipeline.py`. Verified live data:
- 3792 total chunks, 3705 (97.7%) with `chunk_hash`
- 255/260 files at 100% cache coverage
- Schema has `chunk_hash` column, db_writer stores it, index_pipeline queries and skips embed_batch for cached chunks

**Benchmark (AST-aware chunking):** 95.4% skip rate on 1-5% file edits. Saves ~700ms per file save (CPU embedder).

**Remaining:** 87 chunks (5 files) without `chunk_hash` — legacy from before feature was added. Auto-fixed on next re-index.

---

## 2026-07-18 - BUG FOUND: Ghost nodes test revealed AST cache staleness

**How found:** Cross-file dependency test (producer.py defines func, consumer.py calls it). After renaming in consumer only, PropertyGraph still showed `run_pipeline --[CALLS]--> calc_data` instead of `process_data`.

**Deduction chain:** Test showed wrong edges → suspected AST cache → added debug logging → confirmed `extract_calls()` returns stale data when file content changed but path unchanged → found `_walk_file()` only compares path → fixed with content comparison.

**Lesson:** Ghost-node cross-file tests are effective at catching indexing bugs that single-file tests miss.

---

## 2026-07-19 - ANALYSIS: 4 code-intelligence проекта (fallow, code-review-graph, chunkhound, repowise)

**Цель:** вскрыть, что реально работает vs бутафория, что перенять в MSCodeBase.

**Метод:** клонирование в `D:\analysis_sandbox` + 4 параллельных саб-агента (глубокое чтение исходников) + реальные прогоны CLI.

**Ключевые выводы:**
- Во всех 4 проектах ЯДРО — реальный код, НЕ заглушки. Бутафория — в маркетинговых заголовках (числа circular/завышены), не в пустых функциях.
- **fallow** (Rust): dead-code/health/audit реально работают (прогон: 66 dead files, score 50/D). «Call resolution» — оверпромисинг (на деле import-graph). Fallow Runtime — закрытый платный слой.
- **code-review-graph** (Py): граф/FTS5/incremental/30 tools реальны (прогон: 7 nodes/11 edges). «82x token reduction» / «recall 1.0» — circular upper bound (сами признают в README).
- **chunkhound** (Py): parser/DuckDB/research реальны, НО `index` падает без embedding provider (нет regex-only режима). LanceDB-provider — write-only (антипаттерн). «Ollama local» — убран из кода.
- **repowise** (Py+TS): code-health/graph/git/decisions реальны (прогон `init --index-only` без ключа: 3 files/5.4s). ROC AUC 0.74 — только во внешнем bench-репо. «−96% tokens» — метрика загрузки, не счёта при caching.

**Что перенять (приоритеты):**
- Tier 1: token-savings panel (CRG), `_meta` stale_warning (repowise), lean MCP-surface (CRG/repowise), exit 0/1/2 + SARIF (fallow), suppression markers (fallow).
- Tier 2: incremental SHA-256 (CRG), edge confidence tiers (CRG), 3-tier call resolution (repowise), hybrid FTS+vector (CRG), cAST chunking (chunkhound).
- Tier 3: code-health biomarkers (repowise), git hotspots+ownership (repowise), deterministic refactoring (repowise), ADR mining substring-gate (repowise), SA-IS dup (fallow), multi-repo daemon (CRG), boundary presets (fallow), citation engine (chunkhound).

**Антипаттерны:** не копировать circular-метрики как заголовки; не портировать LanceDB-chunkhound (write-only); не тратить время на Fallow Runtime (closed); не делать MCP-subprocess-фасад (fallow) — у нас прямые вызовы.

**Артефакт:** `docs/ANALYSIS_4_PROJECTS.md` (полный отчёт с экспериментальными данными).

**Следующий шаг:** начать с Tier 1 (token-savings panel + stale_warning + lean-surface) — быстрые выигрыши с видимостью ценности.

---

## 2026-07-19 - ANALYSIS UPDATE: real-scale + наши боли (критика учтена)

**Контекст:** владелец раскритиковал первый отчёт по 3 пунктам: (1) «0 TODO» повторяется как слабый сигнал, (2) прогоны на игрушечных репо (2-8 файлов), (3) не смотрели на наши реальные боли недели (race condition, сломанная установка `lancedb>=0.12.0`). Сделал продолжение.

**Что добавлено в `docs/ANALYSIS_4_PROJECTS.md`:**
- Дисклеймер после TL;DR: понижен вес «0 TODO/NotImplementedError» (отсутствие маркера ≠ отсутствие багов; единственное док-во — реальные прогоны).
- **Section 9 (real-scale):** прогон CRG + repowise на клоне `mscodebase-intelligence` (133 py / 40k LOC). CRG: 17s, 2717 nodes/24943 edges. repowise: 38s, 3461 nodes/7516 edges, 16 hotspots, self-validated health (13/20 low-health files имели bug-fix, 4.73x baseline). Архитектурные заимствования (SQL-BFS, Leiden) теперь обоснованы реальным масштабом, не 11 edges.
- **Section 10 (наши боли):** 2 сфокусированных саб-агента.
  - 10.1 Concurrency: fallow (process isolation), CRG (WAL+busy_timeout+_cache_lock+model RLock), chunkhound (SerialDatabaseExecutor max_workers=1 + thread-local + Future-изоляция + compaction Event-guard), repowise (async session-per-call + RateLimiter). Перенять: SerialDatabaseExecutor + Future-изоляция вместо нашего `self._results` по request_id.
  - 10.2 Deps: chunkhound победил (`uv sync --locked` + requirements-lock.txt), repowise (upper bounds `>=,<next-major`), fallow (deny.toml yanked=deny). Перенять: commit uv.lock + CI `--locked` gate + upper bounds на lancedb/mcp/tree-sitter*.

**Tier 1 обновлён:** добавлены пункты 0 (lockfile + clean-install CI gate — чинить сейчас, не требует исследования) и 1 (SerialDatabaseExecutor — устраняет наш race). Оба выше чужих идей, т.к. проблемы уже реальны.

**Вывод:** наши две главные боли этой недели У КОНКУРЕНТОВ УЖЕ РЕШЕНЫ проверенными паттернами. Не нужно изобретать — перенять SerialDatabaseExecutor (chunkhound) + uv sync --locked (chunkhound) + upper bounds (repowise) + deny.toml (fallow).

---

## 2026-07-19 - IMPLEMENTED: Пункт 0 (deps hardening) — DONE

**Контекст:** из анализа 4 проектов (Section 10.2) — наш `lancedb>=0.12.0` инцидент этой недели. У конкурентов (chunkhound `uv sync --locked`, repowise upper bounds) эта проблема решена. Внедрил аналог.

**Что сделано:**
1. **Exact-pin `lancedb==0.34.0`** в `pyproject.toml` + `requirements.txt` (rationale comment: 0.x менял API внутри минорных релизов, сломал тест-сьют 2026-07). Запинил НЕ нижнюю границу диапазона (`0.12.0`), а версию из рабочего extension-venv, на которой тесты проходят.
2. **Валидация API перед пином** (урок от владельца): проверил `dir(lancedb)` для `0.12.0` (нет `Table` → сломал бы `index_guard.py:216`) и для `0.34.0` (есть `Table`, `DBConnection`, `connect`, `connect_async` → все True). Пин `0.34.0` корректен.
3. **Upper bounds** на `mcp>=1.0.0,<2`, `tree-sitter*>=0.21.0,<1`, `numpy>=1.24.0,<3` (repowise стиль `>=,<next-major`).
4. **`requirements-lock.txt`** сгенерирован (`pip freeze` из рабочего venv, 75 строк, `lancedb==0.34.0`). Как chunkhound `requirements-lock.txt`.
5. **`verify_clean_state.sh`** — добавлен lockfile drift-gate (аналог `uv lock --check`): если pyproject exact pin != lock → CI падает. На Linux-CI ставит из lock, локально — по bounds.
6. **`install.py`** не сломан — он ставит из `requirements.txt` (уже обновлён).

**Урок (критично):** пинить версию без проверки API — та же ловушка, что и unbounded range, с другой стороны. Нижняя граница диапазона (`0.12.0`) НЕ равна «проверенной рабочей версии». Пин должен фиксировать версию, на которой реально тестировали текущий код. Проверка: `lancedb.DB` в нашем коде — только строковые аннотации/комментарии, не реальный вызов; реально дёргаем `connect/connect_async/DBConnection/Table` (все есть в 0.34.0).

**Verification:** pyproject.toml валиден (tomllib), drift-gate локально прошёл (lancedb 0.34.0 == 0.34.0 OK; mcp/tree-sitter range → skip).

---

## 2026-07-19 - IMPLEMENTED: Пункт 1 (race condition fix) — DONE

**Контекст:** из анализа 4 проектов (Section 8) — паттерн `SerialDatabaseExecutor` из chunkhound (threading.Lock + Event fast-fail) решает наш межпотоковый race между search_code (event-loop) и intel_trigger_reindex (executor).

**Что сделано:**
1. **`db_manager.py`** — добавлен `threading.Lock` (`_write_lock`) + `threading.Event` (`_reindex_guard`) + методы `set_reindexing()`/`clear_reindexing()`/`is_reindexing()`/`begin_write()`.
2. **`layer.py`** — `set_reindexing()` вызывается перед `run_in_executor` в `_run_reindex_job`, `clear_reindexing()` в finally.
3. **`engine.py`** — `hybrid_search()` проверяет `is_reindexing()` → fast-fail (пустой результат) вместо падения.
4. **`tests/test_lancedb_race.py`** — стресс-тест с N=8 search + N=4 reindex воркерами, проверка корректности (не только "не упало").

**Результат теста:** `ok=8, fast_fail=152, exceptions=0, wrong_chunk=0` — race исправлен, guard сработал 152 раза.

**Урок (AGENTS.md §5.13):** замена одного thread-safety механизма другим создает новую поверхность для гонки (общий словарь результатов, общий correlation id). Каждая замена требует стресс-теста на корректность данных, а не только отсутствия исключений.

---

## 2026-07-19 - RESEARCH: 5 экспериментов — Smart Summary breakthrough

**Контекст:** Инженерный аудит для определения архитектурного направления. 5 экспериментов с реальными данными на MSCodeBase (136 файлов, 40K строк).

### Результаты экспериментов

**Experiment 1: FTS5 3-Index vs Keyword Search**
- FTS5 и Keyword имеют 10% пересечение результатов → дополняют друг друга
- Внедрено в Session 1: `fts5_index.py`, `fts5_mixin.py`, `engine.py`

**Experiment 2: Tree-sitter vs Python AST**
- AST точнее для Python (docstrings, type hints), Tree-sitter лучше для мультиязычности
- Вывод: AST для Python, Tree-sitter для остального

**Experiment 3: Compiler Concept (Full Fact Sheet) — ❌ FAILED**
- Полный fact sheet: 126,767 токенов (136 файлов, все символы, все зависимости)
- Точность: 100% (10/10 запросов)
- Экономия токенов: **-250%** (ФАКТ ДОРОЖЕ файлов!)
- Root cause: fact sheet содержит ВСЁ, broad queries (hotspots, deps) возвращают 20-60 ответов = massive payload
- Вывод: Полный fact sheet НЕ работает как замена чтению файлов

**Experiment 4: PageRank File Importance**
- `runtime_coordinator.py` — самый важный файл (score 0.667, 43 in-degree)
- Top 10% файлов (13) = 47.6% экономии токенов
- Top 20% файлов (27) = **-2%** (хуже полного! потому что важные = большие)
- Вывод: PageRank хорош для PRIORITIZATION, не для REDUCTION

**Experiment 5: Smart Summary — 🎯 BREAKTHROUGH**
- Compact summary: **2,037 токенов** (vs 126,767 полный)
- Точность: **90%** (9/10 запросов)
- Build time: **0.4ms** (vs 337ms полного)
- Экономия: **98.4%** vs полный fact sheet
- Архитектура: Agent → Smart Summary (2K tokens) → Find file → Load detail on demand
- Вывод: Tiered approach работает. Summary как "карта", detail on demand.

### Что сделано
1. Созданы скрипты экспериментов: `run_experiment_compiler_v2.py`, `run_experiment_pagerank.py`, `run_experiment_smart_summary.py`
2. Результаты сохранены в `experiments/*_results.json`
3. Результаты добавлены в `experiments/deep_research_log.md`

### Урок (критично)
**"Полный fact sheet" — ловушка оптимизации.** Чем больше данных предвычисляешь, тем дороже их загружать в контекст. Правильный подход: **маленькая "карта" (2K tokens) + ленивая загрузка деталей**. Это как GPS: показывает маршрут, а не все улицы города.

### Verification: Эксперименты запускались изолированно через spawn_agent, результаты в JSON-файлах.

---

## 2026-07-19 - RESEARCH: GitHub проекты — конкурентный анализ

**Контекст:** Изучение топовых open-source проектов с похожей архитектурой (code intelligence, search, indexing).

**Проекты проанализированы:**
1. **srclight/srclight** (52★) — Tree-sitter based code intelligence
2. **Cranot/roam-code** (500★) — Code navigation with CSR sparse PageRank
3. **chunkhound** — Semantic code search с FTS5 + vector
4. **repowise** — Codebase indexing с dependency tracking

**Ключевые идеи заимствованы:**
1. FTS5 3-index approach (srclight) → внедрено в `fts5_index.py`
2. SerialDatabaseExecutor pattern (chunkhound) → threading guard в `db_manager.py`
3. PageRank importance scoring (roam-code CSR algorithm) → протестировано
4. Tiered fact sheet concept → Smart Summary breakthrough
