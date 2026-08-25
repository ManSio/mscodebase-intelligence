"""Плагины → MCP-сервер (Фаза 4, хвост; план §5.4/§5.5).

wire_plugins(mcp): если задан MSCODEBASE_PLUGINS_DIR — строит PluginRegistry
(preauthorize БЕЗ exec), спавнит runner-subprocess'ы и регистрирует их тулы как
FastMCP-тулы (register_fastmcp). Fail-safe/default-deny: без env — no-op; не
доверенные плагины (trust_resolver=None) → registry.load() откажет → skip;
исключение → warning, сервер продолжает. Subprocess'ы держатся живыми весь срок
службы сервера (registry закреплён на mcp).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from src.plugins.loader import PluginLoadError
from src.plugins.registry import PluginRegistry, register_fastmcp

logger = logging.getLogger("mscodebase_server.plugins")


def wire_plugins(mcp, plugins_root=None, store=None, trust_resolver=None):
    """Регистрирует plugin-тулы в FastMCP-сервере (opt-in). Возвращает registry | None.

    plugins_root/trust_resolver — тестируемые инъекции; по умолчанию из env
    MSCODEBASE_PLUGINS_DIR и fail-closed (default-deny вне UI).
    """
    root = plugins_root if plugins_root is not None else os.environ.get("MSCODEBASE_PLUGINS_DIR", "").strip()
    if not root:
        return None
    plugins_dir = Path(root)
    if not plugins_dir.is_dir():
        logger.warning(f"plugins: {plugins_dir} не каталог — plugin-тулы не подключены")
        return None
    # data_root для runner-процессов обязан указывать на тот же trust-стор,
    # что и переданный store (иначе subprocess не найдёт доверие -> fail-closed).
    data_root = None
    if store is not None and hasattr(store, "_path"):
        data_root = store._path.parent.parent
    reg = PluginRegistry(plugins_dir, store=store, trust_resolver=trust_resolver,
                         data_root=data_root)
    try:
        reg.load()
    except PluginLoadError as e:
        logger.warning(f"plugins: не загружены ({e.kind}: {e.reason}) — try/deny-default, пропуск")
        reg.close()
        return None
    except Exception as e:  # noqa: BLE001 — fail-safe: сервер не должен падать из-за плагина
        logger.warning(f"plugins: ошибка загрузки ({type(e).__name__}: {e})")
        reg.close()
        return None
    register_fastmcp(reg, mcp)
    # держим subprocess'ы живыми весь срок службы сервера
    setattr(mcp, "_plugin_registry", reg)
    logger.info(f"plugins: подключено {len(reg.tools())} тулов из {plugins_dir}")
    return reg
