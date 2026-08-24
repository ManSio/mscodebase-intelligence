# ADR-0006: LSP-обогащение графа — compiler-accurate CALLS-рёбра + semantic tokens (capability-gated)

<!-- stale-ignore -->**Status:** ✅ Accepted (2026-08-19, по итогам живого эксперимента на basedpyright 1.39.10)
<!-- stale-ignore -->**Дата:** 2026-08-19
**Автор:** агент (по итогам `experiments/lsp/` — wire-probe на `lsprotocol==2025.0.0` + live-теста на реальном pyright-форке)

## Context

Граф MSCodeBase строится только из tree-sitter AST (455 файлов / 9630 символов). Tree-sitter даёт
синтаксическую структуру, но не «компиляторную точность»: кросс-файловые call-sites, разрешение
типов, встроенные символы типоведов (`print -> builtins.pyi`) — для него слепые зоны.

Живой эксперимент (2026-08-19) показал, что **реально** даёт LSP для Python:

| Фича | Спек 3.17 | pyright-fork | Live-статус |
|---|---|---|---|
| Call hierarchy (prepare→incoming/outgoing) | ✅ | ✅ | ✅ подтверждено |
| Semantic tokens (`/full`, delta) | ✅ | ✅ | ✅ подтверждено |
| Type hierarchy (3.17) | ✅ | ❌ не объявлен | ❌ для pyright |
| `moniker` (3.16, стабильный id) | ✅ | ❌ не объявлен | ❌ для pyright |
| Gate индексации `pyright/beginIndexing` | vendor | ❌ не наблюдался | ❌ для pyright |

Вывод: **«в спецификации есть feature» ≠ «сервер её реализует»**. На pyright-семействе граф может
реально получить **call hierarchy** (компиляторные кросс-файловые рёбра CALLS с точными range) и
**semantic tokens** (пакетное извлечение точных спанов/видов). Type hierarchy и moniker — отложены
до серверов, которые их объявят (dormant, capability-gated).

Дополнительно: `pygls==2.1.1` + `lsprotocol==2025.0.0` уже запинены в requirements, но не используются
(мост LSP удалён 2026-07-20) — LSP-машинерия уже в venv; используем только типы/схемы `lsprotocol`,
без тяжёлого pygls-фреймворка (его 2.x API — низкоуровневый транспорт, для тонкого клиента не нужен).

## Decision

1. **Тонкий LSP-клиент как READ-обогащение, не как источник правды.** `src/core/lsp_client.py`
   (DRAFT, capability-agnostic) — тонкий stdio-клиент поверх `Content-Length` JSON-RPC. Текущий
   tree-sitter-граф остаётся источником правды и работаeт всегда; LSP-обогащение — опциональный
   слой поверх (fallback-цепочка: LSP → tree-sitter, сервер недоступен → пропускаем).
2. **Capability-gating обязателен.** Клиент просит только объявленные провайдеры (`initialize` →
   `capabilities`). Для pyright активируются call hierarchy + semantic tokens; type hierarchy/moniker —
   используются автоматически там, где сервер их объявит (другие языки/серверы). Никаких
   hard-fail при отсутствии фичи.
3. **Маппинг в PropertyGraph/LanceDB (проект схемы):**
   - Call hierarchy → **рёбра `CALLS`**: `caller-(uri+selectionRange) → callee-(uri+selectionRange)`,
     проп `call_ranges[]` (абсолютные позиции call-site). Компиляторная точность гарантирует
     отсутствие ложных кандидатов от текстового grep.
   - Semantic tokens → **проп спанов на def-узле**: декод `[deltaLine,deltaStart,length,typeIdx,mods]`
     по `legend.tokenTypes` → точные `(line,char,length,type)` без повторного AST-обхода.
4. **Обработка провода перед записью (обязательные преобразования):**
   - **Position encoding:** LSP по умолчанию **UTF-16** (3.17 допускает utf-8/utf-32 negotiation) —
     конвертировать в внутренний off-индекс индекса до записи.
   - **URI-нормализация:** `file:///d%3A/...` (percent-encoded drive, наблюдалось на pyright) →
     канонический путь; маппинг обратно в `file:`-якорь узла.
   - CamelCase→snake_case полей (`selectionRange→selection_range`, `resultId→result_id`).
5. **Процессная модель:** per-language subprocess (`basedpyright-langserver --stdio`, Windows:
   `CREATE_NO_WINDOW` + `Popen` без `capture_output` в daemon-потоке — §6 AGENTS.md). Lifecycle:
   `start`→`initialize`→`initialized`→(опц. gate индексации через `$/progress` у серверов, что его
   шлют)→`shutdown`→`exit`. fallback на tree-sitter при отсутствии/падении сервера.
6. **Вне скоупа сейчас (явно НЕ мигрируем):** type hierarchy и moniker — dormant (нет на pyright);
   обратная запись/rename/move — другой контур (write-tools), требует свой ADR и modification-guard.

## Consequences

- **Плюс:** точные кросс-файловые CALLS-рёбра (включая typeshed: `print→builtins.pyi`) и точные спаны
  без AST-обхода; существующий tree-sitter-путь не ломается; zero-риск для горячего пути (обогащение
  офлайн/пакетами, не в hot path).
- **Минус:** LSP требует резидентного subprocess + память; pyright-форк даёт только 2 из 5 фич
  (type hierarchy/moniker недоступны на Python) — ожидание от интеграции честно ограничено.
- **Temporal:** `lsprotocol==2025.0.0` — 3.17-эра; пока спек 3.17/3.18 — ок. basedpyright — dev-tool
  (не в requirements), для проды нужен пининг сервера по версии (§5.19/§5.22).
- **Blast radius:** НИЗКИЙ для текущего шага (ADR + драфт, не подключён к индексатору). Сама
  интеграция (схема LanceDB + вызов в индексаторе) — ВЫСОКИЙ/CRITICAL: требует отдельного
  прототипа и миграции схемы, не делается в этом ADR.

## Impact

| Файл | Изменение |
|---|---|
| `src/core/lsp_client.py` | (уже создан, DRAFT) тонкий capability-gated LSP-клиент |
| `experiments/lsp/lsp_live_pyright.py` | живой вендор-тест (evidence этого ADR) |
| `experiments/lsp/lsp_client_demo.py` | демо: CALLS edges + декодер semantic tokens |
| `EXPERIMENTS_LOG.md` | 2 записи (wire-probe, live-test) |
| `tests/` + `src/core/...indexer` | **НЕ трогаются** — интеграция отложена отдельным шагом |

## Guard

Живой контроль corpus-«не ломаем»: обогащение не пишется в горячий путь индекса до отдельного
прототипа + `verify_clean_state.sh`. Capability-gating помечает недоступные фичи как skip, а не error.
