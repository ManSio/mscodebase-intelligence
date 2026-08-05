"""Regression-тесты version_manager (баги, найденные при аудит-фиксах 3.3.12).

1. Ложные дрифты: check_consistency ловил ВСЕ семантические версии
   (зависимости pyproject, старые записи CHANGELOG) как расхождения.
2. Кривая вставка заголовка: bump вставлял запись после первого h1/`---`,
   для ru/zh CHANGELOG заголовок попадал в середину файла.
"""

import re
from pathlib import Path

from src.core.version_manager import VersionManager


def _make_project(tmp_path: Path, version: str, changelog_first: str) -> Path:
    """Создаёт минимальный проект: pyproject + docs/en/CHANGELOG.md."""
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n\n'
        'dependencies = ["requests==9.9.9", "numpy==2.0.0"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs" / "en" / "CHANGELOG.md").write_text(
        f"# Changelog\n\nIntro line\n\n{changelog_first}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_no_false_drifts_on_dependency_versions(tmp_path):
    """Версии зависимостей и старых записей НЕ считаются дрифтом."""
    root = _make_project(
        tmp_path,
        version="1.2.3",
        changelog_first="## [1.2.3] — 2026-01-01 — current\n\n### Fixed\n- x\n\n---\n\n## [1.1.0] — 2025-12-01 — old",
    )
    vm = VersionManager()
    assert vm.check_consistency(str(root)) == []


def test_real_drift_still_detected(tmp_path):
    """Реальный дрифт верхнего заголовка CHANGELOG ловится."""
    root = _make_project(
        tmp_path,
        version="1.2.3",
        changelog_first="## [1.2.4] — 2026-01-02 — newer",
    )
    vm = VersionManager()
    drifts = vm.check_consistency(str(root))
    assert len(drifts) == 1
    assert drifts[0]["file"] == "docs/en/CHANGELOG.md"
    assert drifts[0]["actual"] == "1.2.4"


def test_bump_inserts_header_before_first_version_not_mid_file(tmp_path):
    """Заголовок новой версии вставляется ПЕРЕД первым `## [X.Y.Z]`,
    а не в середину файла (регрессия ru/zh CHANGELOG)."""
    root = _make_project(
        tmp_path,
        version="1.2.3",
        changelog_first="## [1.2.3] — 2026-01-01 — current",
    )
    vm = VersionManager()
    new_ver = vm.bump(str(root), "patch")

    assert new_ver == "1.2.4"
    cl = (root / "docs/en/CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"## \[1\.2\.3\]", cl)  # старая запись на месте
    # Новый заголовок — первый версионный в файле
    first_version_header = re.search(r"^## \[(\d+\.\d+\.\d+)\]", cl, re.MULTILINE)
    assert first_version_header is not None
    assert first_version_header.group(1) == "1.2.4"


def test_bump_updates_all_three_changelogs(tmp_path):
    """bump вставляет заголовок во все три CHANGELOG (en/ru/zh)."""
    for lang in ("en", "ru", "zh"):
        (tmp_path / "docs" / lang).mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / lang / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.3] — 2026-01-01\n",
            encoding="utf-8",
        )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8"
    )

    vm = VersionManager()
    vm.bump(str(tmp_path), "patch")

    for lang in ("en", "ru", "zh"):
        text = (tmp_path / "docs" / lang / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "## [1.2.4]" in text, f"{lang}: header not added"
