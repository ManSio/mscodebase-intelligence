# CHANGELOG

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
