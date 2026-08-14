"""revision_gate.py — min_accepted_revision (TC-9, RFC §3.3): потребитель отвергает replay.

Покрытие: valid (потомок/равенство), invalid (старше, связанные истории),
unknown (несвязанные истории / git-крах — НЕ молчаливый accept), CLI grace.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "revision_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("revision_gate", GATE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=str(ROOT),
        capture_output=True,
        timeout=60,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_ancestor_valid():
    mod = _load_gate()
    with mock.patch.object(mod, "_git", return_value=(0, "")):
        assert mod._is_ancestor("aaa", "bbb", Path(".")) == "valid"


def test_equal_is_valid():
    mod = _load_gate()
    assert mod._is_ancestor("abc123", "abc123", Path(".")) == "valid"


def test_older_related_is_invalid():
    mod = _load_gate()
    # merge-base --is-ancestor: 1 (не предок), но merge-base: 0 (общий предок есть)
    with mock.patch.object(mod, "_git", side_effect=[(1, ""), (0, "common")]):
        assert mod._is_ancestor("aaa", "bbb", Path(".")) == "invalid"


def test_unrelated_is_unknown():
    mod = _load_gate()
    # не предок И общего предка нет → несвязанные истории → UNKNOWN, не INVALID
    with mock.patch.object(mod, "_git", side_effect=[(1, ""), (1, "")]):
        assert mod._is_ancestor("aaa", "bbb", Path(".")) == "unknown"


def test_git_crash_is_unknown():
    mod = _load_gate()
    with mock.patch.object(mod, "_git", return_value=(-1, "CRASH")):
        assert mod._is_ancestor("aaa", "bbb", Path(".")) == "unknown"


def test_cli_grace_when_no_min(tmp_path):
    """Manifest без min_accepted_revision → grace VALID (exit 0), без git."""
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({"version": 1, "guards": []}), encoding="utf-8")
    p = _run("--from-manifest", "--manifest", str(mf))
    assert p.returncode == 0, p.stdout
    assert "grace" in p.stdout


def test_cli_unknown_on_unrelated_shas(tmp_path):
    """Заведомо несвязанные sha (нет в git) → UNKNOWN (exit 2), не accept."""
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({"version": 1, "guards": [], "min_accepted_revision": "a" * 40}), encoding="utf-8")
    p = _run("--from-manifest", "--manifest", str(mf), "--current", "b" * 40)
    assert p.returncode == 2, f"{p.stdout}\n{p.stderr}"
    assert "UNKNOWN" in p.stdout
