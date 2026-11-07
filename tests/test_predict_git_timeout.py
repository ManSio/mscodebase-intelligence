"""predict_change must not wait DEFAULT_TIMEOUT (300 s) on read-only git.

Observation 2026-11-07: `predict_change` timed out at the tool's 120 s budget
while the same `static_predict` took 0.66 s outside the MCP. Read-only git now
gets a 20 s budget with GIT_OPTIONAL_LOCKS=0, so an index lock cannot turn a
preview into a two-minute hang.
"""

from __future__ import annotations

import subprocess

import src.core.change_preview as cp


class _FakeProc:
    last_timeout = None

    def __init__(self, *args, **kwargs):
        self.returncode = 0

    def communicate(self, timeout=None):
        type(self).last_timeout = timeout
        return ("", "")

    def kill(self):  # pragma: no cover
        pass


def _patch(monkeypatch, captured):
    def _factory(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(cp.subprocess, "Popen", _factory)


def test_git_readonly_gets_short_timeout_and_no_index_locks(tmp_path, monkeypatch):
    captured = {}
    _patch(monkeypatch, captured)

    cp._git(tmp_path, "diff", "--name-only", "HEAD")

    assert captured["cmd"][0] == "git"
    assert _FakeProc.last_timeout == 20
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    env = captured["kwargs"]["env"]
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_worktree_calls_keep_a_long_budget(tmp_path, monkeypatch):
    captured = {}
    _patch(monkeypatch, captured)

    cp._git(tmp_path, "worktree", "add", "--detach", "tmp", "HEAD", timeout=120)

    assert _FakeProc.last_timeout == 120
