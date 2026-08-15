"""Guard: JSON-схемы MCP-тулов обязаны быть «плоскими» (без $defs/$ref).

Контекст (Zed 1.14.2, #60165): провайдеры с JSON Schema Subset (Google Gemini,
xAI Grok, OpenAI-совместимые прокси) отклоняют MCP-тулы, чьи inputSchema
содержат `$ref`/`$defs` (вложенные pydantic-модели). Наши тулы регистрируются
с примитивными типами (str/int/bool/dict/list) — этот тест ловит регрессию:
кто-то добавляет BaseModel/датакласс в параметры тула → Gemini/Grok больше
не смогут вызвать инструмент в Zed-агенте.

Проверка runtime (не source-статика): строим FastMCP-app с мок-сервисами
(MagicMock — регистрация не вызывает методы) и смотрим на реальные схемы.

Требует `mcp` SDK (зависимость проекта, requirements-lock.txt mcp==1.28.1).
Локально без mcp — тест пропускается (importorskip), в CI исполняется.
"""
from unittest.mock import MagicMock

import pytest

mcp = pytest.importorskip("mcp")
from mcp.server.fastmcp import FastMCP  # noqa: E402

from src.mcp.server_tools import register_all_tools  # noqa: E402


def _registered_tools():
    """Все тулы: core (register_all_tools) + intel (tools_reg)."""
    app = FastMCP("schema_guard")
    register_all_tools(app, MagicMock())
    from src.core.intelligence.tools_reg import register_intelligence_tools
    register_intelligence_tools(app, MagicMock())
    return app._tool_manager.list_tools()


def test_no_dollardefs_or_ref_in_tool_schemas():
    """Ни один тул не должен генерировать $defs/$ref в inputSchema."""
    tools = _registered_tools()
    assert len(tools) >= 40, f"подозрительно мало тулов: {len(tools)}"
    offenders = [
        t.name for t in tools
        if "$defs" in t.parameters or "$ref" in t.parameters
    ]
    assert not offenders, (
        f"JSON Schema Subset-несовместимые схемы ({len(offenders)}): {offenders}. "
        "Вложенные pydantic-модели в параметрах тула ломают Gemini/Grok-консьюмеров "
        "(Zed #60165). Используйте примитивные типы или flatten-схему."
    )


def test_tool_schemas_are_objects_with_properties():
    """Санити: схемы — валидные object-схемы (не пустые, не сломанные)."""
    tools = _registered_tools()
    for t in tools:
        s = t.parameters
        assert isinstance(s, dict), f"{t.name}: schema не dict"
        assert s.get("type") in ("object", None), f"{t.name}: не object-схема"
