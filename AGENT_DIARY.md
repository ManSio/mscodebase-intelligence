# Agent Diary — MSCodeBase

## [2026-07-02 20:48] — [Type: Fix] — Архитектурные исправления MCP-инструментов

**Проблема:**
- get_health_report: таймаут >30 сек при запуске pytest (блокировал поток)
- get_file_history: "authorization channel closed" (пустой кэш + нет git fallback)
- get_bug_correlation: обрезанный вывод, коммиты не загружались
- Пути Windows: /d/Project → D:\d\Project (ломало CommitMemory)
- PYTHONPATH в settings.json ломал запуск сервера

**Решение:**
- Добавлен асинхронный запуск pytest через ThreadPoolExecutor (таймаут 35с)
- Добавлен git fallback в get_file_history при пустом кэше
- Добавлена принудительная загрузка коммитов в get_bug_correlation
- Исправлено разрешение Windows-путей (D:\d\ → D:\)
- Убран PYTHONPATH из настроек Zed (ломал запуск)
- Обновлена документация (AGENTS.md, AI_USAGE.md)

**Результат:**
- Все инструменты работают стабильно
- get_health_report: <5 сек (было >30 сек)
- Все 34 теста проходят
- Система готова к продакшену

**Инструменты:** search_code, get_symbol_info, get_health_report, get_file_history, get_bug_correlation, commit_memory
**Файлы:** src/core/health_report.py, src/core/commit_memory.py, src/mcp/server.py, src/utils/zed_config.py, AGENTS.md, .agents/AI_USAGE.md
**Статус:** ✅


## [2026-06-30 15:00] — [Type: Feature] — All Phases Complete — 33 MCP Tools

## [2026-06-30 14:30] — [Type: Feature] — Cross-project Dependency Graph

**Проблема:**
- Phase 4: Full GraphRAG — нужна реализация Cross-project dependency graph
- Анализ зависимостей между проектами в моно-репо

**Решение:**
- Создан `src/core/cross_project_deps.py` — CrossProjectDependencyGraph
  - build_dependency_graph() — строит directed graph из импортов
  - get_project_dependencies() — зависимости проекта (down/up/both)
  - find_shared_interfaces() — общие символы между проектами
  - find_circular_dependencies() — поиск циклов через DFS
  - get_dependency_path() — кратчайший путь через BFS
  - analyze_impact() — анализ влияния с risk_level
  - Поддержка 5 языков: Python (AST), JS/TS, Java/Kotlin, Go, Rust
- Добавлен MCP tool `cross_project_deps` (action: graph/deps/cycles/shared/impact/path)
- 26 тестов в test_cross_project_deps.py
- Исправлен RecursionError в _collect_source_files (os.walk вместо rglob)
- Исправлен бесконечный цикл build_dependency_graph ↔ find_circular_dependencies

**Инструменты:** search_code, get_symbol_info, read_file, edit_file, terminal
**Файлы:** src/core/cross_project_deps.py, src/mcp/server.py, tests/test_cross_project_deps.py, VISION.md
**Статус:** ✅
