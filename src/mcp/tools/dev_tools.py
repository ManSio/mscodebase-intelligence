"""
MCP tools: generate_docs, bump_version, install_git_hooks.

По Тумблеру: чистые обёртки над src/core/ бизнес-логикой.
"""

import logging

logger = logging.getLogger(__name__)


def register_dev_tools(mcp_app) -> None:
    """Регистрирует dev-инструменты в MCP-приложении.

    Вызывается из server.py или server_factory.py.
    """

    @mcp_app.tool("generate_docs")
    async def generate_docs(project_root: str) -> str:
        """Генерирует Markdown-документацию из PropertyGraph для любого проекта.

        Сохраняет результат в файл docs/generated/MODULE_INDEX.md
        (не возвращает огромный Markdown в чат, чтобы не тормозить Zed).

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Сводка: сколько файлов обработано + путь к файлу.
        """
        try:
            from src.core.doc_generator import DocGenerator
            from pathlib import Path

            dg = DocGenerator()
            root = Path(project_root).resolve()
            output_dir = str(root / "docs" / "generated")
            filepath = dg.generate(project_root, output_dir=output_dir)

            # Статистика из сохранённого файла
            saved = Path(filepath)
            if saved.exists():
                text = saved.read_text(encoding="utf-8")
                lines = text.count("\n")
                files_count = text.count("## ")
                size_kb = len(text.encode("utf-8")) / 1024
            else:
                lines = files_count = 0
                size_kb = 0.0

            logger.info(
                "generate_docs: %.1f KB, %d files, saved to %s",
                size_kb, files_count, filepath,
            )
            return (
                f"✅ Документация сгенерирована\n"
                f"📄 Файлов с символами: {files_count}\n"
                f"📏 Строк: {lines}\n"
                f"💾 Размер: {size_kb:.0f} KB\n"
                f"📁 Сохранено: {filepath}\n"
                f"\n💡 Откройте файл в Zed, чтобы посмотреть без тормозов."
            )
        except Exception as e:
            logger.error(f"generate_docs failed: {e}")
            return f"Error: {e}"

    @mcp_app.tool("bump_version")
    async def bump_version(
        project_root: str, part: str = "patch", dry_run: bool = False
    ) -> str:
        """Бамп версии проекта (pyproject.toml) и обновление CHANGELOG.

        Args:
            project_root: Абсолютный путь к корню проекта.
            part: 'major', 'minor', 'patch' (по умолч. 'patch').
            dry_run: Если True — только показать изменения без записи.

        Returns:
            Результат: новая версия или dry-run отчёт.
        """
        try:
            from src.core.version_manager import VersionManager

            vm = VersionManager()
            result = vm.bump(project_root, part=part, dry_run=dry_run)
            logger.info("bump_version: %s (dry_run=%s)", result, dry_run)
            return result
        except Exception as e:
            logger.error(f"bump_version failed: {e}")
            return f"Error: {e}"

    @mcp_app.tool("auto_update_docs")
    async def auto_update_docs(project_root: str, action: str = "update") -> str:
        """Автоматическое обновление документации проекта.

        Args:
            project_root: Абсолютный путь к корню проекта.
            action: 'update' (полное обновление), 'check' (проверить устаревание).

        Returns:
            Отчёт об обновлении или статус.
        """
        try:
            from src.core.auto_doc_updater import AutoDocUpdater

            updater = AutoDocUpdater()
            if action == "check":
                result = updater.check_staleness(project_root)
            else:
                result = updater.update_all(project_root)
            logger.info("auto_update_docs: %s (%s)", action, project_root)
            return result
        except Exception as e:
            logger.error(f"auto_update_docs failed: {e}")
            return f"Error: {e}"

    @mcp_app.tool("install_git_hooks")
    async def install_git_hooks(
        project_root: str, action: str = "install"
    ) -> str:
        """Устанавливает/удаляет/проверяет pre-commit хуки MSCodeBase в проекте.

        Args:
            project_root: Абсолютный путь к корню проекта.
            action: 'install' (по умолч.), 'uninstall', 'status'.

        Returns:
            Результат операции.
        """
        try:
            from src.core.git_hooks_installer import GitHooksInstaller

            installer = GitHooksInstaller()
            if action == "uninstall":
                result = installer.uninstall(project_root)
            elif action == "status":
                result = installer.check_status(project_root)
            else:
                result = installer.install(project_root)

            logger.info("install_git_hooks: %s (%s)", action, project_root)
            return result
        except Exception as e:
            logger.error(f"install_git_hooks failed: {e}")
            return f"Error: {e}"
