"""Guard for the reindex failure ledger + zombie watchdog (2026-09-25).

Incident: full-reindex job e4977ded was found as a *zombie* — job.status
"running", but py-spy showed no worker thread and no progress; the driving
coroutine never reached its `finally`, so nothing was recorded and the cause
had to be guessed. These tests prove the fix actually fails when the guard is
absent (negative control) and stays quiet for a healthy job.

Run: PYTHONPATH=src python -m pytest tests/test_reindex_ledger.py -q
"""
from __future__ import annotations

import pytest

from src.core import reindex_ledger
from src.core.intelligence import layer as layer_mod
from src.core.intelligence.jobs import job_manager


@pytest.fixture()
def ledger_tmp(tmp_path, monkeypatch):
    p = tmp_path / "reindex_ledger.jsonl"

    monkeypatch.setattr(reindex_ledger, "ledger_path", lambda: p)
    return p


def _fake_layer(*, progress_age_s: float, task_done):
    """Minimal stand-in exposing only what _watchdog_reindex touches."""
    class _Task:
        def __init__(self, done):
            self._done = done

        def done(self):
            return self._done

    obj = object.__new__(layer_mod.ProjectIntelligenceLayer)
    obj._reindex_job_id = job_manager.create_job("full_reindex")
    job = job_manager.get_job(obj._reindex_job_id)
    job.status = "running"
    job.progress = 0.52
    obj._reindex_task = None if task_done is None else _Task(task_done)
    obj._reindex_last_progress_ts = __import__("time").time() - progress_age_s
    return obj, job


def test_record_writes_jsonl(ledger_tmp):
    reindex_ledger.record("start", job_id="abc", project="X")
    reindex_ledger.record("error", job_id="abc", error="Boom: nope")
    lines = ledger_tmp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"event": "start"' in lines[0]
    assert "Boom: nope" in lines[1]


def test_record_never_raises_on_bad_path(monkeypatch):
    def _boom():
        raise RuntimeError("no path")

    monkeypatch.setattr(reindex_ledger, "ledger_path", _boom)
    # Must not raise even though path resolution fails.
    reindex_ledger.record("start", job_id="x")


def test_exception_fields_capture_traceback():
    try:
        raise ValueError("deep failure")
    except ValueError as e:
        fields = reindex_ledger.exception_fields(e)
    assert "ValueError: deep failure" in fields["error"]
    assert "Traceback" in fields["traceback"]


def test_watchdog_terminalises_zombie_task_done(ledger_tmp):
    # NEGATIVE CONTROL: with the guard absent this stays "running" forever.
    obj, job = _fake_layer(progress_age_s=1.0, task_done=True)
    job_manager.jobs[job.job_id] = job
    layer_mod.ProjectIntelligenceLayer._watchdog_reindex(obj)
    assert job.status == "failed"
    assert obj._reindex_job_id is None
    assert "zombie" in ledger_tmp.read_text(encoding="utf-8")


def test_watchdog_terminalises_stall(ledger_tmp, monkeypatch):
    monkeypatch.setattr(
        layer_mod.ProjectIntelligenceLayer, "_REINDEX_STALL_SEC", 10.0
    )
    obj, job = _fake_layer(progress_age_s=999.0, task_done=False)
    layer_mod.ProjectIntelligenceLayer._watchdog_reindex(obj)
    assert job.status == "failed"
    assert "no progress" in (job.error or "")


def test_watchdog_leaves_healthy_job_alone(ledger_tmp):
    # Positive control: recent progress + task still running -> untouched.
    obj, job = _fake_layer(progress_age_s=1.0, task_done=False)
    layer_mod.ProjectIntelligenceLayer._watchdog_reindex(obj)
    assert job.status == "running"
    assert obj._reindex_job_id == job.job_id
    assert not ledger_tmp.exists() or "zombie" not in ledger_tmp.read_text("utf-8")
