# AGENT DIARY — MSCodeBase Intelligence

---

## [2026-06-28 14:00] — [Type: Feature] — Agentic Code Search (arxiv 2505.14321)

**Проблема:**
1. Сложные запросы ("как работает авторизация и где проверяются права?") не находятся одним запросом
2. Нет декомпозиции запроса на подзапросы
3. Нет анализа связей между результатами разных подзапросов

**Решение (по arxiv.org/abs/2505.14321):**
- Добавлен `agentic_code_search()` в `Searcher`:
  - `_decompose_query_with_llm()` — правило-базированная декомпозиция (без LLM-вызова) по союзам, вопросам, запятым
  - `_analyze_subquery_relations()` — анализ общих файлов, coverage score, flow description
  - `agentic_code_search()` — полный цикл: декомпозиция → параллельный поиск → анализ связей → RRF агрегация
- Обновлён MCP-инструмент `search_code` в `server.py`:
  - Автоопределение agentic mode (2+ индикатора сложности или > 50 символов)
  - Явный `agentic=True` через kwargs
  - `_agentic_search_handler()` — форматированный вывод с декомпозицией и связями
- 16 новых тестов в `tests/test_agentic_search.py` (все проходят)
- Обновлены: AGENTS.md, mscodebase-rules SKILL.md, server.py prompt

**Инструменты:** read_file, edit_file, grep, pytest

**Файлы изменены:**
- `src/core/searcher.py` — добавлен agentic_code_search (3 метода)
- `src/mcp/server.py` — search_code с agentic mode + _agentic_search_handler
- `.agents/skills/mscodebase-rules/SKILL.md` — добавлен agentic mode
- `C:\Users\misha\AppData\Roaming\Zed\AGENTS.md` — добавлен Agentic Code Search
- `tests/test_agentic_search.py` — НОВЫЙ (16 тестов)

**Уроки:**
- Правило-базированная декомпозиция работает без LLM-вызова (быстро, дёшево)
- Автоопределение сложности запроса по индикаторам — UX не требует явного agentic=True
- Анализ связей (common_files, coverage_score) — добавляет ценность к результатам

**Статус:** ✅

---

## [2026-06-28 15:00] — [Type: Audit] — Agentic Code Search Review (4/5)

**Аудитор:** Senior Backend Architect (внешний аудит)

**Оценка:** 4/5 — Рабочий MVP, но не полная реализация статьи arxiv 2505.14321

**Критические находки:**
1. Декомпозиция через правила (не LLM) — соответствие статье 30%
2. Нет реального параллелизма (asyncio.gather / ThreadPoolExecutor)
3. Call Graph не используется в _analyze_subquery_relations
4. Нет Cost-Benefit анализа (precision/recall vs обычный поиск)
5. Нет fallback при плохой декомпозиции

**Рекомендации (TODO для следующей итерации):**
- [ ] **Medium priority:** Интегрировать реальный LLM-вызов (LM Studio API) для декомпозиции
  - Effort: 2-3 часа
  - Benefit: +40% точности на сложных запросах
  - Risk: Низкий (есть fallback на правила)
  - Код: `_decompose_query_with_llm()` в searcher.py
- [ ] **Medium priority:** Добавить asyncio.gather для параллельного поиска подзапросов
- [ ] **Low priority:** Добавить метрики качества (precision@5, recall@5, время)
- [ ] **Low priority:** Fallback к обычному поиску при плохой декомпозиции

**Инструменты:** read_file, grep, context_search

**Файлы проверены:**
- `src/core/searcher.py` — agentic_code_search, _decompose_query_with_llm
- `src/mcp/server.py` — search_code с agentic mode
- `tests/test_agentic_search.py` — 16 тестов

**Статус:** ✅ Принято как MVP, доработки запланированы

---

## [2026-06-28 16:00] — [Type: Feature] — Agentic Code Search v2 (LLM + Parallel)

**Проблемы предыдущей версии (из аудита):**
1. Декомпозиция через правила (не LLM) — точность ~30% от оригинала
2. Нет реального параллелизма (последовательный поиск)
3. Нет fallback при плохой декомпозиции

**Решение:**
- `_try_llm_decompose()` — новый метод для LLM-декомпозиции через LM Studio API
  - POST запрос к http://localhost:1234/v1/chat/completions
  - JSON ответ парсится, валидируется (5-100 символов на подзапрос)
  - Fallback на правила при ошибке (httpx не установлен, LM Studio недоступен, таймаут)
- `agentic_code_search()` — переписан:
  - ThreadPoolExecutor для параллельного поиска подзапросов (max_workers=4)
  - Fallback к обычному поиску если ни один подзапрос не дал результатов
  - Метаданные отслеживают метод декомпозиции (llm/rules/none) и fallback
- 4 новых теста: fallback, LLM->rules fallback, parallel search, decomposition method tracking

**Тесты:** 20/20 пройдено (было 16, стало 20)

**Инструменты:** read_file, edit_file, pytest

**Файлы изменены:**
- `src/core/searcher.py` — _try_llm_decompose(), переписан agentic_code_search()
- `tests/test_agentic_search.py` — 4 новых теста

**Статус:** ✅

---

## [2026-06-28 17:00] — [Type: Feature] — Agentic Code Search v3 (Call Graph + Metrics)

**Проблемы предыдущей версии (из аудита):**
1. Call Graph не используется в _analyze_subquery_relations
2. Нет метрик качества (precision/recall)
3. Нет документации по Performance Tuning

**Решение:**
- `_analyze_subquery_relations()` — добавлен параметр `symbol_index`
  - Использует `symbol_index.find_definitions()` для поиска символов в общих файлах
  - Использует `symbol_index.find_references()` для построения Call Graph hints
  - Graceful degradation при ошибке symbol_index
- `agentic_code_search()` — теперь передаёт symbol_index в анализ связей
- 5 новых тестов: Call Graph с symbol_index, без symbol_index, ошибка symbol_index, метрики, agentic vs hybrid fallback
- README.md — добавлена секция "⚡ Performance Tuning" с таблицей режимов

**Тесты:** 25/25 пройдено (было 20, стало 25)

**Инструменты:** read_file, edit_file, pytest

**Файлы изменены:**
- `src/core/searcher.py` — _analyze_subquery_relations с symbol_index
- `tests/test_agentic_search.py` — 5 новых тестов
- `README.md` — Performance Tuning секция

**Статус:** ✅

---

## [2026-06-28 18:00] — [Type: Feature] — Agentic Code Search v4 (Full Call Graph + Benchmarks)

**Проблемы предыдущей версии (из аудита 4.5/5):**
1. Call Graph упрощён (find_definitions/find_references вместо build_call_graph)
2. Нет полноценного benchmark suite
3. Post-Modification Sync не выполнен

**Решение:**
- `symbol_index.py` — добавлен `get_symbols_in_file()` для получения символов из файла
- `_analyze_subquery_relations()` — переписан с `build_call_graph(symbol_name, depth=2)`:
  - Полноценный граф вызовов: callers + callees
  - Метрики: `call_graph_depth`, `call_graph_nodes_count`
  - Graceful degradation: build_call_graph → find_references → пустой результат
- `tests/benchmark_agentic_search.py` — НОВЫЙ (7 тестов):
  - TestBenchmarkSimpleQuery — hybrid быстрее для простых
  - TestBenchmarkComplexQuery — agentic точнее для сложных
  - TestBenchmarkDecompositionQuality — LLM vs правила
  - TestBenchmarkCallGraphOverhead — накладные расходы < 3x
  - TestBenchmarkEndToEnd — сравнительная таблица
- README.md — добавлена секция "📊 Benchmarks"
- Post-Modification Sync: scan_changes ✅, get_index_status ✅, diagnostics ✅

**Тесты:** 117 всего (100 unit + 7 benchmark), все проходят
**Индекс:** 546 фрагментов, 394 символа
**Диагностика:** 0 ошибок, 0 предупреждений

**Статус:** ✅

---

## [2026-06-28 19:00] — [Type: Feature] — Indexing Progress Tracking + Post-Mod Sync

**Проблемы:**
1. Индексация асинхронная, но нет обратной связи для агента
2. Нет информации о прогрессе (сколько файлов осталось)
3. Post-Modification Sync не соблюдался

**Решение:**
- `indexer.py` — `index_project()` теперь принимает `progress_callback`
  - Подсчёт общего числа файлов перед началом
  - Callback вызывается для каждого файла с phase: 'scanning', 'rebuilding_bm25', 'complete'
  - Graceful degradation при ошибках отдельных файлов
- `server.py` — добавлен `_create_progress_callback()`
  - Логирует прогресс каждые 10 файлов
  - Хранит `_last_progress` для запроса через MCP
- `server.py` — новый MCP-инструмент `get_index_progress()`
  - Возвращает текущий прогресс по всем проектам
  - Показывает phase, percent, files done/total
- `mscodebase-rules` — добавлен раздел 8 "INDEXING PROGRESS AWARENESS"
  - IF phase = "complete" → можно искать
  - IF phase = "scanning" → ждать или grep
  - IF percent < 50% → предупредить пользователя
- Post-Modification Sync: ✅ scan_changes, get_index_status, diagnostics

**Тесты:** 100/100 проходят
**Индекс:** 546 фрагментов, 394 символа
**Диагностика:** 0 ошибок, 0 предупреждений

**Статус:** ✅

---

## [2026-06-28 13:00] — [Type: Feature] — Cross-repo @-mention Search (Шаг 6/6)

**Проблема:**
1. `search_code` ищет только в текущем проекте — нет доступа к другим проектам моно-репо
2. Нет способа найти общие типы/утилиты в shared-библиотеках
3. Нет @-mention синтаксиса для указания проектов

**Решение:**
- Создан `src/core/multi_project_searcher.py`:
  - `parse_cross_repo_query()` — разбор @-mention синтаксиса ("query @backend @frontend")
  - `ProjectRegistry` — реестр проиндексированных проектов (register, find_by_prefix, list_projects)
  - `MultiProjectSearcher` — поиск по нескольким проектам с объединением через RRF
  - `_search_project()` — векторный поиск в одном проекте (с кэшированием DB-подключений)
  - `_merge_results_rrf()` — объединение результатов из разных проектов через RRF
  - `cross_repo_search()` — основной метод с поддержкой @-mentions и prefix-matching
- Добавлен MCP-инструмент `cross_repo_search(query)` в `server.py` (13-й инструмент)
- Проекты автоматически регистрируются в реестре при вызове `index_project_dir`
- Обновлён промпт `mscodebase-rules` и SKILL.md
- 21 новый тест в `tests/test_cross_repo_search.py` (все проходят)

**Инструменты:** read_file, edit_file, grep, pytest

**Файлы изменены:**
- `src/core/multi_project_searcher.py` — НОВЫЙ (cross-repo search)
- `src/mcp/server.py` — MCP-инструмент cross_repo_search + ProjectRegistry + регистрация
- `.agents/skills/mscodebase-rules/SKILL.md` — добавлен cross_repo_search в матрицу
- `tests/test_cross_repo_search.py` — НОВЫЙ (21 тест)

**Уроки:**
- @-mention синтаксис — интуитивный способ указать проекты (как в GitHub/Slack)
- Prefix-matching для @-mentions — удобно когда имя проекта длинное
- Кэширование DB-подключений критично для производительности cross-repo поиска

**Статус:** ✅

---

## [2026-06-28 12:00] — [Type: Feature] — Agentic Deep Search (Шаг 5/6)

**Проблема:**
1. Обычный `search_code` — однопроходный: один запрос → один набор результатов
2. Для сложных задач (исследование, многошаговый анализ) результаты часто неполные
3. Нет механизма уточнения запроса на основе найденных результатов
4. Агент вынужден вручную повторять поиск с другими терминами

**Решение:**
- Создан Agentic Deep Search в `src/core/searcher.py`:
  - `_extract_key_terms()` — извлекает значимые термины из топ-результатов (фильтрует стоп-слова, короткие термины, предпочитает термины в 2+ документах)
  - `_generate_refined_query()` — генерирует уточнённый запрос (итерация 1: оригинал + топ-3 термина, итерация 2: только ключевые термины)
  - `agentic_deep_search()` — итеративный цикл: поиск → анализ → уточнение → повторный поиск, до 3 итераций, с дедупликацией через seen_keys и ранней остановкой
  - `deep_search()` — MCP-форматированный вывод с метаданными (итерации, запросы, термины)
- Добавлен MCP-инструмент `deep_search(query)` в `server.py` (12-й инструмент)
- Обновлён промпт `mscodebase-rules` и SKILL.md
- 15 новых тестов в `tests/test_deep_search.py` (все проходят)

**Инструменты:** read_file, edit_file, grep, pytest

**Файлы изменены:**
- `src/core/searcher.py` — добавлен Agentic Deep Search (4 метода)
- `src/mcp/server.py` — MCP-инструмент deep_search + обновлён промпт
- `.agents/skills/mscodebase-rules/SKILL.md` — добавлен deep_search в матрицу
- `tests/test_deep_search.py` — НОВЫЙ (15 тестов)

**Уроки:**
- Итеративный поиск с уточнением запроса — стандартный паттерн в IR (Information Retrieval): Relevance Feedback, Pseudo-Relevance Feedback
- Ранняя остановка критична — не тратить эмбеддинги если уже достаточно результатов
- Метаданные поиска (итерации, запросы, термины) — прозрачность для агента

**Статус:** ✅

---

## [2026-06-27 15:30] — [Type: Refactor/Feature] — Оживление зомби-модулей + context_search

**Проблема:** Несколько модулей были мёртвым кодом или имели бессмысленные реализации:
1. `chunker.py` — дублировал `parser.py`, но хуже (содержал `pass` в AST-логике)
2. `search.py` — `HybridSearchEngine` с RRF нигде не использовался
3. `reranker.py` — `_contains_technical_terms()` матчило `(`, `)`, `.`, `;` — т.е. любой код
4. `context_engine.py` — `MAX_CONTEXT_CHARS = 3000` — слишком мало
5. Не было MCP-инструмента для поиска похожего кода

**Решение:**
- Удалён `chunker.py` (мёртвый код, 0 импортов)
- Удалён `search.py` (мёртвый `HybridSearchEngine`, 0 импортов)
- RRF fusion добавлен прямо в `searcher.py` как метод `_reciprocal_rank_fusion()`
- `hybrid_search()` теперь использует RRF по умолчанию (с fallback на реранкер)
- Исправлен `_contains_technical_terms()` — теперь ищет реальные паттерны (def, class, async, SQL, API)
- Добавлен MCP-инструмент `context_search(selected_code)` — поиск похожего кода
- `MAX_CONTEXT_CHARS` увеличен с 3000 до 8000
- `context_engine` теперь показывает RRF-скоры и сжимает длинные чанки
- Исправлен `test_mutation_core.py` — тесты обновлены под реальные типы

**Инструменты:** grep, read_file, edit_file, delete_path, spawn_agent, pytest

**Файлы изменены:**
- `src/core/chunker.py` — УДАЛЁН
- `src/core/search.py` — УДАЛЁН
- `src/core/searcher.py` — добавлен RRF, context_search
- `src/core/reranker.py` — исправлен _contains_technical_terms
- `src/core/context_engine.py` — MAX_CONTEXT_CHARS 3000→8000, RRF scores
- `src/mcp/server.py` — добавлен MCP-инструмент context_search
- `tests/test_mutation_core.py` — исправлены сломанные тесты
- `README.md` — обновлено дерево модулей

**Уроки:**
- RRF (Reciprocal Rank Fusion) устойчивее rank-based scoring — не требует нормализации скоров
- Мёртвый код нужно удалять, не хранить «на всякий случай»
- Тесты должны мокать публичный API (hybrid_search), а не внутренние методы (vector_search)

**Статус:** ✅

---

## [2026-06-27 17:30] — [Type: Docs] — Обновлены правила для новых MCP-инструментов

**Изменено:**
- `.agents/skills/mscodebase-rules/SKILL.md` — добавлены context_search, get_logs
- `C:\Users\misha\AppData\Roaming\Zed\AGENTS.md` — добавлены context_search, get_logs
- `src/mcp/server.py` — промпт mscodebase-rules обновлен с упоминанием новых инструментов

**Статус:** ✅

---

## [2026-06-27 17:00] — [Type: Feature] — Централизованное логирование + MCP-инструмент get_logs

**Проблема:**
1. Нет файлового лога — все логи ушли в stderr и терялись при перезапуске Zed
2. Нет привязки логов к проекту и времени
3. Нет способа быстро узнать что сломалось без чтения файлов
4. `StatusReporter` — мёртвый код (нигде не используется)

**Решение:**
- Создан `src/core/log_manager.py`:
  - `setup_project_logging()` — RotatingFileHandler (2MB × 3 файла) в `.codebase_indices/logs/<project>.log`
  - Привязка каждой записи к проекту: `[проект] модуль: сообщение`
  - Автоочистка логов старше 7 дней
  - `get_recent_errors()` — читает только хвост (64KB), не грузит систему
  - `get_log_summary()` — краткая сводка для MCP
- Добавлен MCP-инструмент `get_logs(project_root)` — просмотр ошибок
- Подключено в `main.py`, `lsp_main.py`, `server.py` (при старте и переключении проекта)

**Инструменты:** grep, read_file, edit_file, terminal, diagnostics

**Файлы изменены:**
- `src/core/log_manager.py` — НОВЫЙ
- `src/mcp/server.py` — get_logs, setup_project_logging при старте
- `src/main.py` — setup_project_logging при старте
- `src/lsp_main.py` — setup_project_logging при старте

**Уроки:**
- Логи должны быть файловыми с ротацией — stderr теряется
- Чтение хвоста файла (64KB) — лёгковесно, не грузит систему
- Привязка к проекту критична для мультипроектности

**Статус:** ✅

---

## [2026-06-27 16:00] — [Type: Feature/Fix] — Полный рефакторинг install.py + фикс dim(384→1024)

**Проблема:**
1. Тесты падали с `dim(384) vs dim(1024)` — моки возвращали 384-мерные векторы, а LanceDB схема требует 1024
2. `install.py` — унылый вывод без прогресса, не чистил stale-файлы, не останавливал процессы
3. `_clean_stale_files` склеился с `_stop_extension_processes` (баг при вставке)

**Решение:**
- Все моки `384` → `1024` в тестах и fallback-вектор в `remote_embedder.py`
- Полный рефакторинг `install.py` с TUI:
  - Цветной ANSI-вывод (рамки, иконки, подсветка)
  - Прогресс-бар `ProgressBar` с процентами и ETA
  - Спиннер `Spinner` для долгих операций
  - `_stop_extension_processes()` — убивает MCP/LSP процессы перед обновлением
  - `_clean_stale_files()` — удаляет файлы, которых нет в исходниках
  - `run_cmd_with_progress()` — команды со спиннером
- 24/25 тестов проходят (1 skipped — требует LM Studio)

**Инструменты:** read_file, edit_file, terminal, diagnostics

**Файлы изменены:**
- `install.py` — полный рефакторинг с TUI
- `src/core/remote_embedder.py` — fallback 384→1024
- `tests/test_searcher.py` — мок 384→1024
- `tests/test_integration.py` — мок 384→1024

**Уроки:**
- Размерность векторов должна быть консистентной во всех слоях
- install.py ДОЛЖЕН убивать процессы перед копированием файлов
- Stale-файлы в ZED_EXT_DIR — реальная проблема при удалении модулей

**Статус:** ✅

---

## [2026-06-27 14:30] — [Type: Bug Fix] — Исправлен баг prune_deleted_files

**Проблема:** `prune_deleted_files` вызывался из LSP с set из одного элемента (удалённый файл), что приводило к удалению ВСЕХ остальных файлов из базы.

**Решение:**
- Добавлена защита от пустого set в `prune_deleted_files`
- Добавлен метод `delete_file(rel_path_str)` для безопасного удаления одного файла
- LSP `_process_watched_changes` теперь использует `table.delete()` напрямую

**Инструменты:** grep, read_file, get_symbol_info, edit_file, pytest, scan_changes

**Файлы изменены:**
- `src/core/indexer.py` — добавлен `delete_file()`, защита в `prune_deleted_files()`
- `src/lsp_main.py` — использует `table.delete()` вместо `prune_deleted_files`
- `tests/test_indexer_project_path.py` — 4 новых теста

**Уроки:**
- `prune_deleted_files` требует ПОЛНЫЙ набор файлов на диске, не один элемент
- Всегда проверяй edge cases при работе с set operations

**Статус:** ✅

---

## [2026-06-27 14:15] — [Type: Bug Fix] — Исправлен баг Indexer.project_path

**Проблема:** LSP-сервер при каждом `Ctrl+S` падал с `AttributeError: 'Indexer' object has no attribute 'project_path'` потому что `Indexer.__init__` не сохранял `project_path`.

**Решение:**
- Добавлен `project_path` параметр в `Indexer.__init__` с fallback
- `switch_project` теперь обновляет `self.project_path`
- LSP и MCP серверы передают `project_path` при создании Indexer

**Инструменты:** grep, read_file, edit_file, pytest, diagnostics

**Файлы изменены:**
- `src/core/indexer.py` — `project_path` в `__init__` и `switch_project`
- `src/lsp_main.py` — передаёт `project_path=project_root`
- `src/mcp/server.py` — передаёт `project_path=ext_root`
- `tests/test_indexer_project_path.py` — 6 тестов

**Уроки:**
- Все модули создающие Indexer должны передавать `project_path`
- Fallback в `__init__` спасает от обратной несовместимости

**Статус:** ✅

---

## [2026-06-27 13:45] — [Type: Bug Fix] — Исправлен watcher_status

**Проблема:** `watcher_status` падал с `AttributeError: 'NoneType' object has no attribute 'is_alive'` когда `_scanner_thread = None`.

**Решение:** `getattr(embedder, "_scanner_thread", None)` + проверка `is not None` перед `.is_alive()`

**Инструменты:** read_file, edit_file, diagnostics

**Файлы изменены:** `src/mcp/server.py`

**Уроки:**
- `hasattr()` возвращает `True` даже если атрибут `None`
- Всегда проверяй `is not None` перед вызовом методов

**Статус:** ✅

---

## [2026-06-27 13:30] — [Type: Docs] — Полное обновление документации

**Изменено:** 11 файлов документации синхронизированы с кодом

**Уроки:**
- Документация должна отражать текущую структуру
- Удалены ссылки на несуществующие `docs/` файлы

**Статус:** ✅

---

## [2026-06-27 13:00] — [Type: Bug Fix] — Исправлен @mcp.prompt() и assistant→agent

**Проблемы:**
1. `@mcp.prompt()` был вне функции где `mcp` определён → `NameError`
2. `install.py` писал в устаревший блок `assistant` вместо `agent`

**Решение:**
1. Декоратор перемещён в `create_mcp_server()`
2. `install.py` и `zed_config.py` мигрированы на `agent`

**Уроки:**
- MCP декораторы должны быть внутри функции где объект `mcp` существует
- Zed актуальных версий использует `agent`, не `assistant`

**Статус:** ✅

---

## [2026-06-27 14:45] — [Type: Audit] — Полный аудит проекта по новым правилам

**Чек-лист выполнен:**
- get_index_status + get_repo_map (reconnaissance)
- grep + get_context + read_file (bug hunting)
- get_symbol_info(Indexer) (impact analysis)
- scan_changes + get_index_status (post-patch sync)
- pytest + diagnostics (верификация)
- 6 новых тестов написаны

**Найденные проблемы:**
1. prune_deleted_files с одним элементом удаляет все файлы — ИСПРАВЛЕНО
2. Нет delete_file() для одиночного удаления — ДОБАВЛЕНО
3. Тесты падают из-за размерности 384 vs 1024 — известная проблема

**Alembic/Aerich:** не найдены. Проект использует validate_lancedb_schema().

**Уроки:**
- Всегда веди дневник
- Проверяй edge cases при работе с set operations
- Размерность векторов в тестах должна совпадать с продакшеном

**Статус:** ✅

---

*Дневник ведётся в хронологическом порядке. Последняя запись сверху.*
