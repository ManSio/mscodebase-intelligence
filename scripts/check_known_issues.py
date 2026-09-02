#!/usr/bin/env python
"""Pre-commit guard for KNOWN_ISSUES.md (§4.8 protocol).

Checks:
  R1 — File size ≤ 300 lines.
  R2 — Entries older than one calendar month are archived
       under docs/archive/KNOWN_ISSUES_YYYY_MM.md.

Exit codes:
  0 — All checks passed.
  1 — One or more violations detected (message printed to stderr).
"""

import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_LINES = 300
ARCHIVE_DIR_NAME = "docs/archive"
ARCHIVE_FILE_PREFIX = "KNOWN_ISSUES_"
ARCHIVE_FILE_SUFFIX = ".md"

# Regex that matches an entry line like:
# - [🟡 ...] Text … 2026-07-20 …
# - [FIXED] Text … 2026-08-03 …
# - ## 2026-07-20 — Some text
# We look for YYYY-MM-DD patterns inside each non-empty, non-header line.
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Patterns that signal an *archived* file (not the live file):
ARCHIVE_HEADER_RE = re.compile(r"^#\s+KNOWN\s+ISSUES.*?(\d{4})_(\d{2})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_project_root() -> Path:
    """Return the project root (directory containing KNOWN_ISSUES.md)."""
    candidates = [Path.cwd()] + list(Path.cwd().parents)
    for candidate in candidates:
        if (candidate / "KNOWN_ISSUES.md").is_file():
            return candidate
    print(
        "ERROR: Cannot find KNOWN_ISSUES.md — run from project root.",
        file=sys.stderr,
    )
    sys.exit(1)


def extract_dates_from_line(line: str) -> list[str]:
    """Return all YYYY-MM-DD strings found in *line*."""
    return DATE_RE.findall(line)


def parse_archive_month(filepath: Path) -> tuple[int, int] | None:
    """Try to extract YYYY, MM from an archive filename/header.

    Returns (year, month) or None if it cannot be determined.
    Prefers header parsing (more reliable for renamed files).
    """
    # Try header first
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            first_line = fh.readline()
        m = ARCHIVE_HEADER_RE.search(first_line)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass

    # Fallback: parse from filename KNOWN_ISSUES_YYYY_MM.md
    stem = filepath.stem  # e.g. "KNOWN_ISSUES_2026_07"
    parts = stem.split("_")
    if len(parts) >= 3:
        try:
            return int(parts[-2]), int(parts[-1])
        except ValueError:
            pass
    return None


def get_current_year_month() -> tuple[int, int]:
    now = datetime.now()
    return now.year, now.month


def get_previous_months(months_back: int = 2) -> set[tuple[int, int]]:
    """Return a set of (year, month) tuples for the last N months."""
    result: set[tuple[int, int]] = set()
    y, m = get_current_year_month()
    for i in range(months_back + 1):
        # Go backwards
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        result.add((yy, mm))
    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_size(project_root: Path) -> list[str]:
    """R1: KNOWN_ISSUES.md must not exceed MAX_LINES lines."""
    issues: list[str] = []
    ki_path = project_root / "KNOWN_ISSUES.md"

    try:
        with open(ki_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        issues.append("KNOWN_ISSUES.md not found.")
        return issues

    total_lines = len(lines)
    if total_lines > MAX_LINES:
        issues.append(
            f"R1 VIOLATION: KNOWN_ISSUES.md has {total_lines} lines "
            f"(max allowed: {MAX_LINES}). "
            f"§4.8 R4 requires monthly archival when exceeding this limit."
        )

    return issues


def check_archival(project_root: Path) -> list[str]:
    """R2: Entries older than one calendar month must be in an archive file."""
    issues: list[str] = []
    ki_path = project_root / "KNOWN_ISSUES.md"
    archive_dir = project_root / ARCHIVE_DIR_NAME

    # Collect existing archive months
    archive_months: set[tuple[int, int]] = set()
    if archive_dir.is_dir():
        for fpath in archive_dir.iterdir():
            if fpath.is_file() and fpath.name.startswith(ARCHIVE_FILE_PREFIX):
                parsed = parse_archive_month(fpath)
                if parsed:
                    archive_months.add(parsed)

    current_ym = get_current_year_month()
    previous_ym = get_previous_months(months_back=2)  # include last 2 months safety margin

    # Read all dates from the live file
    try:
        with open(ki_path, "r", encoding="utf-8") as fh:
            content_lines = fh.readlines()
    except FileNotFoundError:
        return issues  # already reported by check_size

    # Track which old months appear in the live file
    months_in_live: set[tuple[int, int]] = set()

    for line in content_lines:
        stripped = line.strip()
        # Skip empty lines, separators, headers, metadata lines
        if not stripped:
            continue
        if stripped.startswith("---"):
            continue
        if stripped.startswith("> "):  # blockquote metadata
            continue
        if stripped.startswith("# "):  # main title
            continue
        if stripped.startswith("**") and "entries" in stripped.lower():
            continue  # summary line like "**153 entries**"

        dates = extract_dates_from_line(stripped)
        for date_str in dates:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                ym = (dt.year, dt.month)
                # If the date is strictly older than last month → needs archive
                if ym < current_ym and ym not in archive_months:
                    months_in_live.add(ym)
            except ValueError:
                continue

    if months_in_live:
        for ym in sorted(months_in_live):
            issues.append(
                f"R2 VIOLATION: Entries dated {ym[0]}-{ym[1]:02d} exist in "
                f"live KNOWN_ISSUES.md but no archive file "
                f"{ARCHIVE_FILE_PREFIX}{ym[0]}_{ym[1]:02d}{ARCHIVE_FILE_SUFFIX} "
                f"found in {archive_dir}/. "
                f"§4.8 R4 requires monthly archival."
            )

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    project_root = find_project_root()

    all_issues: list[str] = []
    all_issues.extend(check_size(project_root))
    all_issues.extend(check_archival(project_root))

    if all_issues:
        print("\n".join(all_issues), file=sys.stderr)
        sys.exit(1)

    print("KNOWN_ISSUES.md: OK (size ≤ 300 lines, archival up to date)")
    sys.exit(0)


if __name__ == "__main__":
    main()
