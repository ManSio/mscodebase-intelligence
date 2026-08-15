# Corrected GOLD paths for E2E experiments
# Based on actual repository structure as of 2026-07-23

GOLD = {
    # Definition queries
    "where is hybrid_search defined": "src/core/search/engine.py",
    "Searcher class implementation": "src/core/search/engine.py",
    "DebounceBatch class": "src/core/rate_limiter.py",
    "RuntimeCoordinator": "src/core/runtime_coordinator.py",
    "ProjectContext snapshot": "src/core/runtime_coordinator.py",
    "LspClient process management": "src/core/lsp_client.py",
    "ModificationGuard decorator": "src/core/modification_guard.py",
    "SymbolIndex class": "src/core/indexing/symbol_index.py",
    "GraphAdapterPure": "src/core/search/graph_adapter.py",
    "ErrorBoundary implementation": "src/core/error_handler.py",
    "FTS5Mixin search": "src/core/search/fts5_mixin.py",
    "BM25 scoring algorithm": "src/core/search/bm25.py",
    "Reranker inference": "src/providers/reranker/search_result_reranker.py",
    "EmbeddingCache": "src/core/search/engine.py",
    "ProjectIndexerRegistry": "src/core/indexing/project_indexer_registry.py",

    # Architecture queries
    "how does the search pipeline work": "src/core/search/engine.py",
    "how is the index built": "src/core/indexing/indexer.py",
    "how does the rate limiter work": "src/core/rate_limiter.py",
    "how does the watchdog monitor health": "src/core/indexing/watchdog.py",
    "how does error handling work": "src/core/error_handler.py",
    "how does the MCP server start": "src/mcp/server.py",
    "how does file watching work": "src/core/indexing/watchdog.py",
    "how does the installer work": "install.py",
    "how does i18n work": "src/utils/i18n.py",
    "how does the sandbox execute code": "src/core/sandbox/executor.py",

    # Usage queries
    "who calls hybrid_search": "src/core/search/engine.py",
    "who uses LanceDB": "src/core/indexing/db_manager.py",
    "who imports the config": "src/config/settings.py",
    "who calls the reranker": "src/providers/reranker/search_result_reranker.py",
    "who uses asyncio locks": "src/core/runtime_coordinator.py",
    "who calls embedding_cache": "src/core/search/engine.py",
    "who uses the watchdog": "src/core/indexing/watchdog.py",
    "who calls notify_change": "src/core/indexing/indexer.py",
    "who imports error_handler": "src/core/error_handler.py",
    "who calls search_code": "src/mcp/tools/search_tools.py",

    # Navigation/Structure queries
    "what are the main layers of the project": "src/core/runtime_coordinator.py",
    "what is the entry point": "src/main.py",
    "what files are in core": "src/core/__init__.py",
    "what is the dependency graph": "src/core/indexing/db_manager.py",
    "what are the hotspots": "src/core/intelligence/layer.py",
    "what tests exist": "tests/test_searcher.py",
    "what is the project structure": "src/__init__.py",
    "what are the external dependencies": "src/mcp/server.py",
    "what database is used": "src/core/indexing/db_manager.py",
    "what models are loaded": "src/providers/embedder/remote_embedder.py",

    # Bug-related
    "where could a race condition happen": "src/core/rate_limiter.py",
    "where is memory managed": "src/core/intelligence/layer.py",
    "where are timeouts configured": "src/config/settings.py",
    "where is logging configured": "src/core/log_manager.py",
    "where are SQL queries built": "src/core/indexing/db_manager.py",
}

# Queries where gold file is outside scan scope or ambiguous - EXCLUDE from evaluation
EXCLUDED_QUERIES = [
    "what tests exist",  # tests/ not in scan scope
    "how does the installer work",  # install.py at root, not in src/
]

# Query categories for analysis
CATEGORIES = {
    "definition": list(range(0, 15)),
    "architecture": list(range(15, 25)),
    "usage": list(range(25, 35)),
    "navigation": list(range(35, 45)),
    "bug_related": list(range(45, 50)),
}