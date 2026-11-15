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

## Риски на три шага вперёд (что выстрелит позже, если не заложить сейчас)

1. **Lock-дрейф.** mcp 2.3 поднимает полы зависимостей: `pydantic>=2.12`,
   `sse-starlette>=3`, `pywin32>=311`, плюс новые обязательные `httpx2`,
   `mcp-types` (точный пин `==` версии SDK), `opentelemetry-api`.
   Гейт `scripts/check_lock_drift.sh` сравнивает три файла — обновлять их надо
   одной правкой, иначе коммит красный ещё до тестов.
2. **`httpx` ≠ `httpx2`.** Наш код (`llama_runner`, `remote_embedder`,
   `onnx_client`) импортирует `httpx`; SDK 2.x его больше не приносит.
   `httpx` остаётся нашим прямым пином, а объекты, передаваемые в SDK
   (`http_client=`, `auth=`), обязаны быть `httpx2` — иначе тихая деградация
   (server-initiated сообщения перестают приходить) вместо исключения.
3. **Streamable HTTP: сессии живут 30 минут простоя** (`session_idle_timeout`),
   после чего клиент получает 404 и должен заново инициализироваться. Для
   remote/VPS это изменение контракта: либо документируем, либо ставим
   `session_idle_timeout=None` осознанно (и платим памятью).
4. **Ошибки хендлеров больше не превращаются в `is_error=true`.**
   Наш конверт (`error_boundary`) отдаётся текстом; без явного
   `CallToolResult(is_error=True)` клиент увидит успех. Это тихий регресс
   контракта для агента — поэтому `tests/test_mcp_is_error.py` должен остаться
   краснеющим, а не быть ослабленным.
5. **Кастомные JSON-RPC методы** (heartbeat, dashboard, force-reindex) в 2.x
   через stdio не поддержаны: `request_handlers` удалён. Либо инструменты
   (поверхность 69 → 72, обновление `AGENTS.md`/FACTS/`check_tool_names`),
   либо удаление. Решение владельца — иначе фича молча исчезнет.
6. **OpenTelemetry включён по умолчанию** — новый старт-путь и зависимость.
   Для локального сервера это лишний оверхед; проверить `OTEL_SDK_DISABLED=true`
   как дефолт для stdio-режима.
7. **Строгая валидация результатов** (`Server handler results are validated`):
   любой инструмент, возвращающий не-схемный объект, начнёт падать там, где
   раньше проходил. Наши 69 инструментов надо прогнать через `tools/call`
   smoke, а не только через `tools/list`.
8. **Откат.** `mcp>=1.28,<2` + `pip install -r` возвращает всё, потому что
   Phase 1 держит импорт с fallback. Но после Phase 2 (переписанный `isError`)
   откат уже потребует ветки `v1.x` — поэтому Phase 2 не мержим в один PR
   с Phase 3.

## Решения (приняты по фактам, не по вкусу)

| # | Вопрос | Решение | Почему |
|---|---|---|---|
| 1 | heartbeat / dashboard / force-reindex / clear_memory | **не переносить в инструменты; регистрация под 2.x снята (debug-лог), поверхность остаётся 69** | `grep` по `src/`, `tests/`, `scripts/`, `adapters/`, `docs/` не нашёл **ни одного** потребителя этих JSON-RPC методов — они существовали только как регистрация в `server_factory.py`. Их смысл уже покрыт инструментами: `intel_trigger_reindex`, `intel_reset_index`, `codebase(action="index", path="status")`. Перенос в инструменты изменил бы публичную поверхность (69 → 73) и потребовал правки `AGENTS.md`, FACTS и `check_tool_names` — цена без пользы |
| 2 | OpenTelemetry (в 2.x включён по умолчанию) | **оставляем дефолт SDK, без кода** | спаны без настроенного экспортёра — no-op; отключать глобально значит ломать интеграцию тем, кто её захочет. Кто не хочет — ставит `OTEL_SDK_DISABLED=true` |
| 3 | Streamable HTTP: 30-мин idle | **оставляем дефолт SDK (1800 с)** | сервер single-user/self-hosted; клиент после 404 переинициализируется штатно, а бесконечные сессии — это утечка памяти. Поведение задокументировано, а не «потеряно» |
| 4 | `isError` в 2.x | **middleware** `(ctx, call_next)`, метка ставится в wire-dict `result["isError"]` | `request_handlers` удалён; middleware — публичная точка, одна на все 69 инструментов, payload не меняется |
| 5 | Тесты, завязанные на v1 | **портированы** (`_call` → `Client(server)`, `_is_error` вместо `.root.isError`) | контракт изменил сам SDK; проверки сохранены по смыслу («вызов помечен ошибкой»), ни один ассерт не удалён |
| 6 | Тесты, импортирующие `mcp.server.fastmcp` | **один шим в `tests/conftest.py`**, файлы не правились | 4 файла, 7 импортов, часть — внутри функций (грубая замена ломает отступы); один шим дешевле и переживёт удаление линии 1.x |
