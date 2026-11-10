"""Test-bucket classification (E67, `experiments/test_bucket_2026_11/`).

After the measurement the shipped default is `content`; `path` is the rollback.
"""

from __future__ import annotations

from src.mcp.tools.investigate_tool import _bucket_penalty


def _project(tmp_path):
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "core" / "test_impact.py").write_text(
        "def risk_level(n):\n    return 'high'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "tests" / "test_thing.py").write_text(
        "from pytest import mark\n\ndef test_one():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_helper.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    return tmp_path


def test_production_module_is_spared_by_default(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.delenv("MSCODEBASE_TEST_BUCKET", raising=False)

    assert _bucket_penalty("src/core/test_impact.py", "where is X defined", root) == 0.0


def test_path_mode_is_still_available_as_rollback(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setenv("MSCODEBASE_TEST_BUCKET", "path")

    assert _bucket_penalty("src/core/test_impact.py", "where is X defined", root) == -2.0


def test_a_file_that_defines_tests_is_still_penalised(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.delenv("MSCODEBASE_TEST_BUCKET", raising=False)

    assert _bucket_penalty("src/tests/test_thing.py", "where is X defined", root) == -2.0


def test_no_io_needed_under_tests(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.delenv("MSCODEBASE_TEST_BUCKET", raising=False)

    # The file has no test markers, but a tests/ path is a test by definition.
    assert _bucket_penalty("tests/test_helper.py", "where is X defined", root) == -2.0


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("MSCODEBASE_TEST_BUCKET", raising=False)

    assert _bucket_penalty("src/ghost/test_missing.py", "where is X defined", tmp_path) == -2.0


def test_unknown_mode_keeps_the_new_default(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setenv("MSCODEBASE_TEST_BUCKET", "nonsense")

    assert _bucket_penalty("src/core/test_impact.py", "where is X defined", root) == 0.0


def test_a_question_about_tests_keeps_full_weight(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.delenv("MSCODEBASE_TEST_BUCKET", raising=False)

    assert _bucket_penalty("src/tests/test_thing.py", "where are the tests for X", root) == 0.0
