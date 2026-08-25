"""Манифест плагина (Фаза 4, план §5.1).

Модель ToolPlugin + загрузчик манифеста. Манифест парсится БЕЗ исполнения кода
(только JSON) — первая стадия load-гейта. Валидация:
  - обязательные поля (id, name, version, schema_version, tools, entrypoint);
  - schema_version совместим с поддерживаемым (v1 -> 1);
  - platform: ["any"]/-или текущая ОС;
  - requires_engine_version: SpecifierSet против версии движка (packaging).

source_sha256 — пин издателя (payload хеш); сверяется trust-store'ом на load.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from packaging.specifiers import SpecifierSet

MANIFEST_NAME = "plugin.json"
_SCHEMA_VERSION = 1
_PLATFORM_ALIAS = {
    "win32": "windows",
    "linux": "linux",
    "darwin": "darwin",
}


@dataclass(frozen=True)
class ToolPlugin:
    """Описание плагина из manifest (парсится из JSON, не исполняется)."""

    id: str
    name: str
    version: str
    schema_version: int
    requires_engine_version: str
    platform: List[str]
    entrypoint: str
    tools: List[str]
    source_sha256: str
    source: str
    load_mode: str = "in_process"  # v1: только in_process; subprocess — следующий инкремент
    dependencies: List[str] = field(default_factory=list)

    @property
    def trust_key(self) -> str:
        return f"{self.id}@{self.version}"


class PluginManifestError(Exception):
    """Ошибка манифеста плагина (невалидный JSON / несовместимость)."""

    def __init__(self, reason: str, kind: str):
        super().__init__(f"[{kind}] {reason}")
        self.kind = kind
        self.reason = reason


def current_platform() -> str:
    """Каноническое имя текущей платформы (windows/linux/darwin)."""
    return _PLATFORM_ALIAS.get(sys.platform, sys.platform)


def load_manifest(manifest_path: Path) -> ToolPlugin:
    """Читает и валидирует plugin.json. Не исполняет код плагина."""
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PluginManifestError(f"manifest not found: {manifest_path}", "manifest_missing") from e
    except json.JSONDecodeError as e:
        raise PluginManifestError(f"invalid json: {e}", "manifest_invalid") from e

    required = ("id", "name", "version", "schema_version", "tools", "entrypoint")
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise PluginManifestError(f"missing required field(s): {missing}", "manifest_incomplete")

    for key in ("id", "name", "version"):
        val = str(raw[key]).strip()
        if not val:
            raise PluginManifestError(f"empty '{key}'", "manifest_invalid")
        raw[key] = val

    sv = raw["schema_version"]
    if isinstance(sv, str):
        try:
            sv = int(sv)
        except ValueError as e:
            raise PluginManifestError("schema_version must be int", "schema_mismatch") from e
    if sv != _SCHEMA_VERSION:
        raise PluginManifestError(
            f"schema_version={sv} unsupported (expected {_SCHEMA_VERSION})", "schema_mismatch"
        )
    raw["schema_version"] = sv

    platforms = raw.get("platform", ["any"])
    platforms = [p if isinstance(p, str) else "any" for p in platforms]
    if "any" not in platforms and current_platform() not in platforms:
        raise PluginManifestError(
            f"platform {current_platform()} not in {platforms}", "platform_mismatch"
        )
    raw["platform"] = platforms

    req = str(raw.get("requires_engine_version", ""))
    if req == "":
        req = ">=0"  # по умолчанию — любой движок (консервативно, явный пин лучше)
    raw["requires_engine_version"] = req

    try:
        SpecifierSet(req)
    except Exception:  # noqa: BLE001 — невалидный spec не должен ронять импорт модуля
        raise PluginManifestError(
            f"invalid requires_engine_version '{req}'", "engine_req_invalid"
        ) from None

    tools = raw["tools"]
    if isinstance(tools, str):
        tools = [tools]
    if not isinstance(tools, list) or not tools:
        raise PluginManifestError("'tools' must be a non-empty list", "manifest_invalid")
    for t in tools:
        if not isinstance(t, str) or not t.strip():
            raise PluginManifestError("tool name must be non-empty str", "manifest_invalid")
    raw["tools"] = [t.strip() for t in tools]

    deps = raw.get("dependencies", [])
    if isinstance(deps, str):
        deps = [deps]
    if not isinstance(deps, list):
        deps = []
    deps = [str(d).strip() for d in deps if str(d).strip()]

    return ToolPlugin(
        id=raw["id"],
        name=raw["name"],
        version=raw["version"],
        schema_version=raw["schema_version"],
        requires_engine_version=raw["requires_engine_version"],
        platform=platforms,
        entrypoint=raw["entrypoint"],
        tools=raw["tools"],
        source_sha256=str(raw.get("source_sha256", "")).strip(),
        source=str(raw.get("source", "unknown")).strip(),
        load_mode=str(raw.get("load_mode", "in_process")).strip(),
        dependencies=deps,
    )


def check_engine_compat(manifest: ToolPlugin, engine_version: str) -> None:
    """Проверяет requires_engine_version против версии движка (план §5.1)."""
    spec = SpecifierSet(manifest.requires_engine_version)
    if engine_version not in spec:
        raise PluginManifestError(
            f"engine {engine_version} does not satisfy {manifest.requires_engine_version}",
            "version_mismatch",
        )


def iter_manifest_dirs(plugins_root: Path):
    """Итерирует каталоги-плагины в plugins_root, в которых есть plugin.json (не импорт)."""
    if not plugins_root.is_dir():
        return
    for child in sorted(p for p in plugins_root.iterdir() if p.is_dir()):
        if (child / MANIFEST_NAME).is_file():
            yield child
