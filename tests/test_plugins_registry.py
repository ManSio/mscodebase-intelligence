"""Фаза 4 — MCP-proxy wiring (registry), trust-гейт UX (prompt), dependencies.

End-to-end: хост PluginRegistry → preauthorize (без exec) → runner-subprocess →
proxy call → результат. Тулы плагина из examples/plugins (реальный PoC verify_claim).
"""
from __future__ import annotations

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
