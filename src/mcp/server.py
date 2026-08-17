"""MSCodebase Intelligence MCP Server — рефакторинг v3

Чистый IoC-ориентированный сервер с DI-контейнером.

Архитектура:
- create_mcp_server() — только регистрация инструментов
- DI Container (ServiceCollection) — единственное место создания зависимостей
- tool/*.py — каждый инструмент в отдельном классе с constructor injection
- core/* — чистая бизнес-логика без MCP-зависимостей
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mscodebase_server")


# ══════════════════════════════════════════════════════════
# Process Passport — уникальный ID запуска для диагностики
# ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════
# Re-экспорты для обратной совместимости.
# Источники правды: src/core/passport.py, src/core/project_resolution.py,
# src/mcp/context.py (ARCH-03 + ARCLUX 2026-08-17: разрыв server↔factory↔tools).
# server.py — тонкий фасад: тесты/скрипты импортируют эти имена из mcp.server.
# ══════════════════════════════════════════════════════════
from src.core.passport import (
    RUN_ID as _RUN_ID,  # noqa: F401 — реэкспорт
)
from src.core.passport import (
    RUN_PID as _RUN_PID,  # noqa: F401 — реэкспорт
)
from src.core.passport import (
    RUN_STARTED_AT as _RUN_STARTED_AT,  # noqa: F401 — реэкспорт
)
from src.core.project_resolution import (
    ext_root as _ext_root,  # noqa: F401 — реэкспорт
)
from src.core.project_resolution import (
    reset_project_root_cache,  # noqa: F401 — реэкспорт
    resolve_project_root,  # noqa: F401 — реэкспорт
)
from src.mcp.context import (
    _BUILD_ID,  # noqa: F401 — реэкспорт
    _RUN_SOURCE_FILE,  # noqa: F401 — реэкспорт
    _check_source_extension_sync,  # noqa: F401 — реэкспорт
    _default_project_root,  # noqa: F401 — реэкспорт
    _log_run_passport,  # noqa: F401 — реэкспорт
    _services_cache,  # noqa: F401 — реэкспорт
)

# Default project root (устанавливается при create_mcp_server) —
# состояние перенесено в src/mcp/context.py (реэкспорт выше).


# ══════════════════════════════════════════════════════════
# Создание MCP-сервера
# ══════════════════════════════════════════════════════════


# Re-export from server_factory (избегаем циклического импорта)
def run_server(original_stdout=None):
    """Запускает MCP-сервер через stdio (обёртка над server_factory)."""
    from src.mcp.server_factory import run_server as _run
    _run(original_stdout)
