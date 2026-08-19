"""Плагины (Фаза 4, план §5).

Ядро безопасности v1: манифест (ToolPlugin), trust-store (per id@version, sha256),
load-гейт с TOCTOU-guard и self-check (P-001). In-process для доверенных/first-party;
subprocess-изоляция для third-party и MCP-proxy — следующий инкремент.

Точка входа для внешнего кода:
  from src.plugins import load_plugin, load_manifest, ToolPlugin, PluginLoadError
"""
from __future__ import annotations

from src.plugins.loader import (  # noqa: F401
    PluginLoadError,
    compute_payload_sha256,
    load_plugin,
)
from src.plugins.manifest import (  # noqa: F401
    MANIFEST_NAME,
    PluginManifestError,
    ToolPlugin,
    check_engine_compat,
    current_platform,
    load_manifest,
)
from src.plugins.trust_store import PluginTrustStore  # noqa: F401

__all__ = [
    "PluginLoadError",
    "PluginManifestError",
    "PluginTrustStore",
    "ToolPlugin",
    "MANIFEST_NAME",
    "check_engine_compat",
    "compute_payload_sha256",
    "current_platform",
    "load_manifest",
    "load_plugin",
]
