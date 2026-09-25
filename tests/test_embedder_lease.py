"""Guard: cross-process embedder lease prevents idle-unload during indexing.

Context (2026-09-25): the llama.cpp embedder is shared on a fixed port by all
MSCodeBase workspaces. Its idle watchdog unloads it after 120s; a long reindex
parse phase issues no embed calls, so another workspace could grab the port.
The lease marks "embedder in use" so the watchdog skips the unload.

Run: PYTHONPATH=src python -m pytest tests/test_embedder_lease.py -q
"""
from __future__ import annotations

import pytest

from src.core import embedder_lease
from src.providers.reranker import llama_runner


@pytest.fixture()
def lease_tmp(tmp_path, monkeypatch):
    p = tmp_path / "embedder.lease"
    monkeypatch.setattr(embedder_lease, "lease_path", lambda: p)
    return p


def test_touch_makes_lease_active(lease_tmp):
    assert embedder_lease.is_active() is False
    embedder_lease.touch("reindex")
    assert embedder_lease.is_active() is True
    assert lease_tmp.exists()


def test_lease_expires(lease_tmp):
    embedder_lease.touch("reindex")
    assert embedder_lease.is_active(max_age_s=0.0) is False


def test_corrupt_lease_is_inactive_and_never_raises(lease_tmp):
    lease_tmp.write_text("{not json", encoding="utf-8")
    assert embedder_lease.is_active() is False


def test_watchdog_skips_unload_while_lease_active(lease_tmp):
    embedder_lease.touch("reindex")
    assert llama_runner.LlamaRunner._embedder_unload_allowed() is False


def test_watchdog_allows_unload_without_lease(lease_tmp, monkeypatch):
    # Negative control: no lease (and it never existed) -> unload allowed.
    monkeypatch.setattr(
        embedder_lease, "is_active", lambda max_age_s=300.0: False
    )
    assert llama_runner.LlamaRunner._embedder_unload_allowed() is True


def test_unload_allowed_when_lease_module_broken(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("lease unavailable")

    import src.core.embedder_lease as el

    monkeypatch.setattr(el, "is_active", _boom)
    # Must default to True (fail-open to RAM freeing) and never raise.
    assert llama_runner.LlamaRunner._embedder_unload_allowed() is True
