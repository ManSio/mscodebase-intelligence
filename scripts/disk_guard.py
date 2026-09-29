#!/usr/bin/env python3
"""Disk guard — self-cleaning mechanism for regenerable trash.

Covers the 2026-09-29 C:-critical incident (182MB free): TEMP/opencode
experiment DBs + logs, __pycache__, and stale experiment work dirs grow
unbounded without any TTL. This script enforces caps/TTL and fails CI
when the system drive is nearly full.

Usage:
    python scripts/disk_guard.py --check [--min-free-gb 1]
    python scripts/disk_guard.py --clean [--dry-run] [--temp-ttl-days 7]
                                 [--work-ttl-days 30] [--repo ROOT]
    python scripts/disk_guard.py --report  # top hogs, never deletes

Exit codes: 0 = ok/cleaned, 1 = low disk (--check) or errors, 2 = bad args.

NEVER deletes (only reports): *.gguf models, venvs, lancedb tables,
.git, source files, committed experiment artifacts (results/, frozen/).
Deletion allowlist: backup_*, tool-output*, *.log[.N], *.err*, pytest_*.txt
in TEMP/opencode; *.log rotation in repo; experiments/**/work TTL.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Deletion allowlist inside TEMP/opencode (name patterns only).
TEMP_TRASH_PATTERNS = (
    "backup_*",
    "tool-output*",
    "*.log",
    "*.log.*",
    "*.err*",
    "pytest_*.txt",
)

# Big unknown files are reported, never auto-deleted.
REPORT_ONLY_ABOVE_MB = 100

LOG_ROTATE_ABOVE_MB = 5  # repo *.log larger than this -> keep one .1 backup
WORK_DIRNAME = "work"  # experiments/**/work
PROTECTED_DIR_HINTS = ("frozen", "results")  # never touch under these


@dataclass
class SweepStats:
    deleted_files: int = 0
    deleted_bytes: int = 0
    rotated_logs: int = 0
    errors: list[str] = field(default_factory=list)
    reported_big: list[str] = field(default_factory=list)


def _older_than(path: Path, days: float, now: float) -> bool:
    try:
        return (now - path.stat().st_mtime) > days * 86400
    except OSError:
        return False


def _rmtree_or_file(path: Path, stats: SweepStats, dry_run: bool) -> None:
    try:
        if dry_run:
            size = (
                sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
                if path.is_dir()
                else path.stat().st_size
            )
            stats.deleted_bytes += size
            stats.deleted_files += 1
            return
        if path.is_dir() and not path.is_symlink():
            stats.deleted_bytes += sum(
                p.stat().st_size for p in path.rglob("*") if p.is_file()
            )
            shutil.rmtree(path)
        else:
            stats.deleted_bytes += path.stat().st_size
            path.unlink()
        stats.deleted_files += 1
    except OSError as exc:
        stats.errors.append(f"{path}: {exc}")


def sweep_temp_opencode(
    temp_root: Path, ttl_days: float, stats: SweepStats, dry_run: bool
) -> None:
    """Delete allowlisted trash older than ttl; report big unknown files."""
    now = time.time()
    if not temp_root.is_dir():
        return
    for entry in temp_root.iterdir():
        try:
            if entry.is_file():
                matched = any(
                    fnmatch.fnmatch(entry.name, pat) for pat in TEMP_TRASH_PATTERNS
                )
                size_mb = entry.stat().st_size / (1024 * 1024)
                if matched and _older_than(entry, ttl_days, now):
                    _rmtree_or_file(entry, stats, dry_run)
                elif size_mb >= REPORT_ONLY_ABOVE_MB:
                    stats.reported_big.append(
                        f"{size_mb:.1f}MB {entry} (not allowlisted — owner decision)"
                    )
            elif entry.is_dir():
                if any(
                    fnmatch.fnmatch(entry.name, pat)
                    for pat in ("backup_*", "tool-output*")
                ) and _older_than(entry, ttl_days, now):
                    _rmtree_or_file(entry, stats, dry_run)
        except OSError as exc:
            stats.errors.append(f"{entry}: {exc}")


def rotate_repo_logs(repo: Path, stats: SweepStats, dry_run: bool) -> None:
    """Repo *.log > LOG_ROTATE_ABOVE_MB: move to .1 (drop old .1), keep live file."""
    for log in repo.rglob("*.log"):
        if ".git" in log.parts or "venv" in log.parts or "node_modules" in log.parts:
            continue
        try:
            if log.stat().st_size > LOG_ROTATE_ABOVE_MB * 1024 * 1024:
                backup = log.with_suffix(log.suffix + ".1")
                if not dry_run:
                    if backup.exists():
                        backup.unlink()
                    log.rename(backup)
                    log.touch()
                stats.rotated_logs += 1
        except OSError as exc:
            stats.errors.append(f"{log}: {exc}")


def sweep_experiment_work(
    repo: Path, ttl_days: float, stats: SweepStats, dry_run: bool
) -> None:
    """Delete files under experiments/**/work older than ttl.

    Never descends into frozen/ or results/ dirs. Removes dirs that become empty.
    """
    now = time.time()
    exp_root = repo / "experiments"
    if not exp_root.is_dir():
        return
    for work in exp_root.rglob(WORK_DIRNAME):
        if not work.is_dir():
            continue
        if any(hint in work.parts for hint in PROTECTED_DIR_HINTS):
            continue
        for path in sorted(work.rglob("*"), reverse=True):
            rel = path.relative_to(work)
            if rel.parts and rel.parts[0] in PROTECTED_DIR_HINTS:
                continue
            try:
                if path.is_file() and _older_than(path, ttl_days, now):
                    _rmtree_or_file(path, stats, dry_run)
                elif path.is_dir() and not any(path.iterdir()):
                    if not dry_run:
                        path.rmdir()
            except OSError as exc:
                stats.errors.append(f"{path}: {exc}")


def free_mb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 * 1024)


def top_hogs(root: Path, limit: int = 10) -> list[tuple[float, str]]:
    try:
        entries = [
            e
            for e in root.iterdir()
            if not e.is_symlink() or e.is_dir()
        ]
    except OSError:
        return []
    rows: list[tuple[float, str]] = []
    for entry in entries:
        try:
            if entry.is_file():
                rows.append((entry.stat().st_size / (1024 * 1024), str(entry)))
            elif entry.is_dir():
                total = sum(
                    p.stat().st_size
                    for p in entry.rglob("*")
                    if p.is_file()
                )
                rows.append((total / (1024 * 1024), str(entry)))
        except OSError:
            continue
    return sorted(rows, reverse=True)[:limit]


def default_temp_root() -> Path:
    return Path(os.environ.get("TEMP", os.environ.get("TMP", r"C:\Temp"))) / "opencode"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if system drive free < threshold")
    ap.add_argument("--clean", action="store_true", help="apply TTL/caps cleanup")
    ap.add_argument("--report", action="store_true", help="print top hogs, delete nothing")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-free-gb", type=float, default=1.0)
    ap.add_argument("--temp-ttl-days", type=float, default=7.0)
    ap.add_argument("--work-ttl-days", type=float, default=30.0)
    ap.add_argument("--repo", type=Path, default=PROJECT_ROOT)
    ap.add_argument("--temp-root", type=Path, default=default_temp_root())
    ap.add_argument("--report-limit", type=int, default=10)
    args = ap.parse_args(argv)

    if not (args.check or args.clean or args.report):
        ap.error("one of --check/--clean/--report is required")

    rc = 0
    if args.check or args.clean:
        anchors = {"repo": args.repo.resolve(), "temp": args.temp_root}
        for label, anchor in anchors.items():
            free_gb = shutil.disk_usage(os.fspath(anchor)).free / (1024**3)
            print(f"Free [{label}] {anchor}: {free_gb:.2f}GB (min {args.min_free_gb}GB)")
            if free_gb < args.min_free_gb:
                print(f"FAIL [{label}]: free space {free_gb:.2f}GB < {args.min_free_gb}GB minimum")
                rc = 1
        if args.check:
            return rc

    if args.report or args.clean:
        for root in (args.temp_root, args.repo):
            print(f"--- top hogs under {root} ---")
            for mb, path in top_hogs(root, args.report_limit):
                print(f"{mb:10.1f}MB  {path}")

    if args.clean:
        stats = SweepStats()
        sweep_temp_opencode(args.temp_root, args.temp_ttl_days, stats, args.dry_run)
        rotate_repo_logs(args.repo, stats, args.dry_run)
        sweep_experiment_work(args.repo, args.work_ttl_days, stats, args.dry_run)
        print(
            f"{'Would delete' if args.dry_run else 'Deleted'}: "
            f"{stats.deleted_files} entries, {stats.deleted_bytes / (1024 * 1024):.1f}MB; "
            f"rotated logs: {stats.rotated_logs}"
        )
        for line in stats.reported_big:
            print(f"BIG-TICKET (left for owner): {line}")
        for err in stats.errors:
            print(f"ERROR: {err}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
