"""Red-first tests for the configuration docs guard (G7).

Written after `docs/*/CONFIGURATION.md` documented `MSCODEBASE_MAX_FILE_SIZE_MB`
while `src/config/settings.py:425` reads `MAX_FILE_SIZE_MB`: a user copying the
documented name gets no effect, and nothing noticed for months.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_docs_vs_config as guard  # noqa: E402


def test_real_tree_is_clean_and_checks_many_vars():
    problems, checked = guard.check(REPO)
    assert checked >= 50, f"only {checked} variables parsed — the guard is blind"
    assert problems == [], problems


def test_documented_but_unread_variable_is_reported(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "docs" / "en" / "CONFIGURATION.md").write_text(
        "| Variable | Default | Effect |\n"
        "|---|---|---|\n"
        "| `MSCODEBASE_REAL_FLAG` | `true` | real |\n"
        "| `MSCODEBASE_INVENTED_FLAG` | `10` | invented |\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "settings.py").write_text(
        'FLAG = os.getenv("MSCODEBASE_REAL_FLAG", "true")\n', encoding="utf-8"
    )

    problems, checked = guard.check(tmp_path)
    assert checked == 2
    assert any("MSCODEBASE_INVENTED_FLAG" in p for p in problems), problems
    assert not any("MSCODEBASE_REAL_FLAG" in p for p in problems), problems


def test_max_file_size_name_matches_the_code():
    """The historical defect: the doc must not resurrect the prefixed name."""
    doc = (REPO / "docs" / "en" / "CONFIGURATION.md").read_text(encoding="utf-8")
    settings = (REPO / "src" / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'os.getenv("MAX_FILE_SIZE_MB", "10")' in settings
    assert "MSCODEBASE_MAX_FILE_SIZE_MB" not in doc
    assert "MAX_FILE_SIZE_MB" in doc


def test_empty_corpus_is_not_a_pass(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "docs" / "en" / "CONFIGURATION.md").write_text("# no tables\n", encoding="utf-8")
    problems, checked = guard.check(tmp_path)
    assert checked == 0
    assert problems
