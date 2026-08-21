"""Runner плагинов (Фаза 4, §5.4) — исполняет плагин в ОТДЕЛЬНОМ процессе.

Хост (proxy) выполняет trust-гейт БЕЗ импорта кода (preauthorize_plugin) и\nспавнит этот runner как subprocess. Runner загружает плагин с resolver=None\n(fail-closed): если (id,version) НЕ доверен в общем trust-сторе — выходит с\nкодом 2, код плагина НЕ исполняется. Доверенный плагин исполняется здесь, в\nсвоём процессе: RCE/мутации плагина не затрагивают процесс/память/DI хоста.\n\nПротокол: JSON-RPC 2.0, line-delimited (одна JSON per строка) по stdio:\n  -> {\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}\n  <- {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":[{\"name\":..,\"description\":..}]}\n  -> {\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":..,\"arguments\":{..}}}\n  <- {\"jsonrpc\":\"2.0\",\"id\":2,\"result\":{\"name\":..,\"result\":<json>}}\n  Ошибка: ... \"error\":{\"code\":-32602,\"message\":..}\n\nЗапуск: python -m src.plugins.runner <plugin_dir> <data_root>\n"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(rid, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": str(message)}})


def _call_handler(handler, args: dict):
    res = handler(**(args or {}))
    if inspect.iscoroutine(res):
        res = asyncio.run(res)
    return res


def main(argv) -> int:
    if len(argv) < 3:
        sys.stderr.write("usage: runner <plugin_dir> <data_root>\n")
        return 2
    plugin_dir = Path(argv[1])
    data_root = Path(argv[2])

    from src.plugins import MANIFEST_NAME, PluginTrustStore, load_manifest, load_plugin

    store = PluginTrustStore(data_root / "plugins" / "trust.json")
    manifest = load_manifest(plugin_dir / MANIFEST_NAME)
    try:
        # fail-closed: только уже-доверенные; resolver=None → иначе отказ ДО импорта
        tools = load_plugin(manifest, plugin_dir, store, trust_resolver=None)
    except Exception as e:  # noqa: BLE001 — runner обязан отчитаться и не exec'ить
        sys.stderr.write(json.dumps({"bootstrap_error": type(e).__name__, "str": str(e)}) + "\n")
        return 2

    handlers = {t["name"]: t["handler"] for t in tools}
    meta = {t["name"]: {"description": t.get("description", "")} for t in tools}

    # сервим JSON-RPC по строкам
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _error(None, -32700, "parse error")
            continue
        rid = msg.get("id")
        method = msg.get("method")
        if method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": [
                {"name": n, "description": v["description"]} for n, v in meta.items()
            ]})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            handler = handlers.get(name)
            if handler is None:
                _error(rid, -32602, f"unknown tool: {name}")
                continue
            try:
                res = _call_handler(handler, args)
                _send({"jsonrpc": "2.0", "id": rid, "result": {"name": name, "result": res}})
            except Exception as e:  # noqa: BLE001 — исключение плагина → JSON-RPC error
                _error(rid, -32000, f"{type(e).__name__}: {e}")
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": rid, "result": "pong"})
        else:
            _error(rid, -32601, f"method not found: {method}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
