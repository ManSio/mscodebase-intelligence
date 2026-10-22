"""Tests for embedder_lease ref-count mechanism.

Validates that acquire/release track per-PID ref-counts correctly,
is_active reflects ref-count state, and stale leases expire.
"""
from __future__ import annotations

import os
import time

import pytest

from src.core import embedder_lease


def _cleanup(*pids: int) -> None:
    for p in pids:
        embedder_lease.release(p)


@pytest.fixture(autouse=True)
def _clear_lease():
    """Clear the lease file before each test for isolation."""
    data = embedder_lease.holder()
    if data and isinstance(data, dict):
        for key in list(data.get("pids", {}).keys()):
            try:
                embedder_lease.release(int(key))
            except (ValueError, TypeError):
                pass
    yield
    # Also clean up after
    data = embedder_lease.holder()
    if data and isinstance(data, dict):
        for key in list(data.get("pids", {}).keys()):
            try:
                embedder_lease.release(int(key))
            except (ValueError, TypeError):
                pass


def test_acquire_release_increments_decrements_refcount():
    """acquire bumps count, release decrements; is_active follows."""
    pid = 99991
    _cleanup(pid)
    assert not embedder_lease.is_active(max_age_s=300)

    embedder_lease.acquire(pid, "test")
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.acquire(pid, "test2")  # count = 2
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.release(pid)  # count = 1
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.release(pid)  # count = 0
    assert not embedder_lease.is_active(max_age_s=300)


def test_multiple_pids_tracked_independently():
    """Two PIDs acquiring independently; releasing one doesn't affect the other."""
    pid_a, pid_b = 99992, 99993
    _cleanup(pid_a, pid_b)

    embedder_lease.acquire(pid_a, "a")
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.acquire(pid_b, "b")
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.release(pid_a)  # a released, b still active
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.release(pid_b)  # b released, none active
    assert not embedder_lease.is_active(max_age_s=300)


def test_stale_lease_expires():
    """is_active returns False after max_age_s even with a non-zero count."""
    pid = 99994
    _cleanup(pid)

    embedder_lease.acquire(pid, "stale")
    # Manually set ts to the past
    data = embedder_lease.holder() or {}
    pids = data.get("pids", {})
    pids[str(pid)]["ts"] = time.time() - 600  # 10 min ago
    embedder_lease._save(data)

    assert not embedder_lease.is_active(max_age_s=300)


def test_touch_backward_compatible():
    """touch() (deprecated) acquires one ref-count for current PID."""
    pid = os.getpid()
    _cleanup(pid)
    assert not embedder_lease.is_active(max_age_s=300)

    embedder_lease.touch("legacy")
    assert embedder_lease.is_active(max_age_s=300)

    embedder_lease.release(pid)
    assert not embedder_lease.is_active(max_age_s=300)


def test_holder_returns_lease_data():
    """holder() returns the lease dict or empty when no active PIDs."""
    pid = 99995
    _cleanup(pid)
    data = embedder_lease.holder()
    assert data is not None
    assert data.get("pids", {}) == {}

    embedder_lease.acquire(pid, "diag")
    data = embedder_lease.holder()
    assert data is not None
    assert "pids" in data
    assert str(pid) in data["pids"]

    embedder_lease.release(pid)
