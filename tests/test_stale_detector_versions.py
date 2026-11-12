"""Stale-detector version scan: dependency pins are not project versions.

Night 12->13.11.2026: ru/zh SYSTEM_REQUIREMENTS say `onnxruntime==1.27.0` (the
real pin in requirements.txt). The detector compared it with pyproject's 3.5.0
and reported drift on docs that were correct.
"""

from __future__ import annotations

from pathlib import Path

from tools.stale_detector.stale_check import StaleConfig, scan_doc


def _config(tmp_path: Path) -> StaleConfig:
    cfg = tmp_path / "stale.json"
    cfg.write_text("{}", encoding="utf-8")
    return StaleConfig.from_file(cfg)


def _doc(tmp_path: Path, line: str) -> Path:
    doc = tmp_path / "docs" / "en" / "REQ.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(line + "\n", encoding="utf-8")
    return doc


def test_dependency_pin_is_not_project_version_drift(tmp_path):
    doc = _doc(
        tmp_path,
        "The wheel `onnxruntime==1.27.0` needs AVX2; Python 3.14 is required.",
    )
    assert scan_doc(doc, tmp_path, "3.5.0", _config(tmp_path)) is None


def test_project_version_drift_is_still_reported(tmp_path):
    doc = _doc(tmp_path, "MSCodeBase version 1.27.0 is the documented release.")
    report = scan_doc(doc, tmp_path, "3.5.0", _config(tmp_path))
    assert report is not None
    assert report.hits[0]["expected"] == "1.27.0"
    assert report.hits[0]["actual"] == "3.5.0"
