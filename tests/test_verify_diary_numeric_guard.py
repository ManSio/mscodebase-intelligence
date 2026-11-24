"""Регресс: числовые токены дневника не должны спавнить `git cat-file`.

Инцидент 2026-11-15: на каждом старте MCP Contradiction Ledger проверял
AGENT_DIARY.md, и каждая дата/run-ID (`20261021`, `43092017919`) шла в
`check_commit_exists` → `git cat-file -t` с retry. Десятки процессов, вспышки
консоли на Windows, при том что цифровой guard всё равно возвращал True.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import verify_diary  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(verify_diary, "_COMMIT_CACHE", {})
    monkeypatch.setattr(verify_diary, "_GIT_UNAVAILABLE", False)


def test_numeric_token_does_not_spawn_git(monkeypatch):
    calls: list[object] = []

    def spy(args, *a, **k):
        calls.append(args)
        raise AssertionError("git must not be spawned for a numeric token")

    monkeypatch.setattr(verify_diary.subprocess, "Popen", spy)
    assert verify_diary.check_commit_exists("20261021") is True
    assert verify_diary.check_commit_exists("43092017919") is True
    assert calls == []


def test_hex_token_still_uses_git(monkeypatch):
    """Позитивный контроль: настоящий hex-токен по-прежнему проверяется."""
    seen: list[object] = []

    class FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return (b"commit", b"")

        def kill(self):
            pass

    def fake_popen(args, *a, **k):
        seen.append(args)
        return FakeProc()

    monkeypatch.setattr(verify_diary.subprocess, "Popen", fake_popen)
    assert verify_diary.check_commit_exists("98ab421c") is True
    assert seen, "hex-токен обязан попасть в git cat-file"


def test_cached_result_skips_spawn(monkeypatch):
    verify_diary._COMMIT_CACHE["abcdef12"] = True

    def spy(args, *a, **k):
        raise AssertionError("cache must short-circuit")

    monkeypatch.setattr(verify_diary.subprocess, "Popen", spy)
    assert verify_diary.check_commit_exists("abcdef12") is True
