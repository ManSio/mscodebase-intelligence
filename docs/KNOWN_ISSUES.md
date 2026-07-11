# Known Issues & Technical Debt

> **Part of MSCodeBase Intelligence** | v2.7.1+
> Честный реестр известных проблем и текущих ограничений.

---

## P1 — High

| ID | Статус | Описание | Компонент | Фикс |
|----|--------|----------|-----------|------|
| OOM-001 | ✅ Fixed | **OOM-краш:** 2× llama-server (~2.7 GB) + MCP Python + Zed > 4 GB. Пиковая память 4345 MB, 8 срабатываний зависания `gpui::app` за 3 дня. | llama_runner.py | Idle-выгрузка реранкера (RERANKER_IDLE_TIMEOUT=300s) + watchdog total-RAM мониторинг |

## P3 — Low

| ID | Статус | Описание | Компонент |
|----|--------|----------|-----------|
| ZED-36019 | ⏳ Open | **Index 0 files / 2535 chunks:** path resolution не работает — Zed не передаёт `ZED_WORKTREE_ROOT` при некоторых сценариях запуска. Баг самого Zed, внешний фикс. | Zed LSP bridge |
| DOC-TRANSLATION | ⏳ Open | docs/ru/* и docs/zh/* (кроме README) переведены машинно — требуется верификация native-спикерами | Docs |

## Tech Debt

| Область | Описание | Приоритет |
|---------|----------|-----------|
| CI | Нет полного прогона тестов с lancedb/tree-sitter в GitHub Actions | High |
| LSP WONTFIX | Кастомный LSP не работает в Zed на Windows — архитектурное ограничение | Low |
| Rust/WASM draft | extension/ — заготовка Context Server Extension, заморожена | Low |

---

*Последнее обновление: 2026-07-11 — OOM-001 закрыт, ZED-36019 открыт*
