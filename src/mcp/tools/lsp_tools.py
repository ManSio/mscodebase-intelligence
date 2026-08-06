"""LSP-инструменты: точный AST-анализ через basedpyright (LspClient).

Добавлены 2026-08-06 (вариант C): lsp_find_references / lsp_find_definition /
lsp_document_symbols. LspClient спавнит basedpyright из Zed languages как
subprocess через stdio JSON-RPC 2.0 — НЕ зависит от LanguageRegistry Zed,
поэтому работает на Windows (в отличие от редакторного LSP-сервера, см.
docs/en/investigations/LSP_WONTFIX.md).

Соглашения:
- line/col — 0-based (LSP-native); ответы содержат 0-based позиции.
- Ленивый общий LspClient: один процесс basedpyright на все три тула,
  стартует при первом вызове (~250ms) и переиспользуется.
- Graceful fallback: если basedpyright не найден — понятное сообщение
  с рекомендацией использовать SymbolIndex-инструменты.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger("mscodebase_server.lsp_tools")

# ──────────────────────────────────────────────
# Общий LspClient (один basedpyright-процесс)
# ──────────────────────────────────────────────

_lsp_client: Optional[Any] = None
_lsp_start_lock: Optional[Any] = None


async def _ensure_lsp():
    """Ленивый общий LspClient: стартует один раз, кэшируется.

    False = попытка старта уже была и провалилась (больше не пробуем в
    рамках сессии — ошибка старта почти всегда означает отсутствие
    basedpyright на машине).
    """
    global _lsp_client, _lsp_start_lock
    if _lsp_client is False:
        return None
    if _lsp_client is not None:
        return _lsp_client
    if _lsp_start_lock is None:
        import asyncio

        _lsp_start_lock = asyncio.Lock()
    async with _lsp_start_lock:
        if _lsp_client is not None:
            return _lsp_client if _lsp_client is not False else None
        try:
            from src.core.lsp_client import LspClient
            from src.mcp.server import resolve_project_root

            root = resolve_project_root()
            client = LspClient(project_root=Path(root))
            if await client.start():
                _lsp_client = client
                logger.info("LspClient ready (pid=%s)", getattr(client._process, "pid", "?"))
                return client
        except Exception as _e:
            logger.warning("LspClient start failed: %s", _e)
        _lsp_client = False
        return None


def _format_locations(locations, label: str) -> str:
    """Форматирует список LSP Location (uri + range) в человекочитаемый текст."""
    if not locations:
        return f"{label}: не найдено"
    lines = [f"{label}: {len(locations)}"]
    for loc in locations:
        uri = loc.get("uri", "?")
        start = loc.get("range", {}).get("start", {})
        end = loc.get("range", {}).get("end", {})
        lines.append(
            f"- {uri}:{start.get('line', 0)}:{start.get('character', 0)}"
            f"-{end.get('line', 0)}:{end.get('character', 0)}"
        )
    return "\n".join(lines)


def _get_symbol_range(sym: dict) -> dict:
    """Достаёт Range из DocumentSymbol (range) или SymbolInformation (location.range)."""
    rng = sym.get("range")
    if rng is None:
        rng = (sym.get("location") or {}).get("range") or {}
    return rng or {}


def _format_document_symbols(symbols, indent: int = 0) -> list[str]:
    """Форматирует дерево символов (DocumentSymbol: range+children | SymbolInformation: location)."""
    out = []
    for sym in symbols:
        name = sym.get("name", "?")
        kind = sym.get("kind", 0)
        start = _get_symbol_range(sym).get("start", {})
        end = _get_symbol_range(sym).get("end", {})
        out.append(
            f"{'  ' * indent}- {name} (kind={kind}) "
            f"L{start.get('line', 0)}..L{end.get('line', 0)}"
        )
        children = sym.get("children") or []
        if children:
            out.extend(_format_document_symbols(children, indent + 1))
    return out


# ══════════════════════════════════════════════════════════
# Инструменты
# ══════════════════════════════════════════════════════════


class LspFindReferencesTool(MCPTool):
    """lsp_find_references — все ссылки на символ через basedpyright (точный AST)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_find_references")

    @error_boundary("lsp_find_references", timeout_ms=15000)
    async def execute(
        self,
        file_path: str,
        line: int,
        col: int = -1,
        symbol_name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Найти все вхождения символа (определения + использования).

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).
            line: строка символа, 0-based (LSP-конвенция).
            col: колонка символа, 0-based; -1 = автопоиск по symbol_name.
            symbol_name: имя символа (для автопоиска колонки при col=-1).

        Returns:
            Список позиций "uri:line:col" (0-based) или сообщение о недоступности LSP.
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте search_code / get_symbol_info / impact_analysis."
            )
        if col < 0:
            if not symbol_name:
                return "col < 0 требует symbol_name для автопоиска колонки"
            col = lsp._find_symbol_column(file_path, line, symbol_name)
            if col < 0:
                return f"Не удалось найти '{symbol_name}' на строке {line} — укажите col вручную"
        refs = await lsp.find_references(file_path, line, col)
        return _format_locations(refs, "Ссылки")


class LspFindDefinitionTool(MCPTool):
    """lsp_find_definition — определение символа через basedpyright (точный AST)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_find_definition")

    @error_boundary("lsp_find_definition", timeout_ms=15000)
    async def execute(
        self,
        file_path: str,
        line: int,
        col: int = -1,
        symbol_name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Найти определение символа (переход к объявлению).

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).
            line: строка символа, 0-based (LSP-конвенция).
            col: колонка символа, 0-based; -1 = автопоиск по symbol_name.
            symbol_name: имя символа (для автопоиска колонки при col=-1).

        Returns:
            Позиция определения "uri:line:col" (0-based) или сообщение.
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте search_code / get_symbol_info / impact_analysis."
            )
        if col < 0:
            if not symbol_name:
                return "col < 0 требует symbol_name для автопоиска колонки"
            col = lsp._find_symbol_column(file_path, line, symbol_name)
            if col < 0:
                return f"Не удалось найти '{symbol_name}' на строке {line} — укажите col вручную"
        defs = await lsp.find_definition(file_path, line, col)
        return _format_locations(defs, "Определения")


class LspDocumentSymbolsTool(MCPTool):
    """lsp_document_symbols — дерево символов файла через basedpyright."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_document_symbols")

    @error_boundary("lsp_document_symbols", timeout_ms=15000)
    async def execute(
        self,
        file_path: str,
        kwargs: Optional[dict] = None,
    ) -> str:
        """Получить структуру файла: все классы/функции/переменные с позициями.

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).

        Returns:
            Дерево символов: "name (kind) L<start>..L<end>" (0-based), с вложенностью.
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте search_code / get_symbol_info."
            )
        symbols = await lsp.document_symbols(file_path)
        if not symbols:
            return "Символов не найдено (проверьте file_path)"
        lines = [f"Символы: {len(symbols)}"]
        lines.extend(_format_document_symbols(symbols))
        return "\n".join(lines)
