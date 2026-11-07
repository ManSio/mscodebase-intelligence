"""Contradiction-ledger cache (2026-11-07).

Полная проверка на старте MCP занимала ~2.5 мин и насыщала диск так, что
health-проба `git log` таймаутила. Результат кэшируется по (mtime/size/sha
дневника + HEAD): при неизменном дневнике повторный старт не перепроверяет.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_diary.py"
_spec = importlib.util.spec_from_file_location("verify_diary_cache_under_test", _SCRIPT)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def _setup(tmp_path, monkeypatch):
    diary = tmp_path / "AGENT_DIARY.md"
    diary.write_text("# diary\n\n## [2026-11-01] — x\n", encoding="utf-8")
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "DIARY", diary)
    calls = {"n": 0}

    def fake_verify(entries):
        calls["n"] += 1
        return (3, 0, [])

    monkeypatch.setattr(verify, "run_verification", fake_verify)
    return diary, calls


def test_second_run_is_served_from_cache(tmp_path, monkeypatch):
    diary, calls = _setup(tmp_path, monkeypatch)

    first = verify.run_contradiction_ledger()
    assert first.get("cached") is not True
    assert calls["n"] == 1

    second = verify.run_contradiction_ledger()
    assert second.get("cached") is True
    assert calls["n"] == 1
    assert second["discrepancies"] == 0


def test_diary_change_invalidates_cache(tmp_path, monkeypatch):
    diary, calls = _setup(tmp_path, monkeypatch)

    verify.run_contradiction_ledger()
    assert calls["n"] == 1

    diary.write_text(diary.read_text(encoding="utf-8") + "\nnew line\n", encoding="utf-8")
    third = verify.run_contradiction_ledger()
    assert third.get("cached") is not True
    assert calls["n"] == 2
