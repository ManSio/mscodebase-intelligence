"""Proxy плагинов (Фаза 4, §5.4) — хост-сторона subprocess-изоляции.

Host выполняет trust-гейт БЕЗ импорта кода плагина (preauthorize_plugin) —
код исполняется ТОЛЬКО в runner-subprocess. Proxy спавнит runner, discovers
его тулы (tools/list) и вызывает через JSON-RPC line-delimited по stdio.
RCE/мутация третьестороннего плагина не касается процесса/памяти/DI хоста
(процессная граница; НЕ файловая песочница — см. план §5.4: subprocess как
граница, RestrictedPython — только харденинг, wasmtime — отложен).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from src.plugins.loader import PluginLoadError, preauthorize_plugin
from src.plugins.manifest import MANIFEST_NAME, load_manifest
from src.plugins.trust_store import PluginTrustStore, default_trust_store_path

_ROOT = Path(__file__).resolve().parent.parent.parent


class PluginProcess:
    """Дальний плагин в отдельном процессе с JSON-RPC/stdio."""

    def __init__(
        self,
        plugin_dir: Path,
        data_root: Optional[Path] = None,
        store: Optional[PluginTrustStore] = None,
        trust_resolver=None,
    ):
        self.plugin_dir = Path(plugin_dir)
        self.data_root = Path(data_root) if data_root else Path(os.environ.get("MSCODEBASE_DATA_DIR", "."))
        self.store = store or PluginTrustStore(default_trust_store_path())
        self.manifest = load_manifest(self.plugin_dir / MANIFEST_NAME)

        # Host-side trust-гейт БЕЗ exec; решение/UX — здесь (ум ит. store).
        preauthorize_plugin(self.manifest, self.plugin_dir, self.store, trust_resolver)

        self._proc = self._spawn()
        self._tools: Optional[List[dict]] = None

    def _spawn(self) -> subprocess.Popen:
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", str(_ROOT))
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Запуск runner.py КАК СКРИПТ (не -m): избегает unstable double-import
        # пакета (RuntimeWarning "found in sys.modules") на Windows.
        runner = _ROOT / "src" / "plugins" / "runner.py"
        return subprocess.Popen(
            [sys.executable, str(runner), str(self.plugin_dir), str(self.data_root)],
            cwd=str(_ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        if self._proc.stdin is None or self._proc.stdout is None or self._proc.poll() is not None:
            raise PluginLoadError("plugin process exited before request", "proc_dead")
        req = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            req["params"] = params
        self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            self._reap()
            tail = self._stderr_tail()
            raise PluginLoadError(
                f"plugin process closed stdout (bootstrap/load failure): {tail}", "proc_dead"
            )
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as e:
            raise PluginLoadError(f"bad JSON-RPC response: {e}", "proc_protocol") from e
        if "error" in resp:
            err = resp["error"]
            raise PluginLoadError(f"{err.get('message')}", "rpc_error")
        return resp.get("result")

    def _stderr_tail(self) -> str:
        try:
            if self._proc.stderr is not None:
                return (self._proc.stderr.read() or "")[-500:]
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _reap(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def list_tools(self) -> List[dict]:
        if self._tools is None:
            self._tools = self._rpc("tools/list") or []
        return list(self._tools)

    def call(self, name: str, **kwargs):
        res = self._rpc("tools/call", {"name": name, "arguments": kwargs})
        if not isinstance(res, dict) or "result" not in res:
            raise PluginLoadError(f"unexpected tools/call result for {name}", "proc_protocol")
        return res["result"]

    def close(self) -> None:
        self._reap()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
