"""Тесты hub codebase — маршрутизация write-под-действий (README-контракт).

Регрессия INC: codebase(action="write", ...) → «Unknown action: write» —
под-действие терялось при делегировании в WriteTool. README (все 3 языка)
документирует прямые формы:
    codebase(action="rename"|"move"|"safe_delete"|"replace"|
              "insert_before"|"insert_after"|"ack_impact", ...)

Покрытие:
1. Прямые action → WriteTool с тем же action.
2. Алиасы: delete → safe_delete, ack_impact → ack.
3. Legacy action="write" → вывод под-действия из kwargs.
4. Проброс impact_token (ack).
5. Нераспознанное под-действие → понятная ошибка (не «Unknown action: write»).
"""
from unittest.mock import MagicMock

import pytest

from src.mcp.tools.codebase_tool import CodebaseTool


@pytest.fixture
def mock_services():
    services = MagicMock()
    services.resolve = MagicMock()
    return services


class FakeWriteTool:
    """Перехватывает WriteTool.execute, не трогая real WriteTool/guard."""

    last_action = None
    last_kwargs = None

    def __init__(self, services):
        self.services = services

    async def execute(self, **kwargs):
        type(self).last_action = kwargs.get("action")
        type(self).last_kwargs = kwargs
        return f"FAKE:{kwargs.get('action')}"


@pytest.fixture
def hub(mock_services, monkeypatch):
    monkeypatch.setattr("src.mcp.tools.write_tools.WriteTool", FakeWriteTool)
    FakeWriteTool.last_action = None
    FakeWriteTool.last_kwargs = None
    return CodebaseTool(mock_services)


class TestHubWriteRouting:
    async def test_rename_action_routes_to_write_tool(self, hub):
        await hub.execute(action="rename", old_name="Foo", new_name="Bar")
        assert FakeWriteTool.last_action == "rename"

    async def test_move_action(self, hub):
        await hub.execute(action="move", symbol="Foo", to_file="src/b.py")
        assert FakeWriteTool.last_action == "move"

    async def test_safe_delete_action(self, hub):
        await hub.execute(action="safe_delete", symbol="Foo")
        assert FakeWriteTool.last_action == "safe_delete"

    async def test_delete_alias_maps_to_safe_delete(self, hub):
        await hub.execute(action="delete", symbol="Foo")
        assert FakeWriteTool.last_action == "safe_delete"

    async def test_replace_action(self, hub):
        await hub.execute(action="replace", symbol="Foo", new_code="pass")
        assert FakeWriteTool.last_action == "replace"

    async def test_insert_before(self, hub):
        await hub.execute(action="insert_before", anchor_symbol="Bar", new_code="x")
        assert FakeWriteTool.last_action == "insert_before"

    async def test_insert_after(self, hub):
        await hub.execute(action="insert_after", anchor_symbol="Bar", new_code="x")
        assert FakeWriteTool.last_action == "insert_after"

    async def test_ack_impact_alias_maps_to_ack(self, hub):
        await hub.execute(action="ack_impact", file_path="src/a.py", impact_token="tok")
        assert FakeWriteTool.last_action == "ack"

    async def test_legacy_write_infers_rename(self, hub):
        await hub.execute(action="write", old_name="Foo", new_name="Bar")
        assert FakeWriteTool.last_action == "rename"

    async def test_legacy_write_infers_move(self, hub):
        await hub.execute(action="write", symbol="Foo", to_file="src/b.py")
        assert FakeWriteTool.last_action == "move"

    async def test_legacy_write_infers_replace(self, hub):
        await hub.execute(action="write", symbol="Foo", new_code="pass")
        assert FakeWriteTool.last_action == "replace"

    async def test_legacy_write_infers_safe_delete(self, hub):
        await hub.execute(action="write", symbol="Foo")
        assert FakeWriteTool.last_action == "safe_delete"

    async def test_legacy_write_infers_ack(self, hub):
        await hub.execute(action="write", file_path="src/a.py", impact_token="abc")
        assert FakeWriteTool.last_action == "ack"

    async def test_impact_token_passthrough(self, hub):
        await hub.execute(action="ack_impact", file_path="src/a.py", impact_token="abc")
        assert FakeWriteTool.last_kwargs.get("impact_token") == "abc"

    async def test_unknown_subaction_returns_helpful_error(self, hub):
        result = await hub.execute(action="write")
        assert "Не удалось определить" in result
        assert FakeWriteTool.last_action is None
