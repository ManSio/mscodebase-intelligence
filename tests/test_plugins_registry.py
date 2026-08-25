"""Фаза 4 — MCP-proxy wiring (registry), trust-гейт UX (prompt), dependencies.

End-to-end: хост PluginRegistry → preauthorize (без exec) → runner-subprocess →
proxy call → результат. Тулы плагина из examples/plugins (реальный PoC verify_claim).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from src.plugins import (
    DENY_ALL,
    MANIFEST_NAME,
    PluginRegistry,
    PluginTrustStore,
    load_manifest,
    make_trust_resolver,
    normalize_tool_name,
    register_fastmcp,
    trust_prompt,
)
from src.plugins.deps import validate_dependencies

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"

_ADD_ENTRY = (
    "def add(a, b):\n"
    "    return a + b\n"
    "TOOLS = [{'name': 'add', 'description': 'sum', 'handler': add}]\n"
)


def test_normalize_tool_name():
    assert normalize_tool_name("my.plug", "do thing") == "my_plug_do_thing"


def test_discover():
    reg = PluginRegistry(EXAMPLES, store=PluginTrustStore(Path("x") / "y"))
    ids = [m.id for m in reg.discover()]
    assert "verify_claim" in ids


def test_registry_tools_end_to_end(tmp_path):
    store = PluginTrustStore(tmp_path / "data" / "plugins" / "trust.json")
    resolver = make_trust_resolver(auto_approve=True)
    with PluginRegistry(EXAMPLES, store=store, trust_resolver=resolver,
                        data_root=tmp_path / "data") as reg:
        reg.load()
        tools = reg.tools()
        assert any(t["plugin_id"] == "verify_claim" and t["name"] == "verify_claim"
                   for t in tools)
        vc = next(t for t in tools if t["name"] == "verify_claim")
        assert vc["call"](claim="alpha", anchors=["alpha beta"]) == "VERIFIED"
        assert vc["call"](claim="zzz", anchors=["alpha beta"]) == "REFUTED"
        assert vc["call"](claim="alpha", anchors=None) == "UNKNOWN"


def test_registry_untrusted_denied(tmp_path):
    store = PluginTrustStore(tmp_path / "data" / "plugins" / "trust.json")
    reg = PluginRegistry(EXAMPLES, store=store, trust_resolver=DENY_ALL,
                         data_root=tmp_path / "data")
    with pytest.raises(Exception):  # preauthorize откажет (DENY_ALL)
        reg.load()
    reg.close()


def test_prompt_fields():
    m = load_manifest(EXAMPLES / "verify_claim" / MANIFEST_NAME)
    p = trust_prompt(m, "abcd1234")
    assert "abcd1234" in p
    assert m.name in p and m.version in p and m.source in p


def test_resolver_auto_approve():
    r = make_trust_resolver(auto_approve=True)
    assert r(None, "x", False) is True


def test_resolver_default_deny():
    r = make_trust_resolver()
    assert r(None, "x", False) is False
    assert DENY_ALL(None, "x", False) is False


def test_resolver_decide_called():
    seen = {}

    def decide(prompt):
        seen["p"] = prompt
        return True

    r = make_trust_resolver(decide)
    m = load_manifest(EXAMPLES / "verify_claim" / MANIFEST_NAME)
    assert r(m, "sha-aaa", False) is True
    assert "sha-aaa" in seen["p"]


def test_resolver_drift_note(tmp_path):
    seen = {}

    def decide(prompt):
        seen["p"] = prompt
        return True

    r = make_trust_resolver(decide)
    m = load_manifest(EXAMPLES / "verify_claim" / MANIFEST_NAME)
    r(m, "s", True)
    assert "DRIFT" in seen["p"]


def test_deps_validation():
    assert validate_dependencies(["requests==2.32.0", "numpy==2.4.0"]) == []
    warns = validate_dependencies(["requests", "requests>=2; python_version<'3.11'"])
    assert len(warns) == 2


def test_register_fastmcp_no_error(tmp_path):
    store = PluginTrustStore(tmp_path / "data" / "plugins" / "trust.json")
    reg = PluginRegistry(EXAMPLES, store=store,
                         trust_resolver=make_trust_resolver(auto_approve=True),
                         data_root=tmp_path / "data")
    reg.load()
    mcp = FastMCP("test-registration")
    register_fastmcp(reg, mcp)  # не должно бросить (регистрация динамических тулов)
    reg.close()


# ── wiring в сервер (Фаза 4 хвост) ─────────────────────────────────────────

def _make_plugin_root(tmp_path, name="addplug", tools=("add",)):
    d = tmp_path / "plugins"
    plug = d / name
    plug.mkdir(parents=True, exist_ok=True)
    (plug / MANIFEST_NAME).write_text(json.dumps({
        "id": name, "name": name, "version": "1.0.0", "schema_version": 1,
        "requires_engine_version": ">=0", "platform": ["any"],
        "entrypoint": "plugin.py", "tools": list(tools), "source": "wiring-test",
    }), encoding="utf-8")
    (plug / "plugin.py").write_text(_ADD_ENTRY, encoding="utf-8")
    return d


def test_wire_plugins_no_env_noop(tmp_path):
    from mcp.server.fastmcp import FastMCP

    from src.plugins import wire_plugins

    assert wire_plugins(FastMCP("x")) is None  # нет MSCODEBASE_PLUGINS_DIR
    assert wire_plugins(FastMCP("x"), plugins_root=tmp_path / "nonexistent") is None


def test_wire_plugins_registers_and_calls(tmp_path):
    from mcp.server.fastmcp import FastMCP

    from src.plugins import PluginRegistry, PluginTrustStore, make_trust_resolver, wire_plugins

    root = _make_plugin_root(tmp_path)
    store = PluginTrustStore(tmp_path / "data" / "plugins" / "trust.json")
    # pre-trust (доверяем хэш через однократную загрузку с auto_approve)
    pre = PluginRegistry(root, store=store,
                         trust_resolver=make_trust_resolver(auto_approve=True),
                         data_root=tmp_path / "data")
    pre.load()
    pre.close()

    mcp = FastMCP("test-wiring")
    reg = wire_plugins(mcp, plugins_root=root, store=store, trust_resolver=None)
    assert reg is not None
    tools = reg.tools()
    assert tools and tools[0]["name"] == "add"
    assert tools[0]["call"](a=2, b=3) == 5
    # registry прикреплён к mcp (subprocess'ы живут весь срок сервера)
    assert getattr(mcp, "_plugin_registry", None) is reg
    reg.close()


def test_wire_plugins_untrusted_skipped(tmp_path):
    from mcp.server.fastmcp import FastMCP

    from src.plugins import PluginTrustStore, wire_plugins

    root = _make_plugin_root(tmp_path)
    store = PluginTrustStore(tmp_path / "data2" / "plugins" / "trust.json")
    # нет pre-trust → default-deny → wire_plugins возвращает None (fail-safe skip)
    assert wire_plugins(FastMCP("x"), plugins_root=root, store=store, trust_resolver=None) is None
