"""Contract guard: index-feeding paths MUST be canonical POSIX.

Root cause 2026-09-25 (index ~2x bloat): full reindex built rel paths with "\\"
while hot-reload built them with "/", so the same file became two rows. This
static guard fails the build if any index-feeding module builds a stored path via
a raw `str(...relative_to(...))` without normalising (normalize_rel_path /
as_posix / replace). It is a guard that CAN fail — it would have caught the bug.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Modules whose relative paths flow into the index / dedup / prune / ids.
FEED_FILES = [
    "src/core/indexing/indexer.py",
    "src/core/indexing/db_writer.py",
    "src/core/indexing/index_project_runner.py",
    "src/core/indexing/freshness.py",
    "src/core/indexing/index_status.py",
    "src/mcp/tools/indexing_tools.py",
]

_RAW_RELATIVE = re.compile(r"str\([^)]*relative_to\(")
_NORMALISERS = ("normalize_rel_path", "as_posix", ".replace(")


def _violations() -> list[str]:
    bad: list[str] = []
    for rel in FEED_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _RAW_RELATIVE.search(line) and not any(k in line for k in _NORMALISERS):
                bad.append(f"{rel}:{i}: {line.strip()}")
    return bad


def test_no_raw_relative_to_in_index_feeders():
    bad = _violations()
    assert not bad, (
        "Index-feeding path built without canonical POSIX normalisation:\n"
        + "\n".join(bad)
        + "\nUse src.core.relpath.normalize_rel_path."
    )


def test_guard_can_fail():
    """Negative control: detector FLAGS a raw str(relative_to) and NOT a normalised one."""
    bad = 'rel = str(p.relative_to(root))'
    assert _RAW_RELATIVE.search(bad) and not any(k in bad for k in _NORMALISERS)
    good = 'rel = normalize_rel_path(p.relative_to(root))'
    assert not _RAW_RELATIVE.search(good)
