"""
Version Manager — единый источник версии для любого проекта.

По Тумблеру: чистая бизнес-логика, без MCP-зависимостей.

Usage:
    from src.core.version_manager import VersionManager
    vm = VersionManager()
    vm.bump("/path/to/project", "patch")  # 1.0.0 → 1.0.1
    report = vm.check_consistency("/path/to/project")  # найдёт дрифт
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VersionManager:
    """Управление версией проекта: bump, проверка консистентности."""

    # Файлы, где может упоминаться версия
    VERSION_FILES = [
        "pyproject.toml",
        "README.md",
        "docs/en/CHANGELOG.md",
        "docs/ru/CHANGELOG.md",
        "docs/zh/CHANGELOG.md",
    ]

    @staticmethod
    def _bump_semver(version: str, part: str) -> str:
        """Бампает семантическую версию: major/minor/patch."""
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
        if not match:
            raise ValueError(f"Invalid semver: {version}")
        major, minor, patch = int(match[1]), int(match[2]), int(match[3])
        if part == "major":
            major += 1
            minor = 0
            patch = 0
        elif part == "minor":
            minor += 1
            patch = 0
        elif part == "patch":
            patch += 1
        else:
            raise ValueError(f"Unknown part: {part}")
        return f"{major}.{minor}.{patch}"

    def get_current_version(self, project_root: str) -> Optional[str]:
        """Читает версию из pyproject.toml (единственный источник)."""
        pyproject = Path(project_root) / "pyproject.toml"
        if not pyproject.exists():
            return None
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            m = re.match(r'version\s*=\s*["\'](.+?)["\']', line)
            if m:
                return m.group(1)
        return None

    def check_consistency(self, project_root: str) -> List[Dict]:
        """Проверяет, что версия во всех файлах совпадает с pyproject.toml.

        Returns:
            Список расхождений: [{"file": ..., "expected": ..., "actual": ...}, ...]
        """
        actual = self.get_current_version(project_root)
        if not actual:
            return [{"file": "pyproject.toml", "error": "version not found"}]

        root = Path(project_root)
        drifts = []
        for rel_path in self.VERSION_FILES:
            fp = root / rel_path
            if not fp.exists():
                continue
            text = fp.read_text(encoding="utf-8")
            # Ищем все вхождения семантической версии
            for m in re.finditer(r"(\d+\.\d+\.\d+)", text):
                found = m.group(1)
                if found != actual:
                    drifts.append({
                        "file": rel_path,
                        "line": text[:m.start()].count("\n") + 1,
                        "expected": actual,
                        "actual": found,
                    })
        return drifts

    def bump(
        self, project_root: str, part: str = "patch", dry_run: bool = False
    ) -> str:
        """Бамп версии в pyproject.toml и обновление CHANGELOG.

        Args:
            project_root: Корень проекта.
            part: 'major', 'minor' или 'patch'.
            dry_run: Если True — только показать, что будет изменено.

        Returns:
            Новая версия.
        """
        current = self.get_current_version(project_root)
        if not current:
            raise ValueError(f"pyproject.toml not found in {project_root}")

        new_version = self._bump_semver(current, part)
        root = Path(project_root)
        pyproject = root / "pyproject.toml"

        if dry_run:
            drifts = self.check_consistency(project_root)
            msg = [
                f"Version: {current} → {new_version} ({part})",
                f"pyproject.toml: {current} → {new_version}",
            ]
            for d in drifts:
                msg.append(f"  Drift: {d['file']}:{d['line']} = {d['actual']} (expected {d['expected']})")
            return "\n".join(msg)

        # Обновляем pyproject.toml
        text = pyproject.read_text(encoding="utf-8")
        text = re.sub(
            r'(version\s*=\s*["\'])\d+\.\d+\.\d+(["\'])',
            f"\\g<1>{new_version}\\g<2>",
            text,
        )
        pyproject.write_text(text, encoding="utf-8")

        # Обновляем CHANGELOG.md (добавляем заголовок)
        changelog = root / "docs/en/CHANGELOG.md"
        if changelog.exists():
            cl_text = changelog.read_text(encoding="utf-8")
            # Вставляем новый заголовок после первого h1
            lines = cl_text.split("\n")
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith("# ") and i > 0:
                    insert_at = i
                    break
            import datetime
            today = datetime.date.today().isoformat()
            new_entry = (
                f"\n## [{new_version}] — {today}\n\n"
                f"### Changed\n"
                f"- Version bumped from {current} to {new_version}\n\n"
                f"---\n"
            )
            lines.insert(insert_at, new_entry)
            changelog.write_text("\n".join(lines), encoding="utf-8")

        logger.info(f"Version bumped: {current} → {new_version}")
        return new_version
