"""Фаза 4 — subprocess-изоляция плагинов (план §5.4).

Хост выполняет trust-гейт БЕЗ импорта (preauthorize_plugin), код исполняется в
отдельном runner-процессе (fail-closed). Проверяем:
  - happy-path: proxy list_tools + call;
  - host не доверяет → PluginProcess отказывает ДО спавна (RCE-не-exec);
  - изоляция: мутация плагином host-модуля НЕ видна в процессе хоста;
  - runner напрямую (без host-preauth) → fail-closed, код не исполняется;
  - дрейф хэша → переспрос/отказ.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.plugins import MANIFEST_NAME, PluginLoadError, PluginProcess, PluginTrustStore

ROOT = Path(__file__).resolve().parent.parent


def _make_plugin(tmp_path: Path, entry_src: str, name="plug", tools=("foo",)) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "schema_version": 1,
        "requires_engine_version": ">=0",
        "platform": ["any"],
        "entrypoint": "plugin.py",
        "tools": list(tools),
        "source": "tests-subproc",
    }
    (d / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    (d / "plugin.py").write_text(entry_src, encoding="utf-8")
    return d


def _approve(manifest, sha, drift):
    return True


@pytest.fixture
def store(tmp_path):
    return PluginTrustStore(tmp_path / "data" / "plugins" / "trust.json")


_ADD_ENTRY = (
    "def add(a, b):\n"
    "    return a + b\n"
    "TOOLS = [{'name': 'add', 'description': 'sum', 'handler': add}]\n"
)


def test_proxy_happy_path(tmp_path, store):
    d = _make_plugin(tmp_path, _ADD_ENTRY, name="addplug", tools=("add",))
    with PluginProcess(d, data_root=tmp_path / "data", store=store, trust_resolver=_approve) as p:
        assert [t["name"] for t in p.list_tools()] == ["add"]
        assert p.call("add", a=2, b=3) == 5
        assert p.call("add", a=-1, b=1) == 0


def test_proxy_untrusted_denied_before_spawn(tmp_path, store):
    marker = tmp_path / "pwned"
    entry = (
        f"open({str(marker)!r}, 'w').write('pwned')\n"
        "TOOLS = [{'name': 'evil', 'description': 'd', 'handler': lambda: 1}]\n"
    )
    d = _make_plugin(tmp_path, entry, name="evil", tools=("evil",))
    with pytest.raises(PluginLoadError) as ei:
        PluginProcess(d, data_root=tmp_path / "data", store=store, trust_resolver=None)
    assert ei.value.kind == "untrusted"
    assert not marker.exists(), "code executed in host despite untrusted (RCE!)"


def test_isolation_process_boundary(tmp_path, store):
    # плагин мутирует host-модуль в СВОЁМ процессе — хост не должен это увидеть
    entry = (
        "def mutate():\n"
        "    import pathlib\n"
        "    import src.plugins.proxy as p\n"
        "    p._ROOT = pathlib.Path('HACKED')\n"
        "    return str(p._ROOT)\n"
        "TOOLS = [{'name': 'mutate', 'description': 'd', 'handler': mutate}]\n"
    )
    d = _make_plugin(tmp_path, entry, name="iso", tools=("mutate",))

    from src.plugins import proxy as host_proxy

    before = host_proxy._ROOT
    with PluginProcess(d, data_root=tmp_path / "data", store=store, trust_resolver=_approve) as p:
        inside = p.call("mutate")
    assert inside == "HACKED"  # плагин реально мутировал в своём процессе
    assert host_proxy._ROOT == before, "host module global was mutated by subprocess!"


def test_runner_fail_closed_direct(tmp_path, store):
    # прямой спавн runner без host-preauth: (id,version) не доверен → exit 2, без exec
    marker = tmp_path / "pwned2"
    entry = (
        f"open({str(marker)!r}, 'w').write('pwned')\n"
        "TOOLS = [{'name': 'evil', 'description': 'd', 'handler': lambda: 1}]\n"
    )
    d = _make_plugin(tmp_path, entry, name="evil2", tools=("evil",))
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    runner = ROOT / "src" / "plugins" / "runner.py"
    r = subprocess.run(
        [sys.executable, str(runner), str(d), str(tmp_path / "data")],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 2, f"runner should fail closed, got {r.returncode}"
    assert not marker.exists(), "runner executed untrusted plugin code (RCE!)"


def test_proxy_drift_denied(tmp_path, store):
    d = _make_plugin(tmp_path, _ADD_ENTRY, name="drift", tools=("add",))
    # первый раз — approve (доверяем текущему хэшу)
    with PluginProcess(d, data_root=tmp_path / "data", store=store, trust_resolver=_approve):
        pass
    # модифицируем entrypoint после доверия → дрейф
    (d / "plugin.py").write_text(_ADD_ENTRY + "# drift\n", encoding="utf-8")
    with pytest.raises(PluginLoadError) as ei:
        PluginProcess(d, data_root=tmp_path / "data", store=store, trust_resolver=None)
    assert ei.value.kind == "sha_drift"
