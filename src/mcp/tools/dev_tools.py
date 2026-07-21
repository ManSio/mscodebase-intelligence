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

        Args:
            project_root: Абсолютный путь к корню проекта.

        Returns:
            Markdown-строка или путь к сохранённому файлу.
        """
        try:
            from src.core.doc_generator import DocGenerator

            dg = DocGenerator()
            md = dg.generate(project_root)
            logger.info(
                "generate_docs: %d chars for %s",
                len(md), project_root,
            )
            return md
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
