# Known Issues & Technical Debt

> **Part of MSCodeBase Intelligence** | v3.2.3
> Честный реестр известных проблем и текущих ограничений.
> Синхронизировано с Project Memory (`intel_get_project_memory`): ADR-001, KI-001/002, TD-001..004.

---

## Recently Fixed (2026-07-12) — НЕ повторять, уже закрыто

| ID | Компонент | Симптом | Корень | Статус |
|----|-----------|---------|--------|--------|
| INC-58EA | indexer / remote_embedder / LanceDB | IVF_PQ/IVF_FLAT индекс не строился: "KMeans cannot train 1 centroids with 0 vectors". Все 3365 векторов были нулевыми (norm=0.0). | 1) `_init_onnx` грузил `model.onnx`, но файл — `model_quantized.onnx` → ONNX-сессия падала. 2) `index_project` при сбое embedder молча подменял векторы нулями → отравлял индекс. | ✅ Fixed |
| INC-9573 | intelligence_layer / symbol count | `intel_get_runtime_status` показывал `symbol_index_count: 0` после reindex, хотя `get_index_status` — 3221. | `_resolve_symbol_count` читал кэш через `get_stats()["total_symbols"]`; рабочий `get_index_status` использует живой `get_symbol_count()`. | ✅ Fixed |
| INC-0AA6 | intelligence_layer / job lifecycle | Job зависал на 80% Finalizing ~40с (символьная индексация Tree-sitter без таймаута). | `await future_symbols` без `asyncio.wait_for`. Добавлен таймаут 120с с graceful-завершением. | ✅ Fixed |

**Как проверено:** `embed_batch` даёт norm≈14 (реальные векторы); `create_index(IvfFlat)` строится на реальных данных; `_resolve_symbol_count` in-process возвращает 3221. Требуется перезапуск Zed для применения (extension copy обновлён).

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

---

*Последнее обновление: 2026-07-12*
