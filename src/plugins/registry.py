"""Реестр плагинов / MCP-proxy wiring (Фаза 4, план §5.4/§5.5).

Host-side orchestrator: находит плагины (манифесты), для каждого выполняет
trust-гейт (preauthorize, без exec), спавнит subprocess-runner (PluginProcess)
и предоставляет его тулы как proxy-callable — «вход → правильный выход» через
отдельный процесс (изоляция). Тулы затем можно зарегистрировать в FastMCP-сервере
(register_fastmcp), оставив исполнение кода плагина вне процесса сервера.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Optional

from src.plugins.loader import preauthorize_plugin
from src.plugins.manifest import (
    MANIFEST_NAME,
    ToolPlugin,
    iter_manifest_dirs,
    load_manifest,
)
from src.plugins.proxy import PluginProcess
from src.plugins.trust_store import PluginTrustStore, default_trust_store_path

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9_]")


def normalize_tool_name(plugin_id: str, tool: str) -> str:
    """Уникальное имя MCP-тула для плагинного тула (safe идентификатор)."""
    return f"{_NON_ALNUM.sub('_', plugin_id)}_{_NON_ALNUM.sub('_', tool)}"


class PluginRegistry:
    """Host-реестр: plugin_id -> PluginProcess; aggregates proxy tools."""

    def __init__(
        self,
        plugins_root,
        store: Optional[PluginTrustStore] = None,
        trust_resolver=None,
        data_root=None,
    ):
        self.plugins_root = Path(plugins_root)
        self.store = store or PluginTrustStore(default_trust_store_path())
        self.trust_resolver = trust_resolver
        self.data_root = Path(data_root) if data_root else None
        self._processes: Dict[str, PluginProcess] = {}

    def discover(self) -> List[ToolPlugin]:
        return [
            load_manifest(d / MANIFEST_NAME)
            for d in iter_manifest_dirs(self.plugins_root)
        ]

    def load(self) -> None:
        """Для каждого плагина: preauthorize (без exec) + спавн runner-proxy."""
        for manifest in self.discover():
            plugin_dir = self.plugins_root / manifest.id
            # host-side гейт без импорта кода (доверие здесь, exec там)
            preauthorize_plugin(
                manifest, plugin_dir, self.store,
                trust_resolver=self.trust_resolver,
            )
            if manifest.id in self._processes:
                self._processes[manifest.id].close()
            self._processes[manifest.id] = PluginProcess(
                plugin_dir, data_root=self.data_root, store=self.store,
                trust_resolver=None,  # уже preauthorized выше; runner re-verify до exec
            )

    def tools(self) -> List[dict]:
        """Список тулов всех загруженных плагинов как proxy-callable.

        Каждый: {"plugin_id", "name", "description", "call": fn(**kwargs)->json}.
        """
        out: List[dict] = []
        for pid, proc in self._processes.items():
            for t in proc.list_tools():
                out.append({
                    "plugin_id": pid,
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "call": self._make_call(proc, t["name"]),
                })
        return out

    @staticmethod
    def _make_call(proc: PluginProcess, name: str):
        return lambda **kw: proc.call(name, **kw)

    def close(self) -> None:
        for p in self._processes.values():
            p.close()
        self._processes.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def register_fastmcp(registry: PluginRegistry, mcp):
    """Регистрирует plugin-тулы в FastMCP-сервере (проксирование в subprocess).

    Каждый plugin-тул -> FastMCP tool `plugin_<id>_<tool>(arguments: dict)`,
    который через asyncio.to_thread вызывает proxy-call (не блокирует loop).
    Исполнение кода плагина — вне процесса сервера (изоляция).
    """
    for item in registry.tools():
        name = normalize_tool_name(item["plugin_id"], item["name"])
        description = item["description"]
        call = item["call"]

        async def _proxy(arguments=None):
            args = arguments or {}
            if not isinstance(args, dict):
                raise TypeError("plugin tool 'arguments' must be a JSON object")
            return await asyncio.to_thread(call, **args)

        _proxy.__name__ = name
        _proxy.__doc__ = description or f"Plugin tool (id={item['plugin_id']}, {item['name']})"
        mcp.tool()(_proxy)
