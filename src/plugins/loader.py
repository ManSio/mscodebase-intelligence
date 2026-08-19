"""Load-гейт плагинов (Фаза 4, план §5.2/§5.3/§5.5).

Строгий порядок (TOCTOU-guard, fail-closed):
  1. check_engine_compat (requires_engine_version, содержание — из манифеста, без exec);
  2. payload-хэш (sha256 файла entrypoint);
  3. trust-decision: если (id,version,hash) доверен → ok; если не трекается → resolver
     (по умолчанию deny); если hash дрейфанул от записанного → resolver re-ask
     (по умолчанию deny). Любое изменение между решениями веток перегоняет гейт;
  4. re-hash ПРЯМО перед импортом — правка между гейтом и import = отказ (TOCTOU);
  5. импорт entrypoint (importlib, отдельный разрешённый путь — НЕ execute_script);
  6. self-check (P-001, план §5.5): плагин, импортировавшийся без exception, обязан
     зарегистрировать ВСЕ заявленные в манифесте тулы; иначе — сбой загрузки.

In-process модель v1 (доверенные / first-party). subprocess-изоляция для third-party
и MCP-proxy — следующий инкремент (план §5.4).
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src import __version__ as _ENGINE_VERSION
from src.plugins.manifest import (
    PluginManifestError,
    ToolPlugin,
    check_engine_compat,
)


class PluginLoadError(Exception):
    def __init__(self, reason: str, kind: str):
        super().__init__(f"[{kind}] {reason}")
        self.kind = kind
        self.reason = reason


def compute_payload_sha256(entry_file: Path) -> str:
    h = hashlib.sha256()
    h.update(entry_file.read_bytes())
    return h.hexdigest()


def load_plugin(
    manifest: ToolPlugin,
    plugin_dir: Path,
    store,
    trust_resolver: Optional[Callable[[ToolPlugin, str, bool], bool]] = None,
    engine_version: Optional[str] = None,
) -> List[dict]:
    """Выполняет load-гейт и возвращает список тулов плагина.

    trust_resolver(manifest, sha256, drift) -> bool — вызывается для принятия/
    переспроса решения доверия. None → default-deny.
    Вернёт список {"name", "description", "handler"}.
    """
    # 1) engine compat (содержание — из манифеста, без exec; унифицируем ошибку)
    try:
        check_engine_compat(manifest, engine_version or _ENGINE_VERSION)
    except PluginManifestError as e:
        raise PluginLoadError(e.reason, e.kind) from e

    entry_file = (plugin_dir / manifest.entrypoint).resolve()
    if not entry_file.is_file():
        raise PluginLoadError(f"entrypoint not found: {entry_file}", "entrypoint_missing")

    sha = compute_payload_sha256(entry_file)

    if store.is_trusted(manifest.id, manifest.version, sha):
        pass  # доверен, хэш совпадает
    elif store.decision(manifest.id, manifest.version) is None:
        if not _resolve_trust(store, manifest, sha, trust_resolver, drift=False):
            raise PluginLoadError(
                f"not trusted — requires explicit approval "
                f"(id={manifest.id}@{manifest.version})", "untrusted"
            )
    else:
        # запись есть, но содержимое дрейфануло — переспрашиваем
        if not _resolve_trust(store, manifest, sha, trust_resolver, drift=True):
            raise PluginLoadError("payload hash drifted since trust; not re-approved", "sha_drift")

    # TOCTOU: пересчитываем хэш прямо перед импортом
    if compute_payload_sha256(entry_file) != sha:
        raise PluginLoadError("entrypoint changed between gate and load", "toctou")

    module = _import_entrypoint(manifest, entry_file)
    return _collect_tools(module, manifest)


def _resolve_trust(
    store, manifest: ToolPlugin, sha: str,
    resolver: Optional[Callable[[ToolPlugin, str, bool], bool]], drift: bool,
) -> bool:
    approved = bool(resolver(manifest, sha, drift)) if resolver is not None else False
    if approved:
        store.trust(manifest.id, manifest.version, sha, manifest.source)
    return approved


def _import_entrypoint(manifest: ToolPlugin, entry_file: Path):
    """Импортирует entrypoint плагина (разрешённый путь, отдельный от execute_script)."""
    module_name = f"_mscb_plugin_{manifest.id}_{manifest.version.replace('.', '_')}_{manifest.load_mode}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(entry_file))
        if spec is None or spec.loader is None:
            raise PluginLoadError("cannot create import spec", "import_failed")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except PluginLoadError:
        raise
    except Exception as e:  # noqa: BLE001 — любая ошибка плагина = сбой загрузки с reason
        raise PluginLoadError(f"import failed: {type(e).__name__}: {e}", "import_failed") from e


def _collect_tools(module, manifest: ToolPlugin) -> List[dict]:
    raw = getattr(module, "TOOLS", None)
    if not raw:
        raise PluginLoadError(
            "plugin imported OK but registered no tools (self-check, P-001)",
            "selfcheck_failed",
        )
    by_name: Dict[str, dict] = {}
    for item in raw:
        name = item.get("name")
        handler = item.get("handler")
        if not name or not callable(handler):
            continue
        by_name[name] = {
            "name": name,
            "description": item.get("description", ""),
            "handler": handler,
        }
    missing = [t for t in manifest.tools if t not in by_name]
    if missing:
        raise PluginLoadError(
            f"self-check failed: manifest declares {missing} but they are not registered",
            "selfcheck_failed",
        )
    return [by_name[n] for n in manifest.tools]
