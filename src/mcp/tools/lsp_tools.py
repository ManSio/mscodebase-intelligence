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
        except Exception as _e:  # noqa: BLE001
            # Ленивый старт: любой сбой LSP (loop/transport/init) → graceful fallback (None).
            logger.warning("LspClient start failed: %s", _e)
        _lsp_client = False
        return None



def _format_diagnostics(diags) -> str:
    """Форматирует publishDiagnostics (severity 1=Error, 2=Warning, 3=Info, 4=Hint)."""
    if not diags:
        return "Диагностика: ошибок не найдено ✅"
    lines = [f"Диагностика: {len(diags)}"]
    for d in diags:
        sev = {1: "ERROR", 2: "WARNING", 3: "INFO", 4: "HINT"}.get(d.get("severity"), "?")
        rng = d.get("range", {})
        start = rng.get("start", {})
        code = d.get("code", "")
        msg = d.get("message", "")
        lines.append(
            f"- [{sev}] L{start.get('line', 0)}:{start.get('character', 0)}"
            f" ({code}) {msg}"
        )
    return "\n".join(lines)


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


class LspGetTypeInfoTool(MCPTool):
    """lsp_get_type_info — выведенный тип и сигнатура символа через basedpyright (hover)."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_get_type_info")

    @error_boundary("lsp_get_type_info", timeout_ms=15000)
    async def execute(
        self,
        file_path: str,
        line: int,
        col: int = -1,
        symbol_name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Получить выведенный тип и сигнатуру символа в позиции (line, col).

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).
            line: строка символа, 0-based (LSP-конвенция).
            col: колонка символа, 0-based; -1 = автопоиск по symbol_name.
            symbol_name: имя символа (для автопоиска колонки при col=-1).

        Returns:
            Markdown-строка с типом/сигнатурой/docstring или сообщение.
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте get_symbol_info / search_code."
            )
        if col < 0:
            if not symbol_name:
                return "col < 0 требует symbol_name для автопоиска колонки"
            col = lsp._find_symbol_column(file_path, line, symbol_name)
            if col < 0:
                return f"Не удалось найти '{symbol_name}' на строке {line} — укажите col вручную"
        info = await lsp.hover(file_path, line, col)
        if not info:
            return (
                f"Тип/информация не найдены в позиции L{line}:{col} "
                f"(проверьте file_path и координаты)"
            )
        return info


class LspGetDiagnosticsTool(MCPTool):
    """lsp_get_diagnostics — ошибки типов и синтаксиса файла через basedpyright."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_get_diagnostics")

    @error_boundary("lsp_get_diagnostics", timeout_ms=20000)
    async def execute(
        self,
        file_path: str,
        wait_ms: int = 800,
        kwargs: Optional[dict] = None,
    ) -> str:
        """Проверить файл: ошибки типов, неимпортированные модули, синтаксис.

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).
            wait_ms: сколько ждать публикации диагностики (по умолчанию 800).

        Returns:
            Список диагностик (severity/message/позиция) или "ошибок не найдено".
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте search_code / get_symbol_info."
            )
        diags = await lsp.get_diagnostics(file_path, wait_ms=max(100, min(wait_ms, 5000)))
        return _format_diagnostics(diags)


def _format_code_actions(actions) -> str:
    """Форматирует CodeAction (title/kind/edits) в человекочитаемый список."""
    if not actions:
        return "Быстрых правок не найдено в указанной позиции."
    lines = [f"Быстрые правки ({len(actions)}):"]
    for a in actions:
        title = a.get("title", "?")
        kind = a.get("kind", "quickfix")
        edit = a.get("edit") or {}
        changes = edit.get("changes") or {}
        doc_changes = edit.get("documentChanges") or []
        n_edits = sum(len(v) for v in changes.values()) if changes else len(doc_changes)
        # Краткий превью первой правки (новый текст, ≤60 символов)
        preview = ""
        if changes:
            for uris in changes.values():
                if uris:
                    txt = (uris[0].get("newText") or "").replace("\n", " ⏎ ").strip()
                    if txt:
                        preview = f" → {txt[:60]}"
                    break
        elif doc_changes:
            edits = doc_changes[0].get("edits") or []
            if edits:
                txt = (edits[0].get("newText") or "").replace("\n", " ⏎ ").strip()
                if txt:
                    preview = f" → {txt[:60]}"
        lines.append(f"- {title} (kind={kind}, edits={n_edits}){preview}")
    return "\n".join(lines)


class LspGetCodeActionsTool(MCPTool):
    """lsp_get_code_actions — быстрые правки (quick fixes) через basedpyright."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="lsp_get_code_actions")

    @error_boundary("lsp_get_code_actions", timeout_ms=15000)
    async def execute(
        self,
        file_path: str,
        line: int = 0,
        col: int = 0,
        symbol_name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Получить доступные быстрые правки (автоимпорт, quickfix) в позиции.

        Args:
            file_path: путь к файлу (абсолютный или от корня проекта).
            line: строка символа, 0-based (LSP-конвенция).
            col: колонка символа, 0-based.
            symbol_name: имя символа (для автопоиска колонки при col=0 и line указана).

        Returns:
            Список CodeAction: title / kind / число правок / превью первой.
        """
        await self.require_ready_project()
        lsp = await _ensure_lsp()
        if lsp is None:
            return (
                "LSP недоступен (basedpyright не найден). "
                "Используйте search_code / get_symbol_info."
            )
        if col == 0 and symbol_name:
            col = lsp._find_symbol_column(file_path, line, symbol_name)
            if col < 0:
                col = 0
        actions = await lsp.code_actions(file_path, line, col)
        return _format_code_actions(actions)
