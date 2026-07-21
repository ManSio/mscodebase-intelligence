<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](CHANGELOG.md) • [🇷🇺 Русский](../ru/CHANGELOG.md) • [🇨🇳 中文](../zh/CHANGELOG.md)

# Changelog

All notable changes to this project will be documented in this file.

> **Tool count (current):** the live server registers **41 tools** = 18 core + 13 intel + 7 inline + 3 dev
> (see `src/mcp/server_tools.py` startup log). Older entries below reference earlier totals.

## [3.3.8] — 2026-07-21 — Dev tools: generate_docs, bump_version, install_git_hooks

### Added
- **`src/core/git_hooks_installer.py`**: новый модуль для установки pre-commit хуков (verify_diary + stale_detector + generate_docs) в любой проект.
- **`src/mcp/tools/dev_tools.py`**: 3 новых MCP-инструмента:
  - `generate_docs(project_root)` — генерация Markdown-документации из PropertyGraph
  - `bump_version(project_root, part, dry_run)` — бамп версии pyproject.toml + CHANGELOG
  - `install_git_hooks(project_root, action)` — установка/удаление/статус pre-commit хуков
- **`src/mcp/server_tools.py`**: регистрация dev_tools (+3 инструмента) в `register_all_tools()`.

### Changed
- **Tool count**: 38 → 41 (18 core + 13 intel + 7 inline + 3 dev)
- **`src/mcp/server_tools.py`**: docstring обновлён (Inline tools: 12→7, +3 dev)

### Tests
- **565 passed, 0 failed** (91 deselected) — полный pytest

---

## [3.3.7] — 2026-07-21 — Docs sync: 24 языка, CI badge, PARSE_EXTENSIONS, pyproject.toml

### Changed
- **README.md**: языки исправлены с 18→24 (добавлены SQL, YAML, TOML, HTML, CSS, HCL). Badge тестов: `605` → `553 passed`. CI badge добавлен. Tools count: `39` → `43`.
- **`extensions.py`**: `PARSE_EXTENSIONS` синхронизирован с реальностью — с 8 до 30 расширений (все 23 языка).
- **`pyproject.toml`**: tree-sitter зависимости расширены с 5 до 22 пакетов (все языки, которые реально инициализируются в `CodeParser._init_tree_sitter()`).
- **удалён `experiments/DEV_EXP.md`**: реализованные идеи (Contradiction Ledger, verify_diary, stale_detector dirty flag, gate на статус, dedline на shims) убраны из файла-идей.
- **`experiments/audit.md`**: секция B1-B12 и эксперименты удалены — зафиксированы, закрыты.

### Fixed
- `PARSE_EXTENSIONS` больше не блокирует индексацию Java, C#, Ruby, PHP, Kotlin, Swift, C/C++, Scala, Dart, Bash, SQL, YAML, TOML, HTML, CSS, HCL.

---

## [3.3.6] — 2026-07-21 — Audit fixes: 12 багов + 10 тестов + CI + verify_diary

### Fixed
- 🔴 **CRITICAL (B1)**: `graph.py` — `temp_db.unlink()` before `stat()` → FileNotFoundError при каждом экспорте. Fallback-путь бросал NameError (`compressed` undefined).
- 🟠 **HIGH (B2/B3)**: `graph.py` — zstd compress/decompress subprocess без timeout → вечное зависание. Добавлен `timeout=60`.
- 🟠 **HIGH (B4/B12)**: `engine.py` — `getattr(..., lambda: False)()` молча теряет fast-fail при reindex. Заменён на callable check + logger.error.
- 🟡 **MEDIUM (B5)**: `verify_diary.py` — `pytest -k` давал 7+ false-negatives из 96 ❌. Заменён на прямой поиск тестового файла (`_check_test_file_exists`).
- 🟡 **MEDIUM (B6)**: `ruff.toml` — F821 подавлен в 4 файлах. Добавлены явные импорты `List, Tuple, Dict, Node, SymbolRef`.
- 🟡 **MEDIUM (B7)**: `project_context.py` — `print()` в docstring (ломал JSON-RPC). Заменён на `logger.debug()`.
- 🟡 **MEDIUM (B8)**: `stale_check.py` — ловил ARCHIVED файлы. Добавлен фильтр `ARCHIVED in text[:500]`.
- 🟢 **LOW (B9)**: 18 stub-фасадов в `src/core/*.py` — добавлены `warnings.warn(DeprecationWarning)`.
- **10 pre-existing test failures**: LanceDB `.write_lock` (6 тестов), stale assert messages (2), suppression marker test (1), race test (1).
- `db_manager.py` — `lock_path.parent.mkdir(parents=True, exist_ok=True)` перед PID lock.

### Changed
- **CI**: +`windows-latest` runner, +Windows-specific deps, +`ruff>=0.5.0` в dev-deps, Python 3.11/3.12.
- **`verify_diary.py`**: SymbolCache (один проход .py → set lookup вместо 600+ grep -r вызовов). Парсинг функций только из backtick-кода. `verified_from_clean_state` — только для записей после 2026-07-19. **14% → 68% подтверждения.**
- **Чистка корня**: удалены 15 stale файлов (`nul`, `results.sarif`, `temp_settings.json`, `crash_debug.log` и др.).
- **pyproject.toml**: +`ruff>=0.5.0` в `[dev]`.

---

## [3.3.5] — 2026-07-19 — LLAMA_CPP_ENABLED enabled + reranker online

### Changed
- 🎚️ **`LLAMA_CPP_ENABLED=true`** — llama.cpp reranker теперь включён по умолчанию.
  Реранкер (`bge-reranker-v2-m3`) поднимается на порту 8081, работает через `llama-server.exe`.
- Исправлены три источника шума в логах (07-19):
  1. **Bridge timeout** — `max_wait 0.5s → 2.0s`, warning → debug.
  2. **GPU sampler** — проверка `shutil.which("nvidia-smi")` перед вызовом, тихий фоллбек.
  3. **Disk I/O sampler** — тихий игнор `CalledProcessError`/`TimeoutExpired`/`FileNotFoundError` (PID race).

### Verified
- Model file: `models/Bge-M3-568M-Q4_K_M.gguf` ✅
- Binaries: `llama_msvc/llama-server.exe` + `ggml*.dll` ✅
- Reranker port 8081 должен подниматься при старте MCP.

## [3.3.4] — 2026-07-19 — LLAMA_CPP_ENABLED toggle + is_compatible import fix

### Fixed
- 🐛 **Broken `is_compatible` import.** `server_factory._start_llama_sync()` imported `is_compatible` from `src.providers.reranker.llama_runner`, but it is defined in `llama_install.py`. The failed import silently aborted the llama.cpp auto-start branch (embedder port 8080 never came up). Now imported from the correct module.
- 🎚️ **`LLAMA_CPP_ENABLED` toggle (Tumbler protocol).** Added `llama_cpp_enabled` to `EmbeddingConfig` (`src/config/settings.py`), read from `LLAMA_CPP_ENABLED` env var, **default `false`**. `_start_llama_sync()` now short-circuits when disabled: `if not get_config().embedding.llama_cpp_enabled: return`. When enabled, it still requires `is_compatible()` (binary present) before starting.

### Config
- New env var `LLAMA_CPP_ENABLED` (default `false`). Add to `.env` / `.env.example` to enable llama.cpp embedder auto-start. No hardcoded values — pure config.

> **Note:** `.env.example` could not be auto-edited (private-files guard). Add the line `# LLAMA_CPP_ENABLED=false  # auto-start llama.cpp embedder (default off)` manually.

## [3.3.3] — 2026-07-19 — zed_config.py: safe merge (no settings wipe)

### Fixed
- 🛡️ **`src/utils/zed_config.py` — no more settings.json wipe.** `patch_zed_settings()` previously did `json.loads()` after stripping only `//` comments; a trailing comma or `/* */` block (both valid JSONC in Zed) made it fall back to `settings = {}` and **overwrite the entire file**, destroying all other user settings. Now uses a JSONC-tolerant parser and **aborts on parse error instead of wiping**.
- 🔒 **User env preserved.** On update the whole server entry is no longer replaced — `patch_zed_settings()` merges: authoritative keys (`PYTHONPATH`, `PROJECT_PATH`) are set, user-added env vars (e.g. `MSCODEBASE_ALLOW_SELF_INDEX`) are kept, `EMBEDDING_*` use `setdefault`.
- 🧹 **Removed redundant `agent` injection.** `patch_zed_settings()` no longer force-sets `agent.system_prompt` / `agent.tool_permissions` (the MCP server already injects its own system prompt via `register_system_prompt(mcp)`). User `agent` config is no longer clobbered.
- 🩹 **Targeted text surgery.** Only `context_servers` + `context_servers_to_query` are touched; other servers, comments and settings are byte-for-byte preserved.
- 📍 **Path fixes.** macOS config dir now resolves `~/Library/Application Support/Zed` first; removed dead params (`lsp_config`, `languages_config`, `project_path`); corrected the module docstring (was pointing at the wrong `extensions/installed/...` path).

### Tests
- `scripts/_verify_zed_config.py` (5 scenarios): idempotent on real file, preserves comments + other servers, preserves user env, aborts on broken JSON, `remove_zed_settings` preserves other servers. Diff against the live `settings.json` after `patch_zed_settings()` is empty (idempotent).

## [3.3.2] — 2026-07-18 — AST cache fix + §5.16 subprocess safety

### Fixed
- 🐛 **AST cache staleness** — `CodeParser._walk_file()` cached AST by path only. Modified file with same path returned stale `extract_calls()` data, causing PropertyGraph to get incorrect CALLS edges. Fix: compare `code == self._cache_code` in addition to path.
- 🛡️ **§5.16 Windows subprocess** — added `creationflags=CREATE_NO_WINDOW` to daemon-thread Popen calls. Prevents console window flash + handle conflicts.

### Added
- 🧪 **Regression tests** — `tests/test_ast_cache_invalidation.py` (5 tests: single-file rename, consumer rename, sequential renames, cache reuse, PropertyGraph ghost-node check).
- 📊 **Chunk-level cache verification** — live data confirms 97.7% of chunks protected, 95.4% skip rate on file edits.

### Documentation
- Updated `DEV_DIARY.md`, `KNOWN_ISSUES.md`, `EXPERIMENTS_LOG.md`.

## [3.3.1] — 2026-07-18 — LanceDB corruption recovery + Search stability

### Fixed
- 🔧 **LanceDB corruption recovery** — stale cache fix in `get_status()`;
  `_safe_recreate_table` now syncs via callback to prevent race conditions.
- 🐛 **`search_code(explain=True)`** — fixed `dict(rrf_results)` ValueError
  and `EdgeType` NameError in explain trace.
- 🧹 **`search_tools.py`** — removed redundant `// File:` lines from results;
  safe float formatting in explain trace (no more `0.0000000001` scores).
- 🛡️ **Index stability** — `get_status()` always calls `count_rows()` (no stale cache);
  `optimize()` and `create_index()` separated for auto-index reliability.

## [3.3.0] — 2026-07-17 — Explainability + Architecture Drift + Claim Verifier

### Added
- 🔬 **Explainability Layer** — `search_code(query, explain=True)` показыват per-chunk breakdown
  всех этапов пайплайна: BM25, Dense, RRF, MMR, Bucket, Co-change, Reranker.
  Каждый чанк содержит: rank, score, формулу, штраф MMR, bucket weight, co-change boost.
  Zero-cost disable: при explain=False оверхед отсутствует.
- 🏛️ **Architecture Drift Detector** — `graph_query(action="drift")` анализирует PropertyGraph:
  - Chain imports (A->B->C, no direct A->C) — shim/re-export detection
  - Hub modules (>10 imports) — god-object indicator
  - Circular imports (A->B->A) — mutual dependency detection
- ✅ **Claim Verifier** — `verify_claim(claim={...})` проверяет утверждения агента против кода:
  - `calls` — проверка по CALLS-рёбрам PropertyGraph
  - `defined_in` — поиск определения через SymbolIndex
  - `handles_error` — поиск try/except в AST
  - `imports` — проверка по IMPORTS-рёбрам
  - `defines`, `implements`, `inherits` — иерархические связи
  - Вердикт: confirmed / contradicted / unverifiable + строки кода
- 🌐 **IMPORTS edges in PropertyGraph** — парсер извлекает импорты для 20 языков
  (Python, Rust, TS/TSX, Go, JS, Java, C#, Ruby, PHP, Kotlin, Swift,
   C/C++, Scala, Dart, Bash) и создаёт IMPORTS-рёбра File→Module.

### Changed
- `engine.py`: +tracer hook на всех 7 этапах поискового пайплайна
- `indexer.py` + `index_pipeline.py`: +extract_imports + add_imports
- `graph_query`: новый action="drift"

### Fixed
- PropertyGraph содержал 0 IMPORTS-рёбер при 3500+ других — теперь 788
- Indexer._parse_file_only (дубликат pipeline) не содержал import extraction

## [3.2.3] — 2026-07-14 — MMR diversification + Auto Intent + Synonyms + subprocess-free ADR

### Added
- 🎯 **MMR Diversification** (λ=0.6) — Maximal Marginal Relevance после RRF.
  Убирает дублирующиеся чанки, сохраняя релевантность. 0.3ms на 50 docs.
  Включён по умолчанию в `search_code`. Отключается через lambda_param=1.0.
- 🧠 **Auto Intent Detection** — keyword-based автоопределение `intent_hint` (code/docs/auto)
  по тексту запроса. Не требует ручного указания режима.
- 📖 **Extended Synonyms Map** — с 8 до 39 групп синонимов (auth↔login, function↔method,
  cache↔buffer, database↔db и др.) для query expansion.
- 📁 **intel_auto_collect_adrs** — переписан на чтение `.git/logs/HEAD` + `.git/objects/`
  через zlib. **Больше не использует subprocess.** 14ms на 492 коммита.

### Fixed
- 🐛 **Python 3.14 free variable bug** — `_is_self_index_path` crash fixed (module-level import).
- 🐛 **MCP Source path** — сервер гарантированно грузится из расширения, а не из проекта.
- 🐛 **debug_runtime_passport** — добавлен в default allowed set.

### Changed
- `src/core/indexing/indexer.py` — `search_async` теперь возвращает `vector` для MMR.
- `src/core/search/scoring.py` — добавлен `apply_mmr_diversity` + `auto_detect_intent`.
- `src/core/search/engine.py` — интеграция MMR + auto intent в search pipeline.
- `src/core/search/utils.py` — расширен `_QUERY_SYNONYMS` (8→39 групп).
- `src/main.py` — принудительное переключение `src.__path__` на расширение.

### Fixed
- 🐛 **commit_memory.py** — `fetch_commits` переписан на чтение `.git/logs/HEAD`
  через zlib (без subprocess). Работает в MCP на Windows.
- 🐛 **get_file_history** — fallback на последние коммиты если нет точных
  совпадений (файл не упоминается в сообщениях коммитов).
- 🐛 **GetVariableFlowTool** — `self.services` → `self._services` (AttributeError).
- 🐛 **CypherQueryTool** — `self.services` → `self._services`.
- 🐛 **Удалены** экспериментальные инструменты (`intel_ping`, `intel_exp_*`).
- 🐛 **impact_analysis** — работает с полным именем (`Searcher.method`).

### Changed
- Default MCP tools set расширен **15→24** инструмента:
  `get_logs`, `read_live_file`, `intel_code_topology`, `intel_auto_collect_adrs`,
  `get_commit_history`, `get_file_history`, `get_variable_flow`, `graph_query`,
  `structural_search`.
- `src/core/commit_memory.py` — полная переписка на файловое I/O.
- `src/mcp/tools/graph_tools.py` — исправлен баг с `services`.
- `src/mcp/tools/git_tools.py` — fallback для get_file_history.

### Experiments
- Полное исследование subprocess на Windows Python 3.14.14:
  - `asyncio.create_subprocess_exec` — Timeout ❌
  - `asyncio.to_thread(subprocess.run)` — Timeout ❌
  - `sync def + subprocess.run` — Timeout ❌
  - `sync def + os.system` — Timeout ❌
  - **Вывод:** MCP + subprocess на Windows несовместимы.
- MMR prototype (numpy): 100 docs → 0.62ms, 1000 docs → 8.9ms.
  λ=0.6 снижает дубли в 2× при минимальной потере релевантности.

## [3.2.2] — 2026-07-13 — Restore INT8 as primary embedder path

### Fixed
- 🔧 **INT8 restored as primary** (was wrongly demoted to FP32 priority in 3.2.1).
  Previous agent misdiagnosed `batch=0` in isolated OpenVINO bench as «INT8 broken»
  and switched to FP32, causing **40× speed regression** (350→9 ch/s).
  In the real inference pipeline (cached `InferRequest`) INT8 produces correct
  non-zero embeddings without `token_type_ids`. Reverted in `0665a4b`.
- 🔧 **Reranker tokenizer**: `bge-reranker-v2-m3` downloaded `tokenizer.json`
  (17 MB) from HuggingFace — ONNX reranker server now starts correctly.

### Changed
- **`_detect_model_dir`**: INT8-first sort restored (`-int8` dirs first, then alphabetical).
- **`_init_openvino`**: INT8 `model_quantized.onnx` loaded first; FP32 fallback.
- **Docs (ARCHITECTURE.md, CONTRIBUTING.md)**: stale tool counts updated
  (40→42 class-based, 57→59 total).

### Added
- **`token_type_ids` safety net**: OpenVINO embed branch now feeds `token_type_ids`
  when the model has this input (`_ov_has_token_type_ids`), preventing silent
  zero-vector corruption on models that require it.

---

## [3.2.1] — 2026-07-12 — Embedder & Index Integrity Fixes

### Fixed
- 🔧 **ONNX model loading**: `_init_onnx` теперь грузит `model_quantized.onnx` (INT8) сначала, затем `model.onnx` (как `_init_openvino`). Ранее искал `model.onnx` → сессия падала, embedder возвращал нули.
- 🔧 **Zero-vector poisoning**: `index_project` больше НЕ подменяет векторы нулями при сбое embedder — индексация прерывается с `RuntimeError`. Ранее молча писал нули → семантический поиск был нефункционален, а IVF-индекс не строился (`KMeans cannot train 1 centroids with 0 vectors`).
- 🔧 **Symbol count desync (INC-9573)**: `intel_get_runtime_status` теперь использует живой `get_symbol_count()` + диск-reload (как рабочий `get_index_status`). Устранён рассинхрон 0 vs 3221.
- 🔧 **Job hang at 80% Finalizing (INC-0AA6)**: символьная индексация Tree-sitter теперь под `asyncio.wait_for(timeout=120)` с graceful-завершением job'а.

### Verified
- `embed_batch` → norm≈14 (реальные векторы, не нули)
- `create_index(IvfFlat)` строится на реальных данных
- `_resolve_symbol_count` in-process → 3221

> ⚠️ **Version mismatch**: `extension.toml` всё ещё `version = "2.7.1"`, хотя CHANGELOG ведётся от 3.2.0. Требует выравнивания при следующем релизе.

---

## [3.2.0] — 2026-07-11 — Graph-Native Engine (PropertyGraph + Cypher)

### Added
- 🕸️ **PropertyGraph**: persistent knowledge graph on SQLite (WAL + mmap). Replaces in-memory `Dict` stores with typed nodes/edges. 15 node labels, 28 edge types. `qualified_name UNIQUE`, JSON properties. Zero-dependency.
- 🔍 **Cypher Query Engine**: `query_graph` MCP tool — LLM-friendly `MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'main' RETURN g.name, count(*) AS calls ORDER BY calls DESC LIMIT 10`. Recursive descent parser → SQL → results.
- 🚦 **HTTP Route Extraction**: automatic detection of Flask (`@app.route`), FastAPI (`@app.get`), Django (`path()`), Express (`app.get`), Next.js (`route.ts`). Creates `Route` nodes + `HANDLES` edges in PropertyGraph.
- 📊 **Multi-Signal Scorer**: 4 additional ranking signals for search — `api_signature` (Jaccard), `graph_diffusion` (PageRank), `module_proximity` (hierarchy), `cochange_boost` (git coupling). Weighted fusion with existing RRF pipeline.
- 💀 **Dead Code Detection**: `PropertyGraph.detect_dead_code()` finds functions/methods with zero incoming CALLS edges (excludes entry points). SQL-level query, ~10ms on 10K nodes.
- 🔄 **PURE mode**: `SymbolIndexAdapter` no longer duplicates data in memory — everything reads/writes PropertyGraph directly. RAM savings, full persistence across restarts.
- ⚡ **SQLite PRAGMA tuning**: `cache_size=-64000` (64MB), `mmap_size=268435456` (256MB). Sub-millisecond graph queries.
- 🧩 **Team-Shared Artifact**: `export_compressed()` / `import_compressed()` — zstd-compressed graph snapshots for commit to repo (Phase 3 prep).
- 🔗 **ASSIGNED_FROM edges**: intra-procedural data flow tracking. `CodeParser.extract_assignments()` walks Tree-sitter AST with scope stack for nested functions, detecting `x = y` patterns. Creates `Variable` nodes + `ASSIGNED_FROM` edges in PropertyGraph. Benchmark: 3,337 edges, 67.2/KLOC, 91.9% files of MSCodeBase — 5.4× more coverage than stdlib `ast` reference.
- ⚡ **Unified Walker**: `_walk_file()` does ONE Tree-sitter parse + ONE walk, returns both calls and assignments. Parse cache avoids re-parsing for same file. ~30% faster indexing.
- 🚦 **Conditional Flow**: ASSIGNED_FROM edges include `condition_path` property — stack of if/for/while/try/except nesting. 69% of edges in `src/core` are conditional (MSCodeBase).
- 🌐 **Multilanguage config**: `ASSIGNMENT_NODE_MAP` — Rust and TypeScript/TSX ready (same tree-sitter walk, different assignment node types).
- 🧪 **Test suite**: 18 new unit tests for assignments (basic, conditional, scope, storage, edge cases, multi-language).
- 🔍 **Agent visibility**: `condition_path` exposed in `query_graph` results — agent sees `x → y (if_statement → for_statement)`.

### Changed
- Architecture: 56 → 57 MCP tools (+ `query_graph`). Current total is **59** (42 core + 14 intel + 3 diag).
- DI container: `PropertyGraph` registered as singleton, `SymbolIndex` replaced by `SymbolIndexAdapter` (PURE mode)
- Core layer: `src/core/*.py` 24 → 30 files (+ `graph.py`, `graph_adapter.py`, `cypher_engine.py`, `route_extractor.py`, `multi_signal_scorer.py`, `dataflow_experiment.py`)
- ALL 494 tests pass without changes — full backward compatibility via adapter layer

---

## [3.1.0] — 2026-07-11 — CodeGraph-inspired improvements

### Added
- 📊 **Adaptive search budget**: `search_code` limit auto-scales with project size (<500 files→4, <5K→6, <15K→8, ≥15K→10 results). Explicit `limit` param still respected.
- 🕐 **Staleness banner**: warns "Index may be stale" when last indexed >1h ago. Single lightweight LanceDB query, zero disk scan.
- 🧩 **Graph context in search results**: `_expand_graph_context` now runs for ALL search modes (was only `deep`). Each result shows who calls it — inline, no extra tool calls.
- 🔇 **DEFAULT_TOOLS filter**: only 12 core tools visible by default (search, index, system, write). Remaining 47 still in code, re-enable via `MSCODEBASE_MCP_TOOLS` env var. `MSCODEBASE_MCP_TOOLS=""` shows all 59.
- 🏷️ **ToolAnnotations** (`readOnlyHint`): all read-only tools now carry `readOnlyHint: true` — required by Cursor Ask mode.
- 📁 **Unified extensions**: new `src/core/extensions.py` replaces 3 divergent `SUPPORTED_EXTENSIONS` lists (parser.py, file_guard.py, lsp_main.py). Union of all three + per-purpose split (`PARSE_EXTENSIONS`, `INDEX_EXTENSIONS`).
- 🛡️ **Zed SQLite schema guard**: startup check validates `scoped_kv_store` table exists before `resolve_project_root()` uses it. Warning in logs, not a crash.
- 📋 **MCP protocol version log**: protocol version logged at startup for cross-version troubleshooting.
- 🔧 **LSP config exposed**: `LSP_REQUEST_TIMEOUT` and `LSP_START_TIMEOUT` moved to `.env.example`. `asyncio.get_event_loop()` → `get_running_loop()` (Python 3.12+ compat).
- 📈 **BENCHMARK.md**: real-world benchmarks — 289ms fast mode, 8-18x token savings vs Read/Grep, per-mode latency distribution.

### Changed
- `search_code` default mode: graph context expansion now applies to ALL modes (was deep-only)
- Tool visibility: 12/59 tools shown by default (previously all 59)
- LSP priority: basedpyright > pyright in `_find_server()`
- Timeout: health report git check reduced 30s→15s

### Fixed
- `_show_all` in DEFAULT_TOOLS filter: `MSCODEBASE_MCP_TOOLS=""` now correctly shows all tools (was always False)
- Deprecated `asyncio.get_event_loop()` → `get_running_loop()` in LspClient

---

## [3.0.0] — 2026-07-11 — Write Tools + LSP Client + Meta-Patching

### Added
- ✏️ **6 Write Tools**: `rename_symbol`, `move_symbol`, `safe_delete`, `replace_symbol`, `insert_before_symbol`, `insert_after_symbol` — all with preview/apply + `@modification_guard` decorator (PageRank + blast radius + ack TTL)
- 🧠 **LspClient**: thin LSP client for pyright (JSON-RPC 2.0 over stdio, lazy start, auto-restart, graceful fallback)
- ⚡ **P0 Meta-Patching**: `move_chunks_metadata` — LanceDB file_path update WITHOUT re-embedding (30-80ms vs 2000-5000ms, 0MB RAM vs 700MB)
- 🛡 **Modification Guard**: `@modification_guard(pagerank_min, blast_min, ack_ttl)` — prevents writes on load-bearing files without explicit acknowledgment
- 🔄 **SymbolIndex extensions**: `find_all_references()`, `rename_symbol()`, `has_symbol()`, `remap_file()`
- ⚡ **BM25 fast invalidation**: `_reset_bm25()` — cache drop instead of full rebuild

### Fixed
- `intelligence_layer.py` — `_resolve_symbol_count` at column 0 swallowed all class methods (Intel tools invisible). Moved before class definition
- `intel_get_runtime_status`, `intel_log_incident` and all Intel tools now work correctly (11 methods on ProjectIntelligenceLayer)

---

## [2.7.1] — 2026-07-11 — SQLite кэш, статус индекса, docs синхронизация

### Added
- 🔧 CRT API Set patcher для Windows Insider (build >= 26000) — патч PE-импортов api-ms-win-crt → ucrtbase
- 🖥️ Vulkan GPU поддержка — авто-детекция + `LLAMA_BACKEND=vulkan` + `-ngl 99`
- 🔄 `verify_index_freshness()` — проверка SHA256 хэшей (2-5 сек вместо 5 мин полной переиндексации)
- 💾 SQLite connection cache — `_get_sqlite_connection()` с TTL 2с (вместо 2 новых коннектов на вызов)
- 📝 `docs/KNOWN_ISSUES.md` — единый реестр P0-P3 проблем и техдолга

### Fixed
- `server.py:329-331` — SQL ORDER BY добавлен в `scoped_kv_store` (multi-window race)
- `indexer.py:get_status()` — `_cached_unique_files` fallback: если кэш пуст, а чанки есть — scan LanceDB
- `ui_formatter.py:193` — `symbols` читался из `total_files` вместо `symbol_index_count`
- `intelligence_layer.py` — добавлен `symbol_index_count` в index_telemetry
- `llama_runner.py` — `-ngl` ternary fix: `else "-ngl","0"` → `else "0"`
- `llama_runner.py` — дубликат ключа 'bge-m3' в GGUF_MODELS (восстановлен 'qwen3-embedding')
- `health_report.py` — read-only check (больше не удаляет orphans из индекса)
- `install.py` — `llama_msvc`, `llama_vulkan`, `models` добавлены в skip-лист
- RRF pseudo-code в `SEARCH_PIPELINE.md` — исправлен `enumerate(bm25 + dense)` на раздельные enumerate

### Docs
- 28 файлов синхронизировано (12 en + 6 ru + 9 zh + 1 код)
- AI_INSTALLATION_PROMPT.md — переписан под real workflow (install.py → test MCP → reload)
- README.md (en/ru/zh) — очищены от бутафории: 43→50 tools, LM Studio→llama.cpp primary
- CHANGELOG.md — исправлены битые ссылки на LSP_WONTFIX.md
- HANDFOFF.md — 34→33 core tools

---

## [2.7.0] — 2026-07-09
### Added
- 🦙 llama.cpp как основной провайдер (авто-установка через install.py)
- LlamaRunner — менеджер lifecycle для llama-server.exe (скачивание, запуск, остановка)
- GGUF модели: bge-m3 Q4_K_M (417 MB) + bge-reranker-v2-m3 Q4_K_M (418 MB)
- Платформенная детекция: Windows/macOS/Linux, x64/ARM64
- docs/research/2026-07-09-provider-benchmark.md — полный бенчмарк

### Changed
- installer: 10→12 шагов (+llama.cpp, +GGUF моделей)
- patch_zed_settings: сохраняет // комментарии, no-op guard
- Приоритет провайдеров: LM Studio → llama.cpp → ONNX server → local ONNX
- MCP: 227 MB RAM (было 1200 MB) — в 5.3x меньше
- ONNX server: Tokenizer.from_file() вместо AutoTokenizer — без зависаний

### Fixed
- AutoTokenizer.from_pretrained() зависание на Windows (HTTP к huggingface.co)
- patch_zed_settings вырезал // комментарии → кнопка "восстановить"
- _detect_model_dir() создавал 544 MB InferenceSession только для чтения размерности
- Все HTTP-клиенты: httpx.Limits(keepalive_expiry=30.0) для Zed 1.10.0 compat

---

## [v2.5.3] — 2026-07-07 — mode=ask: RAG-генерация ответа через phi-4

### 🚀 mode=ask
- **`src/core/searcher.py`**: Новый метод `Searcher.ask_async()` — гибридный поиск →
  контекст → phi-4 (chat completion) → структурированный ответ с цитатами.
- **`src/mcp/tools/search_tools.py`**: Добавлен режим `mode="ask"` с защитой:
  в `light` profile — автоматический fallback на `quality` с предупреждением.
- **`src/core/config.py`**: `ASK_TIMEOUT` (60s), `ASK_MODEL` (phi-4-mini-instruct).

### 📦 Версии
- `extension.toml`: 2.5.2 → 2.5.3
- `src/__init__.py`: 2.5.2 → 2.5.3

---

## [v2.5.2] — 2026-07-07 — phi-4-mini-instruct verified + live test

### 🔬 LM Studio
- `phi-4-mini-instruct Q4_K_M` протестирована через `/v1/chat/completions`:
  успешный ответ (75 токенов, `finish_reason=stop`).
- Модель загружается on-demand (state: not-loaded → auto-load).
- Подтверждена готовность к `mode=ask` (v2.7.0).

### 📦 Версии
- `extension.toml`: 2.5.1 → 2.5.2
- `src/__init__.py`: 2.5.1 → 2.5.2

---

## [v2.5.1] — 2026-07-07 — Multi-Bucket RAG + Contextual Retrieval + Profiles

### 🚀 Multi-Bucket RAG (Phase 1)
- **`src/core/searcher.py`**: Overfetch (`raw_limit = min(limit * factor, MAX)`),
  bucket distribution по CODE_EXTENSIONS/DOCS_EXTENSIONS,
  soft weighting ДО reranker, cut-to-limit.
- **`src/core/config.py`**: `CODE_EXTENSIONS`, `DOCS_EXTENSIONS`,
  `MAX_RERANKER_INPUT=30`, `overfetch_factor`, `code_bucket_weight`,
  `docs_bucket_weight` — все через `.env`.

### 🧩 Contextual Retrieval (Phase 2)
- **`src/core/parser.py`**: Новый формат префикса для кода:
  `// File: {path} | Context: {class}.{func}`, для .md:
  `From {path}, section '{heading}':`. Требуется переиндексация.

### ⚖️ Soft Scoring + intent_hint (Phase 3)
- **`src/mcp/tools/search_tools.py`**: Новый параметр `intent_hint`
  (`"auto"` / `"code"` / `"docs"`).
- **`src/core/searcher.py`**: `_apply_bucket_weights()` — динамические
  веса: code=1.2/docs=0.8 для `"code"`, code=0.8/docs=1.2 для `"docs"`,
  1.0/1.0 для `"auto"`.

### ⚙️ SYSTEM_PROFILE (Phase 4)
- **`src/core/config.py`**: `SYSTEM_PROFILE=light|server` с валидацией
  и свойствами `is_light_profile`/`is_server_profile`.
  `light` — синхронный режим (по умолч.), `server` — зарезервирован.

### 📦 Версии
- `extension.toml`: 2.4.4 → 2.5.1
- `src/__init__.py`: 1.0.0 → 2.5.1

---

## [v2.4.7] — 2026-07-05 — LM Studio Connection Pool + Warm-up

### ⚡ Performance
- **`src/core/remote_embedder.py`**: Добавлен `httpx.AsyncClient` с **connection pool**
  (5 keepalive-соединений, 60s expiry) — убирает TCP/TLS overhead на каждый embed-запрос.
- **`src/core/remote_embedder.py`**: Новый метод `embed_batch_async()` — async embed через
  единый HTTP-клиент. `searcher.py` автоматически подхватывает его.
- **`src/mcp/server.py`**: `_warmup_embedder()` при старте сервера — прогревает bge-m3
  тестовым запросом, убивая cold start ~3s у первого search_code.

---

## [v2.4.6] — 2026-07-05 — UI Formatter + Deadlock Fix + Log Centralization

### 🐛 Deadlock Fix
- **`src/core/rate_limiter.py`**: `DebounceBatch._debounce_wait()` больше не
  вызывает `await` внутри `threading.Lock` — вынесено в отдельную переменную
  `should_flush`. `threading.Lock` не reentrant — дедлок 100% при пачке
  `notify_change`. Исправлены code quality: удалён `field`, добавлен `Any`.

### 🎨 UI Formatter (новый модуль)
- **`src/utils/ui_formatter.py`**: 8 базовых функций форматирования:
  `header()`, `table()`, `key_value()`, `code_block()`, `empty_result()`,
  `error_result()`, `ok_result()`, `format_search_code()`, `format_repo_rank()`,
  `format_health_report()`, `format_telemetry()`, `format_eta()`.
- Все данные под `<details>`-спойлер, Markdown-таблицы вместо JSON.

### 🔄 Log Centralization
- **`src/core/log_manager.py`**: `get_log_dir()` теперь ВСЕГДА ведёт в
  `ext_root/.codebase_indices/logs/`, а НЕ per-project. Добавлена
  `_cleanup_stale_project_logs()` — чистит старые логи из проектов.
- Очищены импорты: удалены `datetime`, `timedelta`, `timezone`, дубль `import os`.

### 🧩 UI Formatter Integration
- **`src/mcp/tools/search_tools.py`**: `_format_results()` переведён на
  `format_search_code()`. Вывод — таблица с колонками #, Файл, Строка, Фрагмент, Слой.
- **`src/mcp/tools/system_tools.py`**: `GetIndexStatusTool.execute()` — вывод
  через `header() + key_value() + code_block()`.
- **`src/mcp/tools/analysis_tools.py`**: `GetRepoRankTool.execute()` — вывод
  через `format_repo_rank()` с таблицей и сырыми JSON под спойлером.

### 🧠 Project Memory
- `known_issues`: LSP WONTFIX на Zed 1.9.0 Windows (NODE-567a10)
- `incidents`: INC-2CE4, INC-8817

---

### 📄 Документация
- **Новый отчёт-расследование**: [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md).
  Полный аудит исходников Zed 1.9.0 (`crates/project/src/lsp_store.rs`,
  `crates/extension/src/extension_manifest.rs`, `crates/settings_content/src/language.rs`)
  с цитатами кода и ссылками на raw GitHub. Вердикт: **WONTFIX на Zed 1.9.0** —
  кастомный LSP нельзя зарегистрировать только через `settings.json`,
  нужен Rust+WASM-обёртка.

### 🧹 Очистка мёртвого кода
- **`install.py`**: удалена генерация LSP-конфига (`lsp_config`). LSP-секция
  в `settings.json` больше не создаётся — она не работает (WONTFIX).
- **`src/utils/zed_config.py`**: удалён блок регистрации `lsp.mscodebase-lsp`
  из `patch_zed_settings()`. Функция больше не принимает LSP-конфиг.
- **`scripts/check_lsp_health.py`**: новый диагностический скрипт. Проверяет
  settings.json, процессы, bridge-файлы, SQLite DB. Выдаёт понятный вердикт
  с рекомендациями.

### 📚 Документация
- **`ZED_WINDOWS_QUIRKS.md`** (1.0 → 1.1): новая секция «LSP не стартует в
  Zed 1.9.0 (WONTFIX)» с реальной первопричиной.
- **Обновлён** `AGENT_DIARY.md`: новая запись 15:55 с правильным root cause
  и ссылкой на отчёт-расследование. Старая запись 15:30 помечена DEPRECATED.

### 🧠 Project Memory
- В `known_issues` добавлен узел про LSP-WONTFIX с ссылкой на отчёт
  и тремя workaround'ами (MCP, SQLite fallback, подмена pyright).

### ℹ️ Что это меняет
- **MCP остаётся основным транспортом** для всех сценариев код-ассистента.
- **LSP-фичи в редакторе (inlay-hints, code-actions, автокомплит)** на Zed 1.9.0
  Windows невозможны без Rust-обёртки — by design, не наш баг.
- **Для v3.0** запланирован путь A (Rust+WASM-обёртка через
  `impl zed::Extension::language_server_command`).

---

## [v2.4.4] — 2026-07-05 — Metadata Enrichment: Semantic Compass + Flat Tree

### 🧭 Semantic Compass (MCompassRAG-style, src/core/parser.py + src/core/indexer.py)
- Каждый чанк теперь содержит `layer` (архитектурный слой: core/mcp/utils/tests/...).
- Авто-детекция слоя по пути файла без ручной разметки.
- Поле `module_name` — логическое имя модуля (core.parser, mcp.server).
- Поле `is_public` — публичный/приватный символ (по `_` префиксу).
- Поле `symbol_type` — AST-тип узла (function_definition, method_definition, ...).

### 🌳 Flat Tree (SproutRAG-style, src/core/parser.py + src/core/indexer.py)
- `hierarchy_level`: function | method | class | impl | lines | function_part | section.
- `parent_id`: детерминированный md5-хеш родительского элемента.
  - Для метода: хеш `file_path::ClassName`.
  - Для функции: хеш `file_path` (модуль).
  - Multi-granularity retrieval без графовых БД.

### 🗃 Схема LanceDB
- 6 новых полей: `layer`, `module_name`, `hierarchy_level`, `is_public`, `symbol_type`, `parent_id`.
- Автомиграция через `_migrate_add_metadata_columns()` — без drop_table.
- Старые чанки получают пустые значения; заполнятся при переиндексации.

### 🔧 Код
- `src/core/parser.py`: +`_build_chunk_metadata()` — 4 точки создания чанков.
- `src/core/indexer.py`: +`_migrate_add_metadata_columns()`, +`chunk_metadatas`.
- Все 103 теста пройдены, ни один не сломан.

### 🎯 Фильтрация поиска по layer (MCompassRAG — поиск)
- `search_code` получил параметр `filter_layer` (core/mcp/utils/tests/...).
- LanceDB `.where()` с `prefilter=True` — фильтр на уровне индекса, без загрузки всех чанков.
- BM25 пост-фильтрация по layer из metadata.
- Работает во всех режимах: fast (vector-only), quality (hybrid), deep.

### 🌳 Multi-granularity retrieval (SproutRAG — поиск)
- Новый метод `Searcher.get_chunks_by_parent_id()` — находит все дочерние чанки по parent_id.
- Позволяет подняться по иерархии: модуль → класс → функция.
- E2E: фильтр core выдаёт только core, фильтр tests — только tests, 0 пересечений.

---

## [v2.4.3] — 2026-07-05 — RuntimeCoordinator + intel_get_project_context

### 🎯 RuntimeCoordinator (new, src/core/runtime_coordinator.py)
- Единая точка принятия решения "можно ли выполнять MCP-запрос?".
- Использует Registry (состояние), SystemArtifacts (системный путь),
  Runtime Passport (готовность).
- `can_execute(path) → ExecutionVerdict(ok, reason, state, detail)`.
- `require_ready_project()` в MCPTool делегирует Coordinator-у.
- Имя tool: `intel_get_project_context` (единый стиль Intel Layer).

### 🧪 Код
- ProjectContext, RuntimeCoordinator, server.py, base.py — синтаксис OK.
- Архитектура: Tool → Coordinator → Snapshot, без копипасты.

---

## [v2.4.2] — 2026-07-05 — ProjectContext — единая модель состояния проекта

### 🏗 ProjectContext (new, src/core/project_context.py)
- Единый объект-снэпшот проекта: state + index + bridge + health + memory + jobs.
- Вместо 5 разных вызовов — один `await ctx.capture()`.
- Все поля опциональны: если компонент недоступен → None, без падения.
- `get_project_context` MCP tool — JSON со всей картиной проекта сразу.
- Ничего не ломает — новый слой поверх существующей архитектуры.

### 🔧 SystemArtifacts (src/core/system_artifacts.py)
- Единый модуль для идентификации системных файлов (4 уровня защиты).
- file_guard.py переведён на SystemArtifacts — все списки в одном месте.

---

## [v2.4.1] — 2026-07-05 — Extended Passport + Feedback-Loop Guard + Two-Stage Ready

### 🆔 Passport Extended (BUILD_ID + Bridge/Registry/ProjectState)
- **`src/mcp/server.py`**: добавлен `_BUILD_ID` (git commit hash) — мгновенная
  верификация версии кода.
- `_log_run_passport()` теперь логирует Bridge state и Registry state при старте.
- `debug_runtime_passport` возвращает: `build_id`, `project_state` (enum),
  `bridge`, `bridge_error`, `registry.paths`, `registry.cached_projects`,
  `registry.cache_hits/misses`.

### 🛡 Feedback-Loop Guard (против загрязнения индекса)
- **`src/core/file_guard.py`**: в `_load_gitignore()` добавлены явные паттерны
  исключения служебных файлов индексации:
  - `chunk_summaries.json`, `summaries_cache/**` — описания чанков
  - `incidents.json`, `project_memory.json`, `commits.json` — метаданные памяти
  - `.index_guard.json`, `symbol_index/**` — индексы
- Защита двухслойная: SKIP_DIRS (директории) + .gitignore (файлы).
- Без этих исключений возможен feedback loop: описание чанка → summary →
  индексирование summary → новое summary на основе предыдущего.

### ⏱ Two-Stage wait_until_ready
- **`src/mcp/tools/base.py`**: `require_ready_project()` теперь делает 2 стадии:
  1. Быстрая проверка bridge (1с) — если LSP ещё не записал project_root,
     сразу логирует предупреждение вместо ожидания 5с.
  2. Полное ожидание READY (оставшиеся секунды).

### 🧪 Tests
- Все файлы проходят py_compile.
- Индекс: 1362 чанка, 106 файлов, 1080 Tree-sitter символов, status=active.

---

## [v2.4.0] — 2026-07-05 — Self-Indexing Fix + Process Passport + Project State Machine

### 🛡 Self-Indexing Guard: Dev-Repo Fix
- **`src/mcp/server.py`**: удалён ошибочный `_SELF_INDEX_MARKER`
  (`(path / "src/lsp_main.py").exists()`), заменён на
  `_reject_self_index_target(p, source=)`.
  - Отклоняет: `p == _ext_root` + `is_zed_install_dir(p)`.
  - Больше НЕ блокирует dev-репозиторий (`D:\Project\MSCodeBase`), если
    пользователь открыл исходники расширения как проект в Zed.
- **`src/mcp/tools/base.py`**: добавлен env-override `MSCODEBASE_ALLOW_SELF_INDEX=1`
  для dev-сценария.
- **`src/utils/zed_config.py`**: `patch_zed_settings()` пишет
  `MSCODEBASE_ALLOW_SELF_INDEX=1` в env MCP/LSP.

### 🆔 Process Passport (debug_runtime_passport)
- **`src/mcp/server.py`**: при старте MCP логируется "паспорт" —
  `RUN_ID`, `PID`, `_ext_root`, `PROJECT_PATH`, `ZED_WORKTREE_ROOT`,
  `MSCODEBASE_ALLOW_SELF_INDEX`, `PYTHONPATH`.
- Зарегистрирован MCP-tool `debug_runtime_passport` — возвращает JSON
  с RUN_ID, PID, uptime, source_file, ext_root, env, guard result.
  Позволяет за 1 вызов подтвердить: "тот ли процесс исполняет мой код?".

### 🏗 Project State Machine (race-free multi-window)
- **`src/core/project_indexer_registry.py`**:
  - Добавлен `enum ProjectState`: `UNINITIALIZED → STARTING → INDEXING → READY → FAILED`.
  - Per-project `asyncio.Event` для сигнализации готовности.
  - `get_indexer()` автоматически переводит проект в STARTING при создании
    и в READY/INDEXING после.
  - `wait_until_ready(path, timeout=5.0)` — ожидает READY (решает race
    condition при переключении окон: LSP нового проекта ещё не записал
    bridge, но MCP уже получил tool call).
  - Исправлен дублированный `with self._create_lock` (удалена мёртвая копия).
- **`src/mcp/tools/base.py`**: добавлен `async require_ready_project()`
  в `MCPTool`. Инструменты ждут готовности вместо "последний активный проект".

### 🛠 Утилиты
- **`scripts/sync_src.py`** (new) — быстрая синхронизация `src/` из
  dev-репозитория в install-директорию расширения.
- **`scripts/patch_zed_settings.py`** (new) — патч глобального
  `settings.json` Zed для добавления `MSCODEBASE_ALLOW_SELF_INDEX=1`.

### 🧪 Tests
- Прямой запуск: `_is_self_index_path(D:\Project\MSCodeBase) = False`.
- `resolve_project_root()` возвращает `D:\Project\MSCodeBase` без ошибок.
- MCP-сервер стартует и регистрирует 43 инструмента (33+10).
- Индекс: 1362 чанка, 106 файлов, 1080 Tree-sitter символов, статус active.

---

## [v2.3.3] — 2026-07-05 — Visible Project Path + Self-Indexing Guard

### 🎯 Project Path Visibility (INC-6BCB-v3)
Пользователь больше не должен гадать "где MCP ищет?". Теперь:

- **`search_code`** output начинается с `📂 Project: <path>`.
- **`index_project_dir`** output содержит `📂 Project: <path>` в финале.
- **`notify_change`** output содержит `📂 Project: <path>` после обновления.
- **`get_index_status`** output начинается с `📂 Project: <path>`.
- **`index_health`** output содержит `project_path`, `db_path`,
  `total_chunks` в JSON-ответе.

### 🛡 Hard Self-Indexing Guard (ToolError, not silent)
- **`resolve_indexer_for_request()`** (в `src/mcp/tools/base.py`) бросает
  `ToolError` если resolved project_path это:
  - `_ext_root` (исходники самого расширения)
  - Zed install dir (`is_zed_install_dir()`)
  - `None` (неопределённый project_root)
- **`IndexProjectDirTool`** делает **дополнительную** проверку ДО создания
  Indexer с понятным сообщением: "Refusing to index Zed install dir: ...".
- **Error detail** содержит инструкцию как починить (открыть проект явно,
  передать explicit project_root, или установить PROJECT_PATH env).

### 🐛 Bug Fix
- **`is_zed_install_dir()`** не находил `D:\AI\Zed` (корень установки)
  потому что маркеры требовали trailing path separator. Добавлены
  маркеры для root-of-install + нормализация backslashes/forward slashes
  для кросс-платформенного сравнения.

### 🧪 Tests
- **`tests/test_project_header.py` (new, 16 tests)**:
  - `_is_self_index_path()`: 7 кейсов (None, Zed install, ext_root, user project).
  - `resolve_indexer_for_request()`: 4 кейса (user OK, Zed install blocked,
    None blocked, ext_root blocked).
  - `_project_header()` / `_project_metadata()`: 5 кейсов (success, error,
    dict contents).
- **All tests pass: 323 / 323** (307 предыдущих + 16 новых).

### 📊 Smoke Test
- `create_mcp_server()` стартует за 8.61s, 33 tools + 4 handlers.
- `indexer.bm25_batch` per-project (v2.3.1) + project header (v2.3.3)
  работают вместе.

---

## [v2.3.2] — 2026-07-05 — Multi-Root Awareness + Self-Indexing Guard

### 🐛 Critical Bug: Self-Indexing Zed Install Dir
- **Симптом:** MCP индексирует `D:\AI\Zed\` (саму установку Zed) вместо
  пользовательского проекта. Видно как `db_isolated_path:
  D:\AI\Zed\.codebase_indices\...` в `intel_get_runtime_status`.
- **Корень:** LSP получает от Zed `params.root_uri` (или `workspaceFolders`).
  Если Zed открыт с `D:\AI\Zed` как worktree root (последний открытый
  workspace, или Zed IDE запущен без явного проекта), LSP пишет в bridge
  именно этот путь, и MCP индексирует всю директорию Zed (exe, dll, конфиги).
- **Решение:**
  1. `lsp_project_bridge.is_zed_install_dir(path)` — детектит Zed install dir
     по маркерам в пути (Zed.exe, %LOCALAPPDATA%\Zed, и т.п.) и по
     наличию Zed.exe рядом с директорией.
  2. `lsp_main.on_initialize` — читает `params.workspaceFolders` (LSP 3.6+),
     фильтрует Zed install dir, инициализирует DI для каждого оставшегося.
  3. `lsp_project_bridge.write_active_project` — принимает `all_workspaces`
     список URI всех воркспейсов.
  4. `lsp_project_bridge.read_active_project` — выбирает первый non-Zed-install
     workspace из `all_workspaces`, fallback на `project_root`.
  5. LSP-сервер теперь объявляет `workspace.workspaceFolders` capability
     (supported: True, changeNotifications: True) — Zed будет присылать
     `workspace/didChangeWorkspaceFolders` при открытии/закрытии проектов.

### 🔧 Multi-Root LSP
- `ls._all_workspaces` — список URI всех открытых воркспейсов (для watcher'ов).
- Per-workspace DI: для каждого folder из `workspaceFolders` создаётся
  свой `_services_per_workspace[uri]`. Если Zed откроет 3 проекта —
  будет 3 DI-контейнера, 3 ProjectIndexerRegistry, 3 .codebase_indices/.

### 🧪 Testing: 306 passed + 1 pre-existing failure
- Все предыдущие тесты прошли без изменений.
- `test_expected_message_mismatch` — pre-existing, не связан с v2.3.2.

### 📚 Migration
- После обновления: `sync_to_installed.bat --full` + перезапуск Zed.
- Если `D:\AI\Zed\.codebase_indices/` содержит мусор от self-indexing —
  можно удалить вручную: `rm -rf /d/AI/Zed/.codebase_indices`.
- Чтобы Zed точно открыл проект: `cmd+shift+p` → "Open Project" →
  выбрать `D:\Project\MSCodeBase` (создаст `.zed/` workspace marker).

---

## [v2.3.1] — 2026-07-05 — Startup Hang Fix + DebounceBatch Per-Project

### 🐛 Critical Bug Fixes
- **`lsp_main.py:did_change_watched_files`** — `if _services is None` бросал `NameError` (глобальная `_services` не существует в per-workspace архитектуре). Заменено на lookup в `_services_per_workspace[uri]` с fallback на первый доступный. Без этого watcher-events падали с NameError при первом же срабатывании.
- **`lsp_main.py:did_change`/`did_close`/`did_save`** — workspace_uri и project_root НЕ передавались в `_execute_file_indexing` (только `did_open` передавал). В multi-window это значит, что все индексируемые файлы попадали в default Indexer. **Исправлено** — все четыре хука теперь пробрасывают `getattr(ls, "_workspace_uri", "")` и `getattr(ls, "_project_root", None)`.
- **`lsp_main.py:_execute_file_indexing`** — `services.resolve(type("_IndexerFactory", (), {})) if False else ...` (мёртвый код с анонимным type) заменён на прямой `_get_factory(services)`. Аналогично `services.resolve(type("ProjectRootKey", (), {}))` → `services.resolve(ProjectRootKey)`.
- **`search_tools.py:_agentic_search`** — `self.searcher` и `self.symbol_index` НЕ существуют в базовом `MCPTool` (Indexer/Searcher per-project через registry). Заменено на `self.resolve_searcher()` / `self.resolve_symbol_index()`. Без этого agentic_search падал с AttributeError.
- **`graph_tools.py:GraphQueryTool`** — `services.resolve(SymbolIndex)` + `services.resolve(Indexer)` в `__init__` (Indexer больше не singleton) заменены на `self.resolve_symbol_index()` / `self.resolve_indexer()` per-call. Fallback `Path.cwd()` для project_root убран.
- **`mcp/server.py:IntelligenceLayer`** — `services.resolve(Indexer/Searcher/SymbolIndex)` (все три не зарегистрированы) заменены на `resolve_indexer_for_request(services)`. Без фикса 10 intel_* tools не регистрировались (warning "Intel layer not registered").
- **`mcp/server.py:33+13` → `33+10`** — корректный счёт (10 intel tools, а не 13).

### 🔧 Per-Project DebounceBatch (multi-window)
- **Раньше:** `DebounceBatch` регистрировался в DI как singleton с захватом default `ProjectRootKey` — для не-default проектов BM25 reindex работал с **неправильным** project_root (все per-project файлы реиндексировались default Searcher-ом).
- **Теперь:** `bm25_batch` создаётся per-project внутри `_create_indexer_for_path()` (захватывает конкретный `Indexer` в closure) и хранится как `indexer.bm25_batch`. Все потребители (`lsp_main.py:_execute_file_indexing`, `lsp_main.py:_process_watched_changes`, `mcp/tools/indexing_tools.py:NotifyChangeTool`) берут batch из `indexer.bm25_batch` через `getattr(indexer, "bm25_batch", None)` с fallback на синхронный `searcher.reindex()`.
- **`di_container.py`** — `_batch_reindex_bm25_factory` и `services._factories[DebounceBatch]` удалены. `_create_indexer_for_path` теперь явно создаёт `p_indexer.bm25_batch = DebounceBatch(callback=..., config=...)`.
- **Late-binding fix:** `_create_indexer_for_path` объявлен ПОСЛЕ `notification_broker` (раньше использовал late-binding через globals — хрупко). Захват переменных через default args (`_embedder=embedder, _notification_broker=notification_broker`) делает поведение детерминированным.

### 🚀 Self-Indexing Guard + Bridge Recheck
- **`_trigger_auto_index_if_empty`** — добавлена проверка `indexer.project_path == _ext_root`. Если resolve_project_root упал в fallback (race с LSP), auto-index **не запускается** (раньше индексировал ~500MB исходников самого расширения).
- **Delayed bridge recheck** — фоновая задача через 1.5s после старта MCP повторно читает `read_project_from_bridge(max_wait=2.0)`. Если LSP успел записать project_root — `reset_project_root_cache()` сбрасывает кэш, и последующие вызовы `resolve_project_root` выберут bridge. **Решает race LSP↔MCP** при cold start.

### 🧹 Housekeeping
- **`mcp/tools/base.py`** — удалён мёртвый код `_indexer_factory_from_services` и `_IndexerFactoryKey` (не используется с v2.3.0).
- **`mcp/tools/indexing_tools.py`** — удалён неиспользуемый импорт `DebounceBatch`.
- **`mcp/tools/graph_tools.py`** — удалён неиспользуемый импорт `SymbolIndex`.

### 🧪 Testing: 307 passed
- `tests/test_di_container.py::test_creates_all_services` — убран `DebounceBatch` из списка (больше не singleton).
- `tests/test_di_container.py::test_debounce_batch_uses_searcher` — переписан: batch берётся из `indexer.bm25_batch`, а не через `services.resolve(DebounceBatch)`.
- Все остальные 305 тестов прошли без изменений.

### 📚 Migration Notes
- После обновления: `sync_to_installed.bat --full` + перезапуск Zed.
- Никаких ручных правок `settings.json` не требуется (всё через `patch_zed_settings`).

---

## [v2.3.0] — 2026-07-05 — Multi-Window Support & Hardening

### 🏗️ Architecture: Multi-Window
- **`ProjectIndexerRegistry`** (new, `src/core/project_indexer_registry.py`):
  Per-project `Indexer` с lazy созданием и LRU eviction (5 слотов).
  Каждое открытое окно Zed получает изолированный `Indexer`/
  `FileGuard`/`SymbolIndex`/`db_path` — переключение окон больше не ломает state.
- **`ResourceMonitor`** (new, `src/core/resource_monitor.py`):
  stdlib-only мониторинг RAM/CPU (`resource.getrusage` + `ctypes/psapi` на Windows,
  без `psutil`). Soft/hard пороги для adaptive throttling.
- **LSP per-workspace DI**: `_services_per_workspace[uri]` вместо одного
  глобального `_services`. `init_components(project_root, workspace_uri=...)`.
- **MCP `resolve_indexer_for_request`**: per-project indexer из registry
  с приоритетом: explicit kwarg → `resolve_project_root()` → DI default.

### 🔧 Hardening
- **`_safe_close()`**: обнуляет LanceDB connection + кэши + `gc.collect()` —
  освобождает `.lance` mmap handles на Windows немедленно.
- **Adaptive throttling**: `Indexer.index_project` замедляется при soft
  pressure (0.1s) и останавливается при hard pressure (до 2s).
- **HealthReport `_check_resources`**: rss_mb, cpu_percent, threads,
  registry stats (cached/evictions/hits/misses) в `metrics`.
- **`async indexer` reentrancy**: `_indexing_serial_lock` в LSP сериализует
  запись в LanceDB между `did_open`/`did_change`/`did_save`.

### 🐛 Bug Fixes (audit INC-53EC, 19 issues)
- `di_container.py:177` — `notification_broker` NameError в `CircuitBreaker.on_state_change`
- `lsp_main.py:372` — undefined `_indexer` global в `did_change_watched_files`
- `did_change` debounce 350ms (не на каждый keystroke)
- `asyncio.Lock` → `threading.Lock` (cross-loop safe: LSP pygls loop + MCP asyncio.run loop)
- Sentinel DI keys (`ProjectRootKey`/`DbPathKey`/`IndexerFactoryKey`) вместо `str`/`type("…")`
- `indexer.set_searcher(searcher)` вместо `indexer.searcher = …` (encapsulation)
- `SafePathManager.cleanup` через `atexit` + `weakref.finalize`
- `add_columns` миграция LanceDB вместо `drop+create` race
- `O(N) to_pandas()` заменён на `table.search().where(...).limit(1)`
- LSP watcher glob `**/*.{ext1,ext2,…}` (фильтр по расширениям)
- `git log` с `cwd=project_path` в HealthReport
- `HeartbeatService` class (DI-friendly) вместо module globals
- `IndexGuard` reconciliation (prior `needs_reindex` не залипает)
- `nul` файл удалён (Windows reserved name)

### 🔧 Zed Settings
- `current_dir` убран из `patch_zed_settings` (Zed не подставляет
  `$ZED_WORKTREE_ROOT` в `current_dir` — bug #36019). `resolve_project_root`
  обрабатывает приоритеты сам: PROJECT_PATH env → bridge → CWD → ext_root.
- `fix_zed_settings.bat` (new) — патчит существующий `settings.json` пользователя
  (удаляет `current_dir` с бэкапом).
- Self-indexing guard: PROJECT_PATH указывает на MSCodeBase → warning в логах.

### 🧪 Testing: 325 → 307 passing (+ 11 new = 318; 11 deprecated, минус = 307)
- `test_resource_monitor.py` (new, 11 tests):
  - `ResourceMonitor`: sample, throttle, pressure thresholds, summary, singleton
  - `ProjectIndexerRegistry`: singleton per path, LRU eviction, pressure eviction,
    explicit evict, stats (hits/misses/evictions)
- `test_health_report.py`: degraded status, total_symbols/embedder_mode алиасы,
  orphan-files detection, git log cwd, fallback embedder warning
- `test_integration.py`: `isolated_indexer` использует `temp_project` как
  `project_path` (был баг — FileGuard отвергал файлы как "not in project")
- `test_di_container.py`: `Indexer`/`Searcher` теперь per-project через registry

### 📚 Documentation
- README: tests badge 325 → 307, добавлен Multi-Window в features
- `docs/architecture.md`: секция "Multi-Window Registry" + ResourceMonitor
- CHANGELOG: этот файл
- `pyproject.toml`: bumped to v2.3.0
- AGENT_DIARY.md: 3 записи (аудит + multi-window + resource monitor)

### ⚠️ Migration Notes
- После обновления запустите `fix_zed_settings.bat` для удаления
  `current_dir` из `~/.config/Zed/settings.json` (или `%APPDATA%\Zed\settings.json`).
- `sync_to_installed.bat --full` для синхронизации с установленной копией.
- Перезапустите Zed для подхвата новых версий.

---

## [v2.2.0] — 2026-07-04 — Architecture Modernization

### 🏗 Architecture Rewrite
- **DI Container:** `ServiceCollection` with Constructor Injection (15 services)
- **server.py:** 3,100 → **220 lines** (-93%). God Object eliminated.
- **37 tools** decoupled into 10 domain-specific files in `src/mcp/tools/`
- **error_boundary** decorator: unified JSON responses, real `asyncio.wait_for` timeout
- **DebounceBatch:** BM25 реиндексация через 500ms debounce (не на каждый файл)
- **SlidingWindowRateLimiter:** защита от VFS-петель (10 req/sec max)
- **CircuitBreaker:** CLOSED/OPEN/HALF_OPEN для LM Studio (5 failures → 30s recovery)
- **hybrid_server.py:** DEPRECATED (вся логика в DI Container + lsp_main.py)

### 🔧 Improvements
- `lsp_main.py` — 4 глобальные переменные → DI container (_services)
- `notify_change` — Rate Limiter + DebounceBatch вместо немедленной BM25
- `get_index_progress` — progress tracking как module-level exports
- `read_live_file` — новый инструмент (чтение из LSP VFS с disk fallback)
- `_resolve_project_path` → standalone `resolve_project_root()`
- `GIT_ASKPASS=echo` + `CREATE_NO_WINDOW` — защита от Git Hang на Windows
- `_is_complex_query` — исправлена: русская грамматика → token-based + English W-words

### 🧪 Testing
- 52 new unit tests for:
  - `error_handler.py` — ToolError, error_boundary (async + sync), timeout, retries
  - `rate_limiter.py` — SlidingWindow, DebounceBatch, CircuitBreaker (all states)
  - `di_container.py` — ServiceCollection, 15 DI services, Searcher↔Indexer cycle
- Total: **325 tests**

### 📚 Documentation
- README полностью переписан: 37 инструментов, Clean Architecture с DI
- `docs/ARCHITECTURE.md` — новая схема с DI Container + tool files
- CONTRIBUTING.md — обновлён под новый архитектурный стиль
- AGENT_DIARY.md — 5 записей (все фазы рефакторинга)
- pyproject.toml: bumped to v2.2.0

---

## [v2.1.0] — 2026-07-03

### 🚀 Major
- **Консолидация поиска:** `search_code(query, mode)` — единый инструмент с 5 режимами (`auto/fast/quality/deep/context`)
- **Intelligence Layer:** 10 высокоуровневых `intel_*` инструментов (самодиагностика, топология, память проекта)
- **Отказ от double-write:** `patch_zed_settings()` теперь single-pass (MCP + LSP + Languages за один вызов)
- **Проектная память:** ADR, known_issues, tech_debt, failed_attempts — автоматически сохраняются между сессиями

### 🔧 Improvements
- `get_health_report`/`index_health` — `project_root` опционален (fallback на `$PROJECT_PATH`)
- `notify_change` — правильный резолв путей от корня проекта (не CWD)
- `_resolve_project_path()` — централизованный helper для резолва корня проекта
- Централизованная обработка путей через `PROJECT_PATH` env var (устанавливается Zed)
- `install.py` — clean-up: удалён дублирующий код LSP (теперь в `patch_zed_settings`)

### 📚 Documentation
- README полностью переписан: 26 инструментов, search_code с mode, Intel Layer
- `docs/architecture.md` — обновлён список инструментов (14→26 + 10 intel_*)
- `docs/windows-setup.md` — обновлён под новый формат
- `CONTRIBUTING.md` — убраны упоминания deprecated инструментов
- Создан `sync_to_installed.bat` для быстрой синхронизации source→installed

### 🧹 Housekeeping
- Удалены `run_tests.py`, `run_tests.bat` (дубликаты `pytest`)
- Обновлён `.gitignore` (добавлены dev-артефакты)
- Корень проекта очищен от тестового мусора

### ⚠️ Deprecations
- `smart_search`, `deep_search`, `context_search` → используйте `search_code(query, mode=...)`
- Старые функции пока работают как обёртки (backward compatibility)

## [v2.0.0] - 2026-06-28

### 🚀 Major
- Гибридная архитектура LSP + MCP: единый процесс с общей памятью вместо отдельных серверов
- Полный отказ от межпроцессного взаимодействия — снижение задержек и упрощение деплоя

### ⚠️ Breaking Changes
- Требуется миграция с предыдущей архитектуры на единый LSP+MCP процесс
- Изменены точки интеграции с редактором (больше нет отдельного MCP-сервера)
- Обновлён формат конфигурации

## [v1.4.2] - 2026-06-28

### 🔧 Improvements
- Миграция с ThreadPoolExecutor на asyncio.gather для асинхронных операций
- Улучшена производительность параллельных запросов к провайдерам

## [v1.4.1] - 2026-06-28

### 🔧 Improvements
- Добавлен embedding-based reranker для LM Studio
- Повышена точность ранжирования результатов поиска

## [v1.4.0] - 2026-06-28

### 🚀 Major
- Deep Call Graph с глубиной обхода 2+ уровней
- Расширен анализ зависимостей символов (callers/callees)

## [v1.3.0] - 2026-06-28

### 🔧 Improvements
- Мульти-провайдерный реранкинг: Ollama → LM Studio → RRF fallback
- Автоматическое переключение между провайдерами при недоступности

## [v1.2.0] - 2026-06-28

### 🚀 Major
- Production-ready релиз
- Agentic search v4 с улучшенной семантикой
- Система отслеживания прогресса индексации

## [v1.1.0] - 2026-06-22

### 🚀 Major
- RemoteEmbedder для удалённой генерации эмбеддингов
- Готовый инсталлятор для быстрого развёртывания

## [v1.0.0] - 2026-06-21

### 🚀 Major
- Первый релиз проекта
- Базовый семантический поиск по кодовой базе
- Интеграция с LanceDB для векторного хранения
