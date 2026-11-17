"""Guard: stale_detector понимает версию JS/TS-проекта (package.json)."""
from __future__ import annotations

from pathlib import Path

from src.mcp.tools.doc_tools import StaleDetectorTool


def _tool() -> StaleDetectorTool:
    tool = StaleDetectorTool.__new__(StaleDetectorTool)  # без DI: нужен только метод
    return tool


def test_version_from_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.2.3"}', encoding="utf-8")
    assert _tool()._get_actual_version(tmp_path) == "1.2.3"


def test_pyproject_wins_over_package_json(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "package.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
    assert _tool()._get_actual_version(tmp_path) == "9.9.9"


def test_no_manifest_is_unknown(tmp_path: Path):
    assert _tool()._get_actual_version(tmp_path) == "unknown"


def test_broken_package_json_is_unknown(tmp_path: Path):
    (tmp_path / "package.json").write_text("not-json{", encoding="utf-8")
    assert _tool()._get_actual_version(tmp_path) == "unknown"
