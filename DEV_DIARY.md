# DEV DIARY — MSCodeBase Intelligence

> Дневник инцидентов, экспериментов и архитектурных решений.
> Синхронизировано с `AGENT_DIARY.md` и `EXPERIMENTS_LOG.md`.

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
