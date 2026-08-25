"""Фаза 5 — адаптеры: конфиги клиентов + CLI wrapper (план §4)."""
from __future__ import annotations

import json
from pathlib import Path

import src.cli as cli

ADAPTERS = Path(__file__).resolve().parent.parent / "adapters" / "clients"


def _load(name: str):
    return json.loads((ADAPTERS / name).read_text(encoding="utf-8"))


# ── конфиги клиентов ─────────────────────────────────────────────────────────

def test_claude_config_parse():
    c = _load("claude.code.mcp.json")
    assert "mscodebase" in c["mcpServers"]
    assert "mscodebase-remote" in c["mcpServers"]


def test_vscode_config_parse():
    c = _load("vscode.mcp.json")
    assert "mscodebase" in c["servers"]
    assert "mscodebase-remote" in c["servers"]


def test_stdio_ref_valid_entrypoint():
    c = _load("claude.code.mcp.json")["mcpServers"]["mscodebase"]
    assert c["type"] == "stdio"
    assert c["args"] == ["-m", "src.main"]
    assert "PYTHONPATH" in c["env"]


def test_remote_ref_mcp_endpoint():
    for name in ("claude.code.mcp.json", "vscode.mcp.json"):
        servers = _load(name)["mcpServers" if "claude" in name else "servers"]
        r = servers["mscodebase-remote"]
        assert r["type"] == "http"
        assert r["url"].endswith("/mcp")
        assert "Authorization" in r["headers"]


# ── CLI wrapper (прямой вызов tool-классов без MCP) ─────────────────────────

def test_cli_unknown_tool(tmp_path, capsys):
    rc = cli.main(["no_such_tool", "{}"])
    assert rc == 2
    assert "unsupported CLI tool" in capsys.readouterr().err


def test_cli_bad_args(tmp_path, capsys):
    rc = cli.main(["get_task_status", "not-json"])
    assert rc == 2
    assert "bad arguments" in capsys.readouterr().err


def test_cli_dispatch_ok(monkeypatch, capsys):
    class FakeServices:
        def shutdown(self):
            return None

    class FakeTool:
        def __init__(self, services):
            self.services = services

        def execute(self, **kw):
            return {"echo": kw}

    monkeypatch.setattr(cli, "create_service_collection", lambda root: FakeServices())
    monkeypatch.setattr(cli, "core_tool_allowlist", lambda: {"fake_tool": FakeTool})

    rc = cli.main(["fake_tool", '{"a": 1}'])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["result"] == {"echo": {"a": 1}}


def test_cli_dispatch_tool_error(monkeypatch, capsys):
    class FakeTool:
        def __init__(self, services):
            pass

        def execute(self, **kw):
            raise ValueError("boom")

    monkeypatch.setattr(cli, "create_service_collection", lambda root: object())
    monkeypatch.setattr(cli, "core_tool_allowlist", lambda: {"fake_tool": FakeTool})

    rc = cli.main(["fake_tool", "{}"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "boom" in err
