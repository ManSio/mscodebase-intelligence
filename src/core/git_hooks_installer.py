"""
git_hooks_installer.py — установка pre-commit хуков для любого проекта.

По Тумблеру: чистая бизнес-логика без MCP-зависимостей.
Вызывается из src/mcp/tools/dev_tools.py (тонкая обёртка).

Хуки:
1. verify_diary — проверка AGENT_DIARY.md на целостность
2. stale_detector — обнаружение устаревшей документации
3. generate_docs — авто-генерация Markdown документации
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Шаблон pre-commit хука — вызывает 3 скрипта через Python
PRE_COMMIT_HOOK = """#!/usr/bin/env python3
\"\"\"
MSCodeBase pre-commit hook — автоматическая проверка перед коммитом.

Установлен: {installer_version}
Дата установки: {install_date}

Запускает:
1. verify_diary — проверка AGENT_DIARY.md
2. stale_detector — поиск устаревшей документации
3. generate_docs — генерация документации
\"\"\"

import subprocess
import sys
from pathlib import Path


def run_script(script_path: str, label: str) -> bool:
    \"\"\"Запускает скрипт и возвращает True если успешно.\"\"\"
    project_root = Path(__file__).resolve().parent.parent.parent
    script = project_root / script_path

    if not script.exists():
        print(f"  ⏭️  {{label}}: скрипт не найден ({{script}})")
        return True

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  ❌ {{label}}: FAILED")
        print(result.stderr[:500])
        return False
    print(f"  ✅ {{label}}: OK")
    return True


def main():
    print("🔍 MSCodeBase pre-commit checks:")
    all_ok = True

    all_ok &= run_script("scripts/verify_diary.py", "verify_diary")
    all_ok &= run_script("scripts/stale_detector.py", "stale_detector")
    all_ok &= run_script("scripts/generate_docs.py", "generate_docs")

    if not all_ok:
        print("\\n❌ Pre-commit checks FAILED. Исправьте ошибки перед коммитом.")
        sys.exit(1)
    print("\\n✅ All pre-commit checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
"""


class GitHooksInstaller:
    """Установка и удаление pre-commit хуков MSCodeBase.

    Usage:
        installer = GitHooksInstaller()
        result = installer.install("/path/to/project")
        # или
        result = installer.uninstall("/path/to/project")
    """

    def __init__(self, version: str = "3.3.7"):
        self.version = version

    # ─── Public API ────────────────────────────────────────

    def install(self, project_root: str) -> str:
        """Устанавливает pre-commit хук в .git/hooks/ проекта.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Сообщение о результате установки.
        """
        git_hooks_dir = self._resolve_git_hooks(project_root)
        if git_hooks_dir is None:
            return "❌ .git не найден. Убедитесь, что проект инициализирован (git init)."

        hook_path = git_hooks_dir / "pre-commit"

        if hook_path.exists():
            return (
                f"⚠️ pre-commit хук уже существует: {hook_path}\\n"
                f"   Удалите вручную или вызовите uninstall() перед переустановкой."
            )

        from datetime import datetime

        hook_content = PRE_COMMIT_HOOK.format(
            installer_version=self.version,
            install_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        hook_path.write_text(hook_content, encoding="utf-8")
        hook_path.chmod(0o755)  # +x

        logger.info("Git hook installed: %s", hook_path)
        return (
            f"✅ Pre-commit hook установлен: {hook_path}\\n"
            f"   Версия: {self.version}\\n"
            f"   Хуки: verify_diary, stale_detector, generate_docs"
        )

    def uninstall(self, project_root: str) -> str:
        """Удаляет pre-commit хук из .git/hooks/ проекта.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Сообщение о результате удаления.
        """
        git_hooks_dir = self._resolve_git_hooks(project_root)
        if git_hooks_dir is None:
            return "❌ .git не найден."

        hook_path = git_hooks_dir / "pre-commit"

        if not hook_path.exists():
            return "⚠️ pre-commit хук не установлен."

        hook_path.unlink()
        logger.info("Git hook removed: %s", hook_path)
        return f"✅ Pre-commit hook удалён: {hook_path}"

    def check_status(self, project_root: str) -> str:
        """Проверяет, установлен ли pre-commit хук.

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Статус: установлен / не установлен / .git не найден.
        """
        git_hooks_dir = self._resolve_git_hooks(project_root)
        if git_hooks_dir is None:
            return "❌ .git не найден."

        hook_path = git_hooks_dir / "pre-commit"
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8")
            version = "неизвестно"
            for line in content.splitlines():
                if "installer_version" in line or "MSCodeBase" in content:
                    if "version" in content:
                        for vline in content.splitlines():
                            if "installer_version" in vline:
                                version = vline.split(":")[-1].strip().strip('"')
                                break
            return f"✅ Pre-commit hook установлен (версия: {version})"
        return "ℹ️ Pre-commit hook не установлен"

    # ─── Internal ─────────────────────────────────────────

    def _resolve_git_hooks(self, project_root: str) -> Optional[Path]:
        """Находит .git/hooks/ директорию проекта.

        Сначала проверяет стандартный путь, затем через git rev-parse.
        """
        root = Path(project_root).resolve()

        # Стандартный путь
        git_hooks = root / ".git" / "hooks"
        if git_hooks.is_dir():
            return git_hooks

        # .git может быть файлом (git worktree)
        git_file = root / ".git"
        if git_file.is_file():
            try:
                content = git_file.read_text(encoding="utf-8").strip()
                # Формат: "gitdir: /path/to/.git/worktrees/name"
                if content.startswith("gitdir:"):
                    git_dir = Path(content.split(":", 1)[1].strip())
                    hooks_dir = git_dir.parent / "hooks"
                    if hooks_dir.is_dir():
                        return hooks_dir
            except Exception:
                pass

        # Через git rev-parse
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                git_dir = Path(result.stdout.strip())
                hooks_dir = git_dir / "hooks"
                if hooks_dir.is_dir():
                    return hooks_dir
        except Exception:
            pass

        return None
