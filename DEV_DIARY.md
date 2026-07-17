# DEV DIARY — MSCodeBase Intelligence

> Дневник инцидентов, экспериментов и архитектурных решений.
> Синхронизировано с `AGENT_DIARY.md` и `EXPERIMENTS_LOG.md`.

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

**Статус:** ✅ Активно (ожидает перезагрузки MCP для вступления в силу)
