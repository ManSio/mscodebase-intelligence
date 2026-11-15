# ADR-0008: MCP Python SDK v1 → v2 (mcp 1.30 → 2.3, спецификация 2026-07-28)

- **Статус:** Proposed
- **Дата:** 2026-11-15
- **Контекст:** `mcp==1.30` закреплён в `requirements-lock.txt`. Линия 1.x переведена
  в maintenance mode (только security-фиксы), текущая ревизия спецификации — **2026-07-28**,
  а 1.30 умеет максимум **2025-11-25** (`mcp/types.py:27`).

## Как протокол версионируется

Версия MCP — дата (`YYYY-MM-DD`). «MCP 2.6» не существует; 2.x — версия пакета
`mcp` (PyPI), а не протокола. Проверено: `mcp` 2.3.0 отдаёт
`LATEST_PROTOCOL_VERSION = 2026-07-28`.

## Что уже измерено (Phase 1, worktree `chore/mcp-sdk-v2`)

| Проверка | Результат под mcp 2.3.0 |
|---|---|
| `from mcp.server.mcpserver import MCPServer` | есть; `mcp.server.fastmcp` удалён |
| Наш сервер создаётся | да: `MCPServer`, `name="MSCodebase Intelligence Server"` |
| `serverInfo.version` | **3.5.0** (было `1.30` — версия SDK) |
| Видимых инструментов | **17** (core-профиль), `_tool_manager` + `remove_tool` работают |
| Публичные методы v2 | `tool`, `add_tool`, `remove_tool`, `run_stdio_async`, `streamable_http_app(**kwargs)`, `session_manager`, `middleware`, `custom_route` |

## Что ломается (снятые частные API)

`MCPServer` 2.x **не имеет** `_mcp_server`; вместе с ним исчезли `request_handlers`,
`notification_handlers`, `request_context`. Под это подпадают 4 фичи:

| # | Фича | Файл | Сейчас под v2 |
|---|---|---|---|
| 1 | `isError` для нашего JSON-конверта ошибок | `src/mcp/error_results.py` | флаг не выставляется (guard логирует) |
| 2 | NotificationBroker на `InitializedNotification` | `src/mcp/server_factory.py:_register_notification_broker` | не регистрируется |
| 3 | Кастомные методы (heartbeat, dashboard, force-reindex) | `server_factory.py:start_heartbeat_monitor`, `_register_extension_handlers` | не регистрируются |
| 4 | Расширения через `request_handlers` | там же | не регистрируются |

Phase 1 их не ломает на 1.30 (импорт с fallback), но при поднятии пина они
деградируют — поэтому пин **не меняется**, пока Phase 2 не закрыт.

## План

**Phase 2 — заменить снятые поверхности публичными API v2.**

1. `isError`: возвращать `CallToolResult(is_error=True)` из границы ошибок
   (в v2 результат хендлера валидируется и `is_error` — легальное поле), а не
   перехватывать низкоуровневый `CallToolRequest`. Матрица: конверт ошибки →
   `is_error=true`, успешный ответ → `false`, текстовый payload не меняется.
2. Broker: привязка сессии через `middleware` или на первом `tools/call`
   (`Context.session` доступен в хендлере) вместо `notification_handlers`.
3. Кастомные методы (heartbeat/dashboard/force-reindex): либо `custom_route`
   (если поддерживается в 2.x), либо превратить в инструменты, либо удалить —
   решение владельца, потому что это меняет клиентскую поверхность.
4. Обновить `error_results`-guard и `tests/test_mcp_is_error.py` под новый контракт.

**Phase 3 — пины и приёмка.**

- `pyproject.toml`, `requirements.txt`, `requirements-lock.txt`: `mcp==2.3.0`
  + новые обязательные зависимости (`httpx2`, `mcp-types`, `opentelemetry-api`,
  `sse-starlette>=3`); `httpx` остаётся, потому что его импортирует наш код.
- Приёмка: `initialize` на 2025-06-18 и 2026-07-28, `server/discover`,
  `tools/list` = 17 и 69 (`full`), stdio + Streamable HTTP, 5 клиентских сниппетов,
  `tests/` целиком, `transport-equiv-e2e`.

## Откат

Одна строка: `mcp>=1.28,<2` в `requirements-lock.txt` + `pip install -r`.
Код Phase 1 совместим с 1.x (импорт с fallback), поэтому откат не требует
реверта кода — только пина.

## Открытые вопросы (нужно решение владельца)

1. Судьба кастомных методов (heartbeat/dashboard/force-reindex): переносить в
   инструменты (меняет поверхность и счётчик 69) или удалить?
2. Нужен ли `server/discover` в нашей реализации явно, или достаточно того, что
   SDK 2.x его даёт?
3. Разрешаем ли `sse-starlette` 2 → 3 (два мажора) в lock-файле.
