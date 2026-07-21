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
