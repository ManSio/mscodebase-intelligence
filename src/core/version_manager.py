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
from typing import Dict, List, Optional

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

    # Per-file паттерн ТОЛЬКО «нашей» версии проекта.
    # НЕ ищем все X.Y.Z подряд: версии зависимостей (pyproject), прошлых
    # записей (CHANGELOG) и сторонних пакетов дают ложные дрифты.
    VERSION_PATTERNS = {
        "pyproject.toml": r'^version\s*=\s*["\'](\d+\.\d+\.\d+)["\']',
        "docs/en/CHANGELOG.md": r"^## \[(\d+\.\d+\.\d+)\]",
        "docs/ru/CHANGELOG.md": r"^## \[(\d+\.\d+\.\d+)\]",
        "docs/zh/CHANGELOG.md": r"^## \[(\d+\.\d+\.\d+)\]",
        "README.md": r"(?:version\s*[=:]\s*|releases/tag/v)(\d+\.\d+\.\d+)",
    }

    # CHANGELOG, в которые bump вставляет заголовок (все три языка)
    CHANGELOGS = [
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
            pattern = self.VERSION_PATTERNS.get(rel_path)
            if not pattern:
                continue
            # Берём ПЕРВОЕ вхождение версии (для CHANGELOG — верхний заголовок,
            # для pyproject — project.version). Версии зависимостей/старых
            # записей игнорируются паттерном.
            m = re.search(pattern, text, re.MULTILINE)
            if not m:
                continue  # версия в файле не найдена — не дрифт
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

        # Обновляем CHANGELOG.md (добавляем заголовок перед первым версионным
        # заголовком — не зависеть от позиции первого h1/---)
        import datetime
        today = datetime.date.today().isoformat()
        for rel_cl in self.CHANGELOGS:
            changelog = root / rel_cl
            if not changelog.exists():
                print(f"  ⏭️  {rel_cl} — not found, skipping")
                continue
            cl_text = changelog.read_text(encoding="utf-8")
            m = re.search(r"^## \[\d+\.\d+\.\d+\]", cl_text, re.MULTILINE)
            insert_pos = m.start() if m else len(cl_text)
            new_entry = (
                f"\n## [{new_version}] — {today}\n\n"
                f"### Changed\n"
                f"- Version bumped from {current} to {new_version}\n\n"
                f"---\n\n"
            )
            cl_text = cl_text[:insert_pos] + new_entry + cl_text[insert_pos:]
            changelog.write_text(cl_text, encoding="utf-8")
            print(f"  ✅ {rel_cl} → header added")

        logger.info(f"Version bumped: {current} → {new_version}")
        return new_version
