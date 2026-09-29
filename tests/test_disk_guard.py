"""Unit tests for scripts/disk_guard.py.

All fixtures live in tmp_path — never touches real TEMP/opencode or the repo.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from disk_guard import (  # noqa: E402
    SweepStats,
    rotate_repo_logs,
    sweep_experiment_work,
    sweep_temp_opencode,
)


def _old(path: Path, days: float = 10) -> Path:
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_temp_ttl_deletes_allowlisted_old_backup(tmp_path: Path) -> None:
    backup = tmp_path / "backup_test_20200101"
    backup.mkdir()
    (backup / "f.txt").write_text("x")
    _old(backup / "f.txt", 10)
    _old(backup, 10)
    stats = SweepStats()
    sweep_temp_opencode(tmp_path, 7, stats, dry_run=False)
    assert not backup.exists()
    assert stats.deleted_files == 1


def test_temp_ttl_keeps_fresh_and_non_allowlisted(tmp_path: Path) -> None:
    fresh = tmp_path / "backup_fresh"
    fresh.mkdir()
    (fresh / "f.txt").write_text("x")  # fresh mtime
    db = tmp_path / "important.db"
    db.write_bytes(b"\0" * 1024)  # small so not big-ticket
    stats = SweepStats()
    sweep_temp_opencode(tmp_path, 7, stats, dry_run=False)
    assert fresh.exists()
    assert db.exists()
    assert stats.deleted_files == 0


def test_temp_reports_big_unknown_file(tmp_path: Path) -> None:
    big = tmp_path / "mystery.bin"
    big.write_bytes(b"\0" * 2 * 1024 * 1024)
    import disk_guard

    old_limit, disk_guard.REPORT_ONLY_ABOVE_MB = disk_guard.REPORT_ONLY_ABOVE_MB, 1
    try:
        stats = SweepStats()
        sweep_temp_opencode(tmp_path, 7, stats, dry_run=False)
    finally:
        disk_guard.REPORT_ONLY_ABOVE_MB = old_limit
    assert big.exists()  # never auto-deleted
    assert len(stats.reported_big) == 1


def test_temp_ttl_deletes_stale_pytest_worker_dir(tmp_path: Path) -> None:
    worker = tmp_path / "pytest-of-misha"
    worker.mkdir()
    (worker / "tokenizer.json").write_bytes(b"\0" * 64)
    _old(worker / "tokenizer.json", 10)
    _old(worker, 10)
    stats = SweepStats()
    sweep_temp_opencode(tmp_path, 7, stats, dry_run=False)
    assert not worker.exists()


def test_temp_dry_run_deletes_nothing(tmp_path: Path) -> None:
    log = tmp_path / "stale.log"
    log.write_text("x")
    _old(log, 10)
    stats = SweepStats()
    sweep_temp_opencode(tmp_path, 7, stats, dry_run=True)
    assert log.exists()
    assert stats.deleted_files == 1  # counted, not removed


def test_log_rotation_keeps_one_backup(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"\0" * 6 * 1024 * 1024)
    stats = SweepStats()
    rotate_repo_logs(tmp_path, stats, dry_run=False)
    assert stats.rotated_logs == 1
    assert log.exists() and log.stat().st_size == 0
    assert log.with_suffix(".log.1").stat().st_size == 6 * 1024 * 1024


def test_log_rotation_skips_small_logs(tmp_path: Path) -> None:
    log = tmp_path / "small.log"
    log.write_text("tiny")
    stats = SweepStats()
    rotate_repo_logs(tmp_path, stats, dry_run=False)
    assert stats.rotated_logs == 0
    assert log.read_text() == "tiny"


def test_work_ttl_respects_frozen_and_results(tmp_path: Path) -> None:
    exp = tmp_path / "experiments" / "e1"
    work = exp / "work"
    work.mkdir(parents=True)
    stale = work / "ctx.txt"
    stale.write_text("old")
    _old(stale, 40)
    frozen = work / "frozen" / "keep.txt"
    frozen.parent.mkdir()
    frozen.write_text("keep")
    _old(frozen, 40)
    results = exp / "results" / "work" / "r.txt"  # protected path hint
    results.parent.mkdir(parents=True)
    results.write_text("keep")
    stats = SweepStats()
    sweep_experiment_work(tmp_path, 30, stats, dry_run=False)
    assert not stale.exists()
    assert frozen.exists()
    assert results.exists()
