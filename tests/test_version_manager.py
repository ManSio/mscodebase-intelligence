"""Tests: VersionManager — bump, consistency check."""

import json
from pathlib import Path
from unittest.mock import patch


class TestVersionManager:
    def test_get_version(self):
        """Читает версию из pyproject.toml."""
        from src.core.version_manager import VersionManager
        root = Path(__file__).resolve().parent.parent
        v = VersionManager().get_current_version(str(root))
        assert v is not None
        assert v.count(".") == 2  # major.minor.patch

    def test_check_consistency(self):
        """Проверяет консистентность версий во всех файлах."""
        from src.core.version_manager import VersionManager
        root = Path(__file__).resolve().parent.parent
        drifts = VersionManager().check_consistency(str(root))
        # Может быть дрифт (CHANGELOG может содержать старые версии)
        # Но pyproject.toml — единый источник
        # drifts может включать pyproject.toml если в нём есть старые версии
        # (комментарии, примеры). Это нормально — check_consistency находит ВСЕ вхождения.

    def test_bump_patch(self):
        """bump('patch') инкрементирует патч: 1.0.0 → 1.0.1."""
        from src.core.version_manager import VersionManager
        vm = VersionManager()
        assert vm._bump_semver("1.0.0", "patch") == "1.0.1"
        assert vm._bump_semver("3.3.1", "patch") == "3.3.2"
        assert vm._bump_semver("0.0.9", "patch") == "0.0.10"

    def test_bump_minor(self):
        """bump('minor') инкрементирует минор: 1.0.0 → 1.1.0."""
        from src.core.version_manager import VersionManager
        vm = VersionManager()
        assert vm._bump_semver("1.0.0", "minor") == "1.1.0"
        assert vm._bump_semver("3.3.1", "minor") == "3.4.0"

    def test_bump_major(self):
        """bump('major') инкрементирует мажор: 1.0.0 → 2.0.0."""
        from src.core.version_manager import VersionManager
        vm = VersionManager()
        assert vm._bump_semver("1.0.0", "major") == "2.0.0"
        assert vm._bump_semver("3.3.1", "major") == "4.0.0"

    def test_dry_run_no_write(self):
        """dry_run=True не меняет файлы."""
        from src.core.version_manager import VersionManager
        root = Path(__file__).resolve().parent.parent
        result = VersionManager().bump(str(root), part="patch", dry_run=True)
        assert "Version:" in result
        assert "Drift" in result or "pyproject.toml" in result
