"""Execution-contract git probe: Popen+communicate, not check_output.

Regression 2026-11-07: on Windows the probe ran `subprocess.check_output` inside
a ThreadPoolExecutor thread while the MCP process had its stdout redirected to
the JSON-RPC pipe. Reading the child's pipe deadlocked (AGENTS.md §5.16), so
every health report carried "Git операция не удалась: Функция превысила таймаут
15 секунд" while `git log -1` itself took 40 ms by hand.

The tests use a fake spawner: the property under test is WHICH API is used and
how the timeout is handled, not what git prints.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import src.core.intelligence.health as health_mod
from src.core.intelligence.health import HealthReport


class _OkPopen:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.timeout = None

    def communicate(self, timeout=None):
        self.timeout = timeout
        return (b"abc1234 subject line\n", b"")

    def kill(self):  # pragma: no cover — must not be called on success
        raise AssertionError("kill() called on a successful probe")


class _SlowPopen:
    def __init__(self, *args, **kwargs):
        self.killed = False
        self._first = True

    def communicate(self, timeout=None):
        if self._first:
            self._first = False
            raise subprocess.TimeoutExpired(cmd="git", timeout=timeout)
        return (b"", b"")

    def kill(self):
        self.killed = True


def test_probe_uses_communicate_with_inner_timeout(tmp_path, monkeypatch):
    spawned = {}

    def _factory(*args, **kwargs):
        spawned["proc"] = _OkPopen(*args, **kwargs)
        return spawned["proc"]

    monkeypatch.setattr(health_mod.subprocess, "Popen", _factory)
    report = HealthReport(project_path=Path(tmp_path))
    report._check_execution_contract()

    assert spawned["proc"].kwargs.get("stdout") is subprocess.PIPE
    assert spawned["proc"].timeout == 10  # < внешнего бюджета 15s (нет гонки)
    assert report.metrics.get("last_commit") == "abc1234 subject line"
    assert not [w for w in report.warnings if w["component"] == "execution_contract"]


def test_probe_kills_the_child_on_timeout(tmp_path, monkeypatch):
    proc = _SlowPopen()

    monkeypatch.setattr(health_mod.subprocess, "Popen", lambda *a, **k: proc)
    report = HealthReport(project_path=Path(tmp_path))
    report._check_execution_contract()

    assert proc.killed is True
    assert any(
        w["component"] == "execution_contract" and "таймаут" in w["message"].lower()
        for w in report.warnings
    )
