"""
git_hooks_installer.py — установка pre-commit хуков для любого проекта.

По Тумблеру: чистая бизнес-логика без MCP-зависимостей.
Вызывается из src/mcp/tools/dev_tools.py (тонкая обёртка).

Хуки:
1. verify_diary — проверка AGENT_DIARY.md на целостность
2. stale_detector — проверка дрейфа версий в доках (doc-sync 2026-08-12:
   checker exit 0, re-enabled после 113 дрейфов → 0)
3. check_tool_names — semantic-гейт имён MCP-тулов в доках (2026-08-12:
   мёртвые имена get_variable_flow и др. удалены, гейт не даёт им вернуться)
4. negative_controls — guard inventory (протокол Тома / OWP §5.2, 2026-08-14:
   каждый guard обязан уметь падать; digest-pinning — правка фикстуры → unproven)
5. check_layer_boundaries — гейт трёх осей Universal Engine (Фаза 1, 2026-08-18:
   mcp/tools не импортирует adapters/src.sources, core — не adapters.*)
6. architecture_linter — архитектурные инварианты (core→mcp, registry через
   Coordinator, циклы core-модулей, stale-имена; 2026-08-24)
7. lock_guard (advisory) — печать активных git-локов параллельных агентов
   (ADR-0007, 2026-08-24); exit 0 — не блокирует коммит
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from src import __version__ as _ENGINE_VERSION

logger = logging.getLogger(__name__)

# Шаблон pre-commit хука — вызывает 3 скрипта через Python
# Внимание: строка проходит через .format(installer_version=..., install_date=...),
# поэтому внутренние фигурные скобки f-строк экранируются как {{ }}.
PRE_COMMIT_HOOK = """#!/usr/bin/env python
\"\"\"
MSCodeBase pre-commit hook — автоматическая проверка перед коммитом.

Установлен: {installer_version}
Дата установки: {install_date}

Запускает:
1. verify_diary — проверка AGENT_DIARY.md
2. stale_detector — проверка дрейфа версий в доках
3. check_tool_names — semantic-гейт имён MCP-тулов
4. negative_controls — guard inventory (каждый guard умеет падать)
5. check_layer_boundaries — гейт трёх осей (Universal Engine)
6. architecture_linter — архитектурные инварианты (core→mcp, registry, циклы, stale-имена)
7. lock_guard — активные git-локи (advisory, exit 0)
\"\"\"

import subprocess
import sys
from pathlib import Path


# §9 п.9 (ENCODING SAFETY): при выводе emoji-строк из stdout скриптов
# (например, «📊 Итог: 20 ✅ / 1 ❌») в cp1251-консоль падает
# UnicodeEncodeError → hook фейлит коммит по ложной причине.
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def run_script(script_path: str, label: str) -> bool:
    \"\"\"Запускает скрипт и возвращает True если успешно.\"\"\"
    project_root = Path(__file__).resolve().parent.parent.parent
    script = project_root / script_path

    if not script.exists():
        print(f"  ⏭️  {{label}}: скрипт не найден ({{script}})")
        return True

    # §5.16: Popen + communicate (не capture_output) — защита от pipe-deadlock
    # в фоновых потоках; encoding="utf-8" — декодирование stdout в utf-8.
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    # Таймаут-запас: verify_diary гоняет gate-zero (полный pytest ~108-130s под
    # нагрузкой) — кап 120s давал флаки TimeoutExpired на коммитах (2026-08-08).
    stdout, _ = proc.communicate(timeout=300)
    if proc.returncode != 0:
        print(f"  ❌ {{label}}: exit {{proc.returncode}}")
        if stdout:
            for line in stdout.splitlines()[-10:]:
                print(f"    {{line}}")
        return False
    print(f"  ✅ {{label}}: OK")
    return True


def main():
    print("🔍 MSCodeBase pre-commit checks:")
    all_ok = True

    all_ok &= run_script("scripts/verify_diary.py", "verify_diary")
    all_ok &= run_script("scripts/stale_detector.py", "stale_detector")
    all_ok &= run_script("scripts/check_tool_names.py", "check_tool_names")
    all_ok &= run_script("scripts/negative_controls_runner.py", "negative_controls")
    all_ok &= run_script("scripts/check_layer_boundaries.py", "check_layer_boundaries")
    all_ok &= run_script("scripts/architecture_linter.py", "architecture_linter")
    all_ok &= run_script("scripts/lock_guard.py", "lock_guard (advisory)")

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

    def __init__(self, version: str = _ENGINE_VERSION):
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
                f"⚠️ pre-commit хук уже существует: {hook_path}\n"
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
            f"✅ Pre-commit hook установлен: {hook_path}\n"
            f"   Версия: {self.version}\n"
            f"   Хуки: verify_diary + stale_detector + check_tool_names + negative_controls + check_layer_boundaries + architecture_linter + lock_guard (advisory)"
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
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                git_dir = Path(result.stdout.strip())
                hooks_dir = git_dir / "hooks"
                if hooks_dir.is_dir():
                    return hooks_dir
        except Exception:
            pass

        return None
