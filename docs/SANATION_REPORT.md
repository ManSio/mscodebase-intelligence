# Отчёт о санации исключений

**Дата:** 2026-07-14
**Режим:** APPLY
**Всего найдено:** 252
**Всего исправлено:** 252

## Изменённые файлы

| Файл | Найдено | Исправлено |
|------|---------|------------|
| src\core\autonomous_fix.py | 2 | 2 |
| src\core\code_health.py | 4 | 4 |
| src\core\commit_memory.py | 1 | 1 |
| src\core\error_handler.py | 2 | 2 |
| src\core\execution_contract.py | 2 | 2 |
| src\core\graph.py | 3 | 3 |
| src\core\graph_rag.py | 2 | 2 |
| src\core\indexing\index_guard.py | 7 | 7 |
| src\core\indexing\indexer.py | 31 | 31 |
| src\core\indexing\parser.py | 3 | 3 |
| src\core\indexing\project_indexer_registry.py | 11 | 11 |
| src\core\indexing\symbol_index.py | 2 | 2 |
| src\core\intelligence\health.py | 16 | 16 |
| src\core\intelligence\layer.py | 11 | 11 |
| src\core\intelligence\project_context.py | 3 | 3 |
| src\core\log_manager.py | 6 | 6 |
| src\core\lsp_client.py | 2 | 2 |
| src\core\lsp_project_bridge.py | 1 | 1 |
| src\core\modification_guard.py | 1 | 1 |
| src\core\multi_project_searcher.py | 2 | 2 |
| src\core\onnx_server.py | 1 | 1 |
| src\core\rate_limiter.py | 2 | 2 |
| src\core\route_extractor.py | 1 | 1 |
| src\core\runtime_coordinator.py | 4 | 4 |
| src\core\search\branch_aware_index.py | 4 | 4 |
| src\core\search\engine.py | 4 | 4 |
| src\core\search\graph_adapter.py | 1 | 1 |
| src\core\structural_search.py | 4 | 4 |
| src\core\task_queue.py | 4 | 4 |
| src\main.py | 2 | 2 |
| src\mcp\server.py | 32 | 32 |
| src\mcp\tools\analysis_tools.py | 1 | 1 |
| src\mcp\tools\base.py | 12 | 12 |
| src\mcp\tools\indexing_tools.py | 2 | 2 |
| src\mcp\tools\search_tools.py | 3 | 3 |
| src\mcp\tools\system_tools.py | 8 | 8 |
| src\mcp\tools\write_tools.py | 19 | 19 |
| src\providers\embedder\remote_embedder.py | 9 | 9 |
| src\providers\reranker\llama_runner.py | 22 | 22 |
| src\providers\reranker\multi_provider.py | 4 | 4 |
| src\utils\i18n.py | 1 | 1 |

## Пропущенные файлы

- src\__init__.py: no logger — skipping
- src\config\__init__.py: no logger — skipping
- src\config\settings.py: no logger — skipping
- src\core\__init__.py: no logger — skipping
- src\core\branch_aware_index.py: no logger — skipping
- src\core\chunk_summarizer.py: no logger — skipping
- src\core\config.py: no logger — skipping
- src\core\cross_project_deps.py: no logger — skipping
- src\core\cypher_engine.py: no logger — skipping
- src\core\extensions.py: no logger — skipping
- src\core\file_guard.py: no logger — skipping
- src\core\graph_adapter.py: no logger — skipping
- src\core\health_report.py: no logger — skipping
- src\core\index_guard.py: no logger — skipping
- src\core\indexer.py: no logger — skipping
- src\core\indexing\__init__.py: no logger — skipping
- src\core\indexing\resource_monitor.py: skipped (intentional fallback)
- src\core\intelligence\__init__.py: no logger — skipping
- src\core\intelligence_layer.py: no logger — skipping
- src\core\interfaces\__init__.py: no logger — skipping
- src\core\interfaces\embedder.py: no logger — skipping
- src\core\interfaces\reranker.py: no logger — skipping
- src\core\interfaces\searcher.py: no logger — skipping
- src\core\llama_runner.py: no logger — skipping
- src\core\parser.py: no logger — skipping
- src\core\passport.py: skipped (passport.py)
- src\core\platform_utils.py: no logger — skipping
- src\core\project_context.py: no logger — skipping
- src\core\project_indexer_registry.py: no logger — skipping
- src\core\remote_embedder.py: no logger — skipping
- src\core\reranker.py: no logger — skipping
- src\core\resource_monitor.py: skipped (intentional fallback)
- src\core\search\__init__.py: no logger — skipping
- src\core\searcher.py: no logger — skipping
- src\core\start_reranker_snippet.py: skipped (start_reranker_snippet.py)
- src\core\symbol_index.py: no logger — skipping
- src\mcp\__init__.py: no logger — skipping
- src\mcp\tools\__init__.py: no logger — skipping
- src\providers\embedder\__init__.py: no logger — skipping
- src\providers\reranker\__init__.py: no logger — skipping
- src\providers\search\__init__.py: no logger — skipping
- src\utils\__init__.py: no logger — skipping
- src\utils\ui_formatter.py: no logger — skipping

---
*Сгенерировано скриптом `scripts/sanitize_exceptions.py`*
