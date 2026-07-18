# Known Issues & Technical Debt

> **Part of MSCodeBase Intelligence** | v3.3.0
> Честный реестр известных проблем и текущих ограничений.
> Синхронизировано с Project Memory (`intel_get_project_memory`): ADR-001, KI-001/002, TD-001..004.

---

## Recently Fixed (2026-07-17) — НЕ повторять, уже закрыто

| ID | Компонент | Симптом | Корень | Статус |
|----|-----------|---------|--------|--------|
| INC-VOCAB | remote_embedder / INT8 model | search_code возвращал мусор. Cosine similarity INT8 vs FP32 = -0.03. | `e5-base-v2-int8/model_quantized.onnx` сквантизирован из НЕВЕРНОЙ базовой модели: vocab=30522 (BERT-uncased) вместо 250002 (intfloat/e5-base-v2). Все эмбеддинги — мусор, маскировался BM25 в RRF. | ✅ Fixed: Смена модели на `multilingual-e5-small-int8` (384dim, vocab=250002, cos=1.0) |
| INC-BATCH | indexer | Скорость индексации 18-25 ch/s вместо ожидаемых 52 ch/s. | `_BATCH_SIZE=64` неоптимален для small INT8. Оптимум: batch=4 → 52 ch/s; batch=64 → 25 ch/s. | ✅ Fixed: `_BATCH_SIZE = 4` |
| INC-DIM | intelligence_layer | Хардкод `dimension: 768` в intelligence/layer.py, хотя модель 384-dim. | `embedding_dim` не обновлялся из модели, всегда брался из env (768). | ✅ Fixed: Авто-определение через `_lightweight_onnx_dim()` |
| INC-RACE | remote_embedder / OpenVINO | Спорадические нулевые векторы при многопоточном инференсе. | OpenVINO InferRequest не thread-safe. 2+ потока → "Infer Request is busy" → batch=0 → нули. | ✅ Fixed: Lock + single InferRequest + guard на shape[0]==0 |
| INC-DOCS | remote_embedder | Докстринг обещал "250-350 ch/s", реальная скорость 37-52 ch/s. | Комментарий остался от удалённой модели e5-base-v2 INT8. Новая модель (e5-small) медленнее. | ✅ Fixed: Обновлены все комментарии (строки 540, 588, 635, 650) |
| INC-INSTALL | install.py / download_model.py | install.py ставил `e5-base-v2-int8` (768dim, 265MB), а рантайм использовал `multilingual-e5-small-int8` (384dim, 113MB). | Маппинг модели в install.py не обновлялся при смене модели 17.07. | ✅ Fixed: slug → `multilingual-e5-small-int8`, HF → `keisuke-miyako/multilingual-e5-small-onnx-int8` |

**Guards (добавлены для предотвращения повторения):**
1. При скачивании INT8 модели — проверять `vocab_size` (должен быть 250002).
2. После реквантизации — проверять cosine similarity vs FP32 (должен быть >0.99).
3. Не доверять цифрам ch/s из докстринга — замерять при реальном `max_length=128`.
4. `_detect_model_dir()` авто-определяет `embedding_dim` из ONNX-метаданных.
5. `_download_prequantized()` для INT8: сохраняет `model_quantized.onnx` + скачивает `config.json`.

---

## Recently Fixed (2026-07-12)

| ID | Компонент | Симптом | Корень | Статус |
|----|-----------|---------|--------|--------|
| INC-58EA | indexer / remote_embedder / LanceDB | IVF_PQ/IVF_FLAT индекс не строился: "KMeans cannot train 1 centroids with 0 vectors". Все 3365 векторов были нулевыми (norm=0.0). | 1) `_init_onnx` грузил `model.onnx`, но файл — `model_quantized.onnx` → ONNX-сессия падала. 2) `index_project` при сбое embedder молча подменял векторы нулями → отравлял индекс. | ✅ Fixed |
| INC-9573 | intelligence_layer / symbol count | `intel_get_runtime_status` показывал `symbol_index_count: 0` после reindex, хотя `get_index_status` — 3221. | `_resolve_symbol_count` читал кэш через `get_stats()["total_symbols"]`; рабочий `get_index_status` использует живой `get_symbol_count()`. | ✅ Fixed |
| INC-0AA6 | intelligence_layer / job lifecycle | Job зависал на 80% Finalizing ~40с (символьная индексация Tree-sitter без таймаута). | `await future_symbols` без `asyncio.wait_for`. Добавлен таймаут 120с с graceful-завершением. | ✅ Fixed |

---

## P3 — Low

| ID | Статус | Описание | Компонент |
|----|--------|----------|-----------|
| ZED-36019 | ✅ Closed | **Index 0 files / 2535 chunks:** path resolution не работает — Zed не передаёт `ZED_WORKTREE_ROOT`. Исправлено: added `current_dir = $ZED_WORKTREE_ROOT` в extension.toml + SQLite multi-workspace fallback + delayed bridge recheck (3 fallback layers) | LSP bridge |
| DOC-TRANSLATION | ✅ Closed | docs/ru/* и docs/zh/* (кроме README) переведены машинно — native-верификация пройдена | Docs |
| SYM-INDEX-PARTIAL | ✅ Fixed | **SymbolIndex partial data**: `_parse_file_only` вызывал `pg.remove_file(rel_path)` напрямую вместо `self._symbol_index.remove_file(abs_path)` — path mismatch. PropertyGraph не удалял старые узлы, find_definitions() находил orphaned node. Фикс: замена на `self._symbol_index.remove_file(str(full_path))`. Добавлен invariant-test (20 тестов). | SymbolIndexAdapter / indexer |

## Tech Debt (из Project Memory)

| ID | Область | Описание | Приоритет |
|----|---------|----------|-----------|
| TD-001 | SymbolIndex | SymbolIndex реализован частично; CI не покрывает lance-based индекс. Архитектурно хрупко после INC-BAF5. | Medium |
| TD-002 | LanceDB IVF | ~~IVF_PQ не строился (0 vectors)~~ — **ИСПРАВЛЕНО (INC-58EA)**. После перезапуска Zed reindex даст реальные векторы + рабочий IVF. | Closed |
| TD-003 | Symbol count | ~~Рассинхрон symbols после reindex~~ — **ИСПРАВЛЕНО (INC-9573)**. | Closed |
| TD-004 | Job lifecycle | ~~Зависание Finalizing~~ — **ИСПРАВЛЕНО (INC-0AA6)**. | Closed |
| CI | Testing | Нет полного прогона тестов с lancedb/tree-sitter в GitHub Actions — создан `.github/workflows/test.yml` | High |

---

## Known Issues (из Project Memory, раздел known_issues)

| ID | Title | Workaround |
|----|-------|-----------|
| KI-001 | LSP bridge not synced on Windows (Zed bug #36019) | Self-indexing через SymbolIndex + SQLite. Нормализовано как warning. |
| KI-002 | MCP RAM ~1GB idle, peak 2.8GB under load — **НЕ утечка** | Пик под нагрузкой (reindex + орфан-процесс). Idle стабилен ~1GB. Рычаги: lazy ONNX load, `max_cached=1` в registry, LanceDB mmap. |
| KI-003 | Скорость индексации: 37-52 ch/s (не 250-350) | Реальный бенчмарк multilingual-e5-small-int8 при max_len=128. Batch=4 оптимален. Увеличение batch до 64 СНИЖАЕТ скорость до 25 ch/s. |

---

## Current Model Stack (2026-07-17)

| Модель | Размер | Dim | Vocab | Скорость | Статус |
|--------|--------|-----|-------|----------|--------|
| `multilingual-e5-small-int8` (keisuke-miyako) | 113 MB | 384 | 250002 | 37-52 ch/s | ✅ Активна |
| `multilingual-e5-small` (FP32, reference) | 448 MB | 384 | 250002 | — | Reference |
| `e5-base-v2` (FP32, reference) | 266 MB | 768 | 250002 | — | Reference (откат) |
| `reranker-bge-reranker-v2-m3` | 544 MB | 1024 | — | — | ✅ Активен |

---

*Последнее обновление: 2026-07-18*
