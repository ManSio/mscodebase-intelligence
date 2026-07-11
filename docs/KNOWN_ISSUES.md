# Known Issues & Technical Debt

> **Part of MSCodeBase Intelligence** | v2.7.1+
> Честный реестр известных проблем и текущих ограничений.

---

## P3 — Low

| ID | Статус | Описание | Компонент |
|----|--------|----------|-----------|
| ZED-36019 | ✅ Closed | **Index 0 files / 2535 chunks:** path resolution не работает — Zed не передаёт `ZED_WORKTREE_ROOT`. Исправлено: added `current_dir = $ZED_WORKTREE_ROOT` в extension.toml + SQLite multi-workspace fallback + delayed bridge recheck (3 fallback layers) | LSP bridge |
| DOC-TRANSLATION | ✅ Closed | docs/ru/* и docs/zh/* (кроме README) переведены машинно — native-верификация пройдена | Docs |

## Tech Debt

| Область | Описание | Приоритет |
|---------|----------|-----------|
| CI | Нет полного прогона тестов с lancedb/tree-sitter в GitHub Actions — создан `.github/workflows/test.yml` | High |

---

*Последнее обновление: 2026-07-11 — все открытые закрыты*
