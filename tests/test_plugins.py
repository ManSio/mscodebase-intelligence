"""Фаза 4 — плагины: trust-гейт, sha256-pin, TOCTOU, self-check, версии, RCE.

Негативные контроли (план §5 DoD):
  - наивная загрузка (без доверия) БЛОКИРУЕТСЯ и код плагина НЕ исполняется (E-01);
  - trust-гейт работает (первый раз — resolver, повтор — без переспроса);
  - sha-drif пользовательского содержимого — переспрос/отказ;
  - TOCTOU (правка между гейтом и импортом) — отказ;
  - несовпадение версии/schema/platform — отказ; self-check — отказ, если не
    зарегистрировал заявленные тулы.
  - happy-path: PoC verify_claim грузится и исполняется.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import __version__ as ENGINE_VERSION
from src.plugins import (
    MANIFEST_NAME,
    PluginLoadError,
    PluginManifestError,
    PluginTrustStore,
    compute_payload_sha256,
    current_platform,
    load_manifest,
    load_plugin,
)
from src.plugins.loader import compute_payload_sha256 as _sha

# ── фикстуры/хелперы ────────────────────────────────────────────────────────

def _plugin_dir(tmp_path: Path, manifest: dict, entry_src: str, name="foo") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    (d / manifest["entrypoint"]).write_text(entry_src, encoding="utf-8")
    return d


def _manifest(**over) -> dict:
    base = {
        "id": "test_plug",
        "name": "Test Plugin",
        "version": "1.0.0",
        "schema_version": 1,
        "requires_engine_version": f">={ENGINE_VERSION}",
        "platform": ["any"],
        "entrypoint": "plugin.py",
        "tools": ["foo"],
        "source": "tests",
    }
    base.update(over)
    return base


_GOOD_ENTRY = (
    "TOOLS = [{'name': 'foo', 'description': 'd', 'handler': lambda x: 'foo:' + str(x)}]\n"
)


# ── manifest / версии / platform ─────────────────────────────────────────────

def test_manifest_requires_missing_fields(tmp_path):
    with pytest.raises(PluginManifestError) as ei:
        load_manifest(tmp_path / "nonexistent.json")
    assert ei.value.kind == "manifest_missing"


def test_manifest_schema_mismatch_real(tmp_path):
    d = _plugin_dir(tmp_path, _manifest(schema_version=99), _GOOD_ENTRY)
    with pytest.raises(PluginManifestError) as ei:
        load_manifest(d / MANIFEST_NAME)
    assert ei.value.kind == "schema_mismatch"


def test_manifest_platform_mismatch(tmp_path):
    d = _plugin_dir(tmp_path, _manifest(platform=["darwin"]), _GOOD_ENTRY)
    if current_platform() != "darwin":
        with pytest.raises(PluginManifestError) as ei:
            load_manifest(d / MANIFEST_NAME)
        assert ei.value.kind == "platform_mismatch"


def test_load_engine_version_mismatch(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(requires_engine_version=">=999.0.0"), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=_approve)
    assert ei.value.kind == "version_mismatch"


def test_load_invalid_engine_req(tmp_path):
    d = _plugin_dir(tmp_path, _manifest(requires_engine_version="not-a-spec!!"), _GOOD_ENTRY)
    with pytest.raises(PluginManifestError) as ei:
        load_manifest(d / MANIFEST_NAME)
    assert ei.value.kind == "engine_req_invalid"


# ── load-гейт / trust / TOCTOU / self-check / RCE ────────────────────────────

@pytest.fixture
def store(tmp_path):
    return PluginTrustStore(tmp_path / "trust.json")


def _approve(manifest, sha, drift):
    return True


def test_naive_load_blocked_and_not_executed(tmp_path, store):
    # RCE негативный контроль (E-01): код плагина НЕ должен исполниться без доверия.
    marker = tmp_path / "pwned"
    malicious = (
        f"open({str(marker)!r}, 'w').write('pwned')\n"
        "TOOLS = [{'name': 'evil', 'description': 'd', 'handler': lambda: 1}]\n"
    )
    d = _plugin_dir(tmp_path, _manifest(tools=["evil"]), malicious, name="evil")
    m = load_manifest(d / MANIFEST_NAME)
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=None)  # default deny
    assert ei.value.kind == "untrusted"
    assert not marker.exists(), "plugin code executed despite being untrusted (RCE!)"


def test_trust_gate_first_time_then_cached(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    calls = []

    def resolver(manifest, sha, drift):
        calls.append(sha)
        return True

    tools = load_plugin(m, d, store, trust_resolver=resolver)
    assert [t["name"] for t in tools] == ["foo"]
    assert len(calls) == 1  # первый раз — resolver
    assert store.is_trusted(m.id, m.version, _sha(d / m.entrypoint))

    # повтор — trust в сторe, резолвер не нужен (resolver=None, но доверено)
    tools2 = load_plugin(m, d, store, trust_resolver=None)
    assert [t2["name"] for t2 in tools2] == ["foo"]


def test_sha_drift_denied_by_default(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    load_plugin(m, d, store, trust_resolver=_approve)  # доверяем текущему хэшу
    # модифицируем entrypoint после доверия
    (d / m.entrypoint).write_text(_GOOD_ENTRY + "# drift\n", encoding="utf-8")
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=None)  # drift + deny
    assert ei.value.kind == "sha_drift"


def test_sha_drift_reapproved_after_prompt(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    load_plugin(m, d, store, trust_resolver=_approve)
    (d / m.entrypoint).write_text(_GOOD_ENTRY + "# x\n", encoding="utf-8")
    calls = []
    tools = load_plugin(m, d, store, trust_resolver=lambda mf, sha, dr: calls.append(dr) or True)
    assert [t["name"] for t in tools] == ["foo"]
    assert calls == [True]  # drift переспрошен, одобрен


def test_toctou_detected(tmp_path, store):
    # resolver модифицирует файл во время гейта → re-hash перед import ≠ sha → отказ
    d = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    entry = d / m.entrypoint

    def sneaky(manifest, sha, drift):
        entry.write_text(_GOOD_ENTRY + "# TOCTOU\n", encoding="utf-8")
        return True

    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=sneaky)
    assert ei.value.kind == "toctou"


def test_selfcheck_fails_when_tool_missing(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(tools=["foo", "bar"]), _GOOD_ENTRY)
    m = load_manifest(d / MANIFEST_NAME)
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=_approve)
    assert ei.value.kind == "selfcheck_failed"


def test_selfcheck_fails_when_no_tools(tmp_path, store):
    d = _plugin_dir(tmp_path, _manifest(tools=["foo"]), "# no TOOLS exported\n")
    m = load_manifest(d / MANIFEST_NAME)
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=_approve)
    assert ei.value.kind == "selfcheck_failed"


def test_entrypoint_missing(tmp_path, store):
    d = tmp_path / "foo"
    d.mkdir(parents=True, exist_ok=True)
    (d / MANIFEST_NAME).write_text(json.dumps(_manifest(entrypoint="nope.py")), encoding="utf-8")
    # nope.py НЕ создаём → entrypoint отсутствует
    m = load_manifest(d / MANIFEST_NAME)
    with pytest.raises(PluginLoadError) as ei:
        load_plugin(m, d, store, trust_resolver=_approve)
    assert ei.value.kind == "entrypoint_missing"


def test_payload_sha_stable(tmp_path):
    d = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY)
    assert compute_payload_sha256(d / "plugin.py") == compute_payload_sha256(d / "plugin.py")
    alt = _plugin_dir(tmp_path, _manifest(), _GOOD_ENTRY + "# change\n", name="foo2")
    assert compute_payload_sha256(d / "plugin.py") != compute_payload_sha256(alt / "plugin.py")


# ── PoC: verify_claim ────────────────────────────────────────────────────────

def test_poc_verify_claim(tmp_path, store):
    poc = Path(__file__).resolve().parent.parent / "examples" / "plugins" / "verify_claim"
    m = load_manifest(poc / MANIFEST_NAME)
    tools = load_plugin(m, poc, store, trust_resolver=_approve)
    assert len(tools) == 1 and tools[0]["name"] == "verify_claim"
    fn = tools[0]["handler"]
    assert fn("alpha", ["alpha beta gamma"]) == "VERIFIED"
    assert fn("delta", ["alpha beta gamma"]) == "REFUTED"
    assert fn("alpha", None) == "UNKNOWN"
