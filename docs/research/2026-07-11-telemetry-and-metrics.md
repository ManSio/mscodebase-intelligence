# Telemetry & Metrics — MSCodeBase v3.0

> Сводка телеметрии и метрик системы, собранная 11 июля 2026.
> Период: 2026-07-05 — 2026-07-11 (6 снапшотов)

---

## 1. 📊 ЭВОЛЮЦИЯ МЕТРИК (All Time)

| Дата | Chunks | Файлы | Символы | RAM | LLM Ping | Provider |
|------|--------|-------|---------|-----|----------|----------|
| 2026-07-05 | 1515 | 108 | — | 185 MB | **797ms** | llama_cpp |
| 2026-07-07 | 0 | 0 | — | 167 MB | 3094ms | — |
| 2026-07-08 | 211 | 0 | — | 172 MB | 11941ms ⚠️ | llama_cpp |
| 2026-07-09 | 211 | 0 | — | 151 MB | 3082ms | llama_cpp |
| 2026-07-10 | 211 | 0 | — | 151 MB | 4819ms | llama_cpp |
| **2026-07-11** | **2917** 🏆 | **169** 🏆 | **1424** | **311 MB** | **286ms** 🏆 | llama_cpp |

### Ключевые изменения за период:

| Метрика | 2026-07-05 | 2026-07-11 | Δ |
|---------|-----------|-----------|----|
| **LLM Ping** | 797ms | **286ms** | **-64%** 🟢 |
| **Batch10** | — | **357ms** | 🆕 |
| **Throughput** | — | **1401 tok/s** | 🆕 |
| **RAM** | 185 MB | 311 MB | +68% 🟡 |
| **Chunks** | 1515 | **2917** | **+93%** 🟢 |
| **Файлы** | 108 | **169** | **+56%** 🟢 |

---

## 2. 🛠 PER-TOOL МЕТРИКИ (Session Snapshot)

Собрано: **19 вызовов инструментов** за сессию аудита.

| Инструмент | Вызовов | Ошибок | Min (ms) | Avg (ms) | Max (ms) | P95 (ms) |
|-----------|---------|--------|----------|----------|----------|----------|
| `search_code` | 7 | 0 | 279 | **2077** | 3406 | 3106 |
| `rename_symbol` | 5 | 0 | 1547 | **2180** | 3699 | 2396 |
| `get_health_report` | 1 | 0 | 32626 ⚠️ | 32626 | 32626 | 32626 |
| `notify_change` | 1 | 0 | 3577 | 3577 | 3577 | 3577 |
| `get_symbol_info` | 1 | 0 | 1530 | 1530 | 1530 | 1530 |
| `impact_analysis` | 1 | 0 | 1558 | 1558 | 1558 | 1558 |
| `get_index_status` | 2 | 0 | 240 | 240 | 240 | 240 |
| `get_index_progress` | 1 | 0 | 214 | 214 | 214 | 214 |
| `structural_search` | 1 | 0 | 34 | 34 | 34 | 34 |
| `ack_impact` | 1 | 0 | 1 ⚡ | 1 | 1 | 1 |
| `get_bug_correlation` | 1 | 0 | 3 ⚡ | 3 | 3 | 3 |
| `get_hotspots` | 1 | 0 | 1 ⚡ | 1 | 1 | 1 |
| `get_runtime_counters` | 1 | 0 | — | — | — | — |
| `intel_get_project_context` | 1 | 0 | 441 | 441 | 441 | 441 |
| `intel_get_telemetry` | 2 | 0 | 50 | 50 | 50 | 50 |
| `intel_get_runtime_status` | 1 | 0 | 150 | 150 | 150 | 150 |
| `intel_code_topology` | 1 | 0 | 50 | 50 | 50 | 50 |
| `intel_execution_timeline` | 1 | 0 | 30 | 30 | 30 | 30 |
| `intel_tool_health` | 1 | 0 | 30 | 30 | 30 | 30 |
| `intel_get_project_memory` | 2 | 0 | 100 | 100 | 100 | 100 |
| `intel_explain_project_state` | 1 | 0 | 100 | 100 | 100 | 100 |
| `intel_get_hotspots` | 1 | 0 | 50 | 50 | 50 | 50 |

### ⚡ Топ самых быстрых (≤50ms)

1. `ack_impact` — **1ms**
2. `get_hotspots` — **1ms**
3. `get_bug_correlation` — **3ms**
4. `intel_execution_timeline` — **30ms**
5. `intel_tool_health` — **30ms**
6. `structural_search` — **34ms**
7. `intel_get_hotspots` — **50ms**
8. `intel_get_telemetry` — **50ms**
9. `intel_code_topology` — **50ms**

### 🐢 Топ самых медленных (≥1000ms)

1. `get_health_report` — **32626ms** ⚠️ (исправлен timeout 30→15s)
2. `rename_symbol` (avg) — **2180ms** (включает LSP fallback)
3. `search_code` (avg) — **2077ms** (зависит от режима)
4. `impact_analysis` — **1558ms**
5. `get_symbol_info` — **1530ms**
6. `notify_change` — **3577ms** ⚠️ (один вызов, мало данных)

---

## 3. 🔍 SEARCH_CODE ПО РЕЖИМАМ

| Режим | Query | Результаты | Время | Качество |
|-------|-------|-----------|-------|----------|
| `fast` | `class Indexer` | 3 | **299ms** | Точное совпадение |
| `fast` | `def move_chunks_metadata` | 3 | **290ms** | Точное совпадение |
| `fast` | `def _resolve_symbol_count` | 3 | **279ms** | Точное совпадение |
| `quality` | rename symbol across project files | 3 | **1886ms** | Reranked |
| `quality` | embedder provider class gemini llama | 5 | **343ms** ⚡ | Reranked |
| `deep` | google gemini ai integration | 5 | **~1900ms** | Agentic multi-pass |
| `deep` | indexer rename file path without re-embedding | 3 | **~1900ms** | Agentic multi-pass |
| `context` | def apply_file_move | 3 | **~500ms** | Code similarity |

### Среднее время по режиму:

| Режим | Среднее | Мин | Макс |
|-------|---------|-----|------|
| `fast` | **289ms** | 279ms | 299ms |
| `quality` | **1114ms** | 343ms | 1886ms |
| `deep` | **~1900ms** | ~1900ms | ~1900ms |
| `context` | **~500ms** | ~500ms | ~500ms |

---

## 4. 🔬 ТЕСТЫ (74/74 PASS)

| Файл | Тестов | Время | Покрытие |
|------|--------|-------|----------|
| `tests/test_move_chunks.py` | 28 | 1.81s | Meta-patching: apply_file_move, move_chunks_metadata, _infer_module_name, _infer_layer, BM25 reset, file_guard |
| `tests/test_modification_guard.py` | 13 | 0.10s | Guard: ack_impact, @modification_guard deny/allow, TTL expiry, hot file detection |
| `tests/test_write_tools.py` | 33 | 3.63s | Write: rename_symbol, move_symbol, safe_delete, replace_symbol, insert_before/after |
| **Total** | **74** | **5.54s** | **100% прохождение** |

### Тестовая архитектура:
```
tests/
├── test_move_chunks.py        — 28 тестов на мета-патчинг LanceDB
├── test_modification_guard.py  — 13 тестов на модификационный гард
├── test_write_tools.py        — 33 теста на write инструменты
├── conftest.py                 — фикстуры (mock_indexer и др.)
└── benchmark_agentic_search.py — бенчмарки
```

---

## 5. 💻 РЕСУРСЫ СИСТЕМЫ — ПОЛНЫЙ РАСКЛАД

### 5.1 Память по компонентам (честно, не «311 МБ» одной строкой)

| Компонент | idle (простой) | под нагрузкой | пик (индексация) | Примечание |
|-----------|---------------|---------------|------------------|------------|
| **Python MCP** (main процесс) | **~147 MB** | **~150 MB** | **~150 MB** | стриминг, не копит |
| **llama embedder** (bge-m3) | ~440 MB (mmap) | ~440 MB | **~878 MB** | mmap-файл модели, растёт при батчинге |
| **llama reranker** (bge-reranker) | **0 MB** (выгружен) | ~440 MB | ~440 MB | авто-выгрузка через 5 мин idle |
| **Python второй процесс** | **0.6 MB** | — | — | zombie от deadlock (починен) |
| **ИТОГО система** | **~147 MB** (MCP) | **~590 MB** (+embedder) | **~1,028 MB** (MCP+оба llama) |

### 5.2 Динамика памяти по сценариям

```
Простой (idle):
  Python MCP ─ 147 MB
  ─────────────────────
  Всего:       147 MB   (reranker выгружен по таймауту)

Поиск (search_code):
  Python MCP ─ 150 MB
  + embedder  ─ 440 MB (mmap, разделяемый)
  + reranker  ─ 440 MB (поднимается по запросу)
  ─────────────────────
  Всего:      ~1,030 MB  (~590 MB физической, остальное mmap)

Индексация (intel_trigger_reindex):
  Python MCP ─ 150 MB
  + embedder  ─ 878 MB  (батчинг, временные буферы)
  + reranker  ─ 0 MB   (не используется при индексации)
  GPU: 99% ───────────────
  Всего:      ~1,028 MB  (из них 440 MB mmap — файл модели)
```

### 5.3 Почему Диспетчер задач показывает меньше

| Метрика | Наше значение | Диспетчер задач | Разница | Причина |
|---------|--------------|-----------------|---------|---------|
| MCP idle | 311 MB (RSS peak) | **147 MB** (Working Set) | -164 MB | Windows вытеснил неиспользуемые страницы в paged pool |
| embedder | 440 MB (mmap file) | **440 MB** (читает из mmap) | 0 | mmap-файл считается полностью выделенным, но физически не занят |
| 2-й Python | 0.6 MB | **0.6 MB** | 0 | zombie-процесс от deadlock до фикса |

### Остальные метрики

| Метрика | idle | поиск | индексация |
|---------|------|-------|-----------|
| **CPU** | 0.0% | ~20% | ~60-99% (GPU 99%) |
| **Threads** | 8 | 8 | 8 |
| **LLM Ping** | — | 286ms | — |
| **Throughput** | — | 1401 tok/s | 12 chunks/s |

### Реестр Runtime:

| Проверка | Статус | Детали |
|----------|--------|--------|
| `can_execute` | ✅ 6/6 ready | 0 blocked |
| `bridge` | ❌ Not synced | Windows — ожидаемо |
| `lsp_client` | ✅ 505 LOC | Чистый stdlib, zero dependencies |
| `file_guard` | ✅ Active | Self-index protection |
| `self_index_guard` | ✅ False | Пути проекта ≠ расширения |
| `ZED_WORKTREE_ROOT` | ⚠️ null | SQLite fallback active |

---

## 6. ⏱ ETA PREDICTOR

| Параметр | Значение |
|----------|----------|
| **Total measurements** | 15 |
| **Learned ops** | 10/8 |
| **Operations with data** | rename_symbol, search_code, notify_change, get_index_status, get_symbol_info |

---

## 7. 🔴 HEALTH REPORT (до исправления)

При последнем запуске `get_health_report`:
- ⏱ Время: **32.6s** ⚠️
- Общий статус: **degraded**
- **Ошибок:** 0
- **Предупреждения:**
  1. Директория логов не существует
  2. **156 orphan files** в индексе
  3. Git операция превысила таймаут 30s
- **Орфан файлы очищены:** 0 (до переиндексации)

**После фикса:** timeout снижен с 30s→15s. Переиндексация запущена (Job: cb3f238d).

---

## 8. 🔥 ХОТСПОТЫ (Highest Bug Ratio)

| Файл | Bug Ratio | Баги/Коммиты | Риск |
|------|-----------|-------------|------|
| `src/core/onnx_server.py` | **1.0** | 3/3 | 🔴 Critical |
| `src/core/remote_embedder.py` | **0.82** | 18/22 | 🔴 High |
| `docs/en/CHANGELOG.md` | 0.75 | 3/4 | 🟡 High |
| `src/core/intelligence_layer.py` | 0.71 | 5/7 | 🟡 High |
| `install.py` | 0.67 | 10/15 | 🟡 High |
| `src/core/parser.py` | 0.67 | 2/3 | 🟡 High |
| `src/core/indexer.py` | **0.6** | 3/5 | 🟡 Medium |

---

## 9. 📈 ЭВОЛЮЦИЯ ЧЕРЕЗ КОММИТЫ

Последние 5 коммитов (все ManSio):

| Дата | Хэш | Изменение |
|------|-----|-----------|
| 2026-07-10 | `66c64dd0` | Fix: EMBEDDING_PROVIDER=auto now allows llama.cpp check |
| 2026-07-10 | `968d8b89` | FIX: _preload_onnx_delayed now checks llama.cpp before loading ONNX |
| 2026-07-10 | `d641f191` | Fix: embed_batch now checks llama.cpp even in ONNX mode |
| 2026-07-10 | `b9ed8f8b` | CRITICAL FIX: breaker fallback=True causes scanner to think LM Studio is up |
| 2026-07-09 | `6f8b5ef4` | Fix: scanner now detects llama.cpp provider (was missing) |

---

## 10. 🧬 RUNTIME PASSPORT

| Параметр | Значение |
|----------|----------|
| **RUN_ID** | `15f9ee310247` |
| **BUILD_ID** | `e7777440a372` |
| **PID** | `14412` |
| **Started** | `2026-07-11T19:21:09.802981` |
| **Uptime** | `1496.6s` |
| **Source** | `D:\Project\MSCodeBase\src\mcp\server.py` |
| **User** | `misha` |
| **CWD** | `D:\Project\MSCodeBase` |
| **Ext Root** | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` |

---

*Generated: 2026-07-11*  
*Tools: intel_get_telemetry, debug_runtime_passport, get_runtime_counters, diagnostics, pytest*
