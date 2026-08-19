"""Плагины (Фаза 4, план §5).

Ядро безопасности v1: манифест (ToolPlugin), trust-store (per id@version, sha256),
load-гейт с TOCTOU-guard и self-check (P-001). In-process для доверенных/first-party;
subprocess-изоляция для third-party: host preauthorize (trust-гейт без exec) +
runner (исполнение в отдельном процессе, fail-closed) + JSON-RPC proxy.

Точка входа для внешнего кода:
  from src.plugins import load_manifest, preauthorize_plugin, load_plugin, PluginProcess
"""
from __future__ import annotations

from src.plugins.deps import validate_dependencies  # noqa: F401
from src.plugins.loader import (  # noqa: F401
    PluginLoadError,
    compute_payload_sha256,
    load_plugin,
    preauthorize_plugin,
)
from src.plugins.manifest import (  # noqa: F401
    MANIFEST_NAME,
    PluginManifestError,
    ToolPlugin,
    check_engine_compat,
    current_platform,
    iter_manifest_dirs,
    load_manifest,
)
from src.plugins.prompt import DENY_ALL, make_trust_resolver, trust_prompt  # noqa: F401
from src.plugins.proxy import PluginProcess  # noqa: F401
from src.plugins.registry import (  # noqa: F401
    PluginRegistry,
    normalize_tool_name,
    register_fastmcp,
)
from src.plugins.trust_store import (  # noqa: F401
    PluginTrustStore,
    default_trust_store_path,
)

__all__ = [
    "DENY_ALL",
    "PluginLoadError",
    "PluginManifestError",
    "PluginProcess",
    "PluginRegistry",
    "PluginTrustStore",
    "ToolPlugin",
    "MANIFEST_NAME",
    "check_engine_compat",
    "compute_payload_sha256",
    "current_platform",
    "default_trust_store_path",
    "iter_manifest_dirs",
    "load_manifest",
    "load_plugin",
    "make_trust_resolver",
    "normalize_tool_name",
    "preauthorize_plugin",
    "register_fastmcp",
    "trust_prompt",
    "validate_dependencies",
]
