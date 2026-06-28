# CHANGELOG

## [2.0.0] — 2026-06-28

### 🚀 Major: Hybrid LSP + MCP Architecture

**Problem:**
- Separate LSP and MCP processes caused WinError 5 (file lock conflicts) on Windows
- `didSave` arrives before physical disk write (Windows I/O buffering)
- AI edits to closed files not detected by LSP
- watchdog.py couldn't detect changes in memory buffers

**Solution:**
- **Single-process architecture**: LSP (stdio) + MCP (HTTP/SSE) in one Python process
- **In-Memory Indexing**: Reads from LSP VFS (`document.source`) instead of disk
- **Full Document Sync**: Receives complete file content via `didChange` events
- **AI Edit Detection**: Catches `didOpen`/`didChange`/`didClose` for background edits
- **No file lock conflicts**: Single process accesses LanceDB

**New Files:**
- `src/hybrid_server.py` — Hybrid LSP + MCP server
- `.zed/settings.json` — Project-level Zed configuration

**Configuration Changes:**
- MCP now runs via HTTP/SSE on `http://127.0.0.1:8765/sse` (not stdio)
- LSP uses `hybrid_server.py` entry point
- Recommended: `autosave: "on_focus_change"` in Zed settings

**Technical Details:**
- LSP events: `didOpen`, `didChange`, `didSave`, `didClose`, `didChangeWatchedFiles`
- MCP server: FastMCP with SSE transport
- SharedIndexer: single LanceDB instance for both LSP and MCP
- Cold start: automatic full indexing on LSP initialization

**Migration:**
1. Update `.zed/settings.json` (see README)
2. Restart Zed
3. Old `lsp_main.py` and `mcp/server.py` kept for reference

**Breaking Changes:**
- Entry point changed from `lsp_main.py` to `hybrid_server.py`
- MCP URL changed from stdio to `http://127.0.0.1:8765/sse`
- Requires Zed restart after update

---

## [1.4.2] — 2026-06-28

### 🚀 Major: Async Migration (ThreadPoolExecutor → asyncio.gather)

**Problem:**
- `agentic_code_search` used `ThreadPoolExecutor` (4 OS threads)
- `Embedder.embed_batch()` used synchronous `httpx.post()` (blocking)
- Mixed sync/async code caused complexity

**Solution:**
- `Embedder.embed_batch_async()` — async version with `httpx.AsyncClient`
- `Searcher.hybrid_search_async()` — fully async hybrid search
- `Searcher.agentic_code_search_async()` — uses `asyncio.gather` (zero threads!)
- `_apply_multi_reranker_async()` — native async reranker
- Backward compatible: sync wrappers use `asyncio.run()` when no loop running

**Performance:**
- 0 OS threads for parallel subquery search (was 4)
- Native async I/O for embeddings and reranking
- ~8MB memory savings from eliminated thread stacks

**Tests:**
- All 25 agentic search tests updated for async mocks
- 72 total tests passing

---

## [1.4.1] — 2026-06-28

### 🔧 Fix: Embedding-based Reranker for LM Studio Compatibility

**Problem:**
- LM Studio has no native `/v1/rerank` endpoint
- LM Studio only loads embedding models (no LLM Instruct models)
- `input` parameter format caused "Expected array, received object" errors

**Solution:**
- Added `_embedding_rerank()` method using cosine similarity
- Works with any embedding model (BGE-M3, Nomic, etc.)
- Fixed `input` format: now strictly `list[str]` (JSON array)
- Added `_check_llm_available()` to detect Instruct models
- Priority: Embedding rerank → LLM rerank → RRF fallback

**Tests:**
- 5 new tests for embedding rerank (cosine similarity, fallback, edge cases)
- Total: 25 reranker tests (all passing)

---

## [1.4.0] — 2026-06-28

### 🚀 Major Release — Deep Call Graph (Depth 2+)

**New Features:**
- **Bidirectional Call Graph** (`src/core/symbol_index.py`):
  - BFS-based graph traversal with configurable depth (1-5)
  - `build_call_graph()` now finds both callers and callees at depth 2+
  - Cycle detection to prevent infinite loops
  - `get_call_chain()` for upstream/downstream traversal
  - `get_symbol_context()` enriched with calls info
- **Call Extraction** (`src/core/parser.py`):
  - `extract_calls()` method extracts function invocations from AST
  - Supports: simple calls, method calls (obj.method()), scoped (module::func)
  - `add_references()` in SymbolIndex for storing call relationships
- **Integration** — `index_project()` now extracts calls during indexing
- **Tests** — 22 new unit tests in `tests/test_symbol_index_call_graph.py`

### 📊 Test Coverage
- **153 unit tests** + **7 benchmark tests** = **160 total**

---

## [1.3.0] — 2026-06-28

### 🚀 Major Release — Multi-Provider Reranking

**New Features:**
- **Multi-Provider Reranker** (`src/core/reranker.py`) — `MultiProviderReranker` class:
  - Auto-detects Ollama (`:11434`) and LM Studio (`:1234`) via async ping (0.5s timeout)
  - Batch reranking: all chunks in one LLM request (800 char truncation per chunk)
  - Strict JSON response via `response_format={"type": "json_object"}`
  - 4-level JSON parser: pure → markdown → regex → individual objects
  - Priority: Ollama → LM Studio → transparent RRF fallback
  - Full fault tolerance: timeouts, ConnectError, malformed JSON all caught
- **Integration** — `searcher.py` now calls reranker after RRF in `hybrid_search` and `agentic_code_search`
- **Tests** — 20 new unit tests in `tests/test_reranker.py` covering all providers and edge cases

### 🔧 Improvements
- `reranker.py` — Complete rewrite: ONNX removed, pure `httpx`-based LLM inference
- `searcher.py` — Lazy sync initialization of reranker via `asyncio.run` + `ThreadPoolExecutor`
- `requirements.txt` / `pyproject.toml` — Removed `onnxruntime` and `transformers`

### 📊 Test Coverage
- **131 unit tests** + **7 benchmark tests** = **138 total**
- All reranker tests passing (20/20)

### 📚 Documentation
- README.md — Added reranking section, OLLAMA_URL env var, updated architecture diagram
- ARCHITECTURE.md — New section 8: Multi-Provider Reranker architecture

### 🧹 Cleanup
- Removed heavy binary dependencies: `onnxruntime>=1.16.0`, `transformers>=4.36.0`
- Extension is now lightweight — only `httpx` for network inference

---

## [1.2.0] — 2026-06-28

### 🚀 Major Release — Production Ready

**New Features:**
- **Agentic Code Search v4** — Full LLM decomposition via LM Studio API with ThreadPoolExecutor parallel search and Call Graph analysis
- **Indexing Progress Tracking** — Real-time progress callback system with `get_index_progress()` MCP tool
- **Cross-repo @-mention Search** — Multi-project search with RRF aggregation
- **Agentic Deep Search** — Iterative query refinement with key term extraction
- **Context Search** — Find similar code by embedding selected fragment
- **Structural Search** — 13 AST patterns (class_inheritance, function_with_decorator, async_function, etc.)
- **Centralized Logging** — File-based logs with rotation (2MB × 3) and auto-cleanup

### 🔧 Improvements
- `install.py` — Cross-platform venv paths (Windows/Linux/macOS), error handling, Zed IDE presence check
- `remote_embedder.py` — Auto-scanner for LM Studio/Ollama availability with fallback cascade
- `indexer.py` — Progress callback support, graceful error handling per file
- `searcher.py` — LLM decomposition with rules fallback, parallel search via ThreadPoolExecutor

### 📊 Test Coverage
- **111 unit tests** + **7 benchmark tests** = **118 total**
- All tests passing

### 📚 Documentation
- Complete README with Quick Start, Architecture, Performance Tuning
- ARCHITECTURE.md with data flow diagrams and module descriptions
- SKILL.md with tool selection matrix (14 tools)
- TESTING.md with real test commands

### 🧹 Cleanup
- Removed dead modules: `chunker.py`, `search.py`
- Removed unused dependencies: `chromadb`, `watchdog`, `psutil`, `requests`, `tqdm`
- Consolidated documentation (removed PROJECT_DOCS.md, CODE_OF_CONDUCT.md, AI_PROMPT.md)

---

## [1.1.0] — 2026-06-22

### Добавлено
- Режим работы через **RemoteEmbedder** — векторизация кода через LM Studio
- **Оркестратор потоков** — защита от повторного запуска индексации
- Установщик (`install.py`) с копированием расширения в Zed

### Исправлено
- `@mcp.prompt()` перемещён внутрь `create_mcp_server()`
- `system_prompt` записывается в `"agent"` вместо `"assistant"`

---

## [1.0.0] — 2026-06-21

- Первый релиз. ONNX-векторизация (BAAI/bge-m3), LanceDB, инкрементальная индексация, MCP-инструменты.
