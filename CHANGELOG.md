# CHANGELOG

## [1.2.0] — 2026-06-28

### � Major Release — Production Ready

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

### � Cleanup
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
