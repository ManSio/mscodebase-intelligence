"""TEST-04 + WIN-03 (audit): restricted read policy и cp1251 fallback в read_live_file.

- SEC-05: absolute_path без guard — при MSCODEBASE_RESTRICTED_READ=1
  чтение вне project root отклоняется.
- WIN-03: порядок декодирования BOM → UTF-8 → cp1251 → chardet → latin-1
  унифицирован с index_parser (русские Windows-проекты).
"""

from pathlib import Path

import pytest

from src.mcp.tools.system_tools import ReadLiveFileTool


class _FakeServices:
    pass


class _FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = Path(project_path)


def _make_tool(project_root: Path) -> ReadLiveFileTool:
    tool = ReadLiveFileTool(_FakeServices())
    # Подменяем resolve_indexer — тест не трогает registry/резолвер.
    tool.resolve_indexer = lambda *a, **k: _FakeIndexer(project_root)  # type: ignore
    return tool


async def _run(tool: ReadLiveFileTool, **kwargs) -> dict:
    """Вызывает внутреннюю логику в обход error_boundary (он возвращает str)."""
    return await tool.execute.__wrapped__(tool, **kwargs)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_restricted_read_blocks_absolute_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_RESTRICTED_READ", "1")
    root = tmp_path / "project"
    root.mkdir()
    (root / "inside.txt").write_text("ok", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(outside))

    assert res["status"] == "error"
    assert "outside project root" in res["message"]


@pytest.mark.asyncio
async def test_restricted_read_allows_inside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_RESTRICTED_READ", "1")
    root = tmp_path / "project"
    root.mkdir()
    target = root / "inside.txt"
    target.write_text("hello", encoding="utf-8")

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(target))

    assert res["status"] == "ok"
    assert "hello" in res["content"]


@pytest.mark.asyncio
async def test_restricted_read_off_keeps_legacy_behavior(tmp_path, monkeypatch):
    """По умолчанию (без env) absolute_path вне корня читается как раньше."""
    monkeypatch.delenv("MSCODEBASE_RESTRICTED_READ", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("legacy", encoding="utf-8")

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(outside))

    assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_cp1251_file_decoded_not_mojibake(tmp_path):
    """WIN-03: русский cp1251-файл читается как текст, не как latin-1 мусор."""
    root = tmp_path / "project"
    root.mkdir()
    target = root / "russian.txt"
    text = "Привет, мир — тест кодировки"
    target.write_bytes(text.encode("cp1251"))

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(target))

    assert res["status"] == "ok"
    assert res["encoding"] == "cp1251"
    assert "Привет, мир" in res["content"]


@pytest.mark.asyncio
async def test_live_buffer_overlay_served_before_disk(tmp_path, monkeypatch):
    """Live-оверлей: несохранённый текст читается раньше диска (source=live_buffer)."""
    from src.sync.live_buffer import LiveBuffer

    root = tmp_path / "project"
    root.mkdir()
    target = root / "a.py"
    target.write_text("DISK content", encoding="utf-8")

    # Кладём в оверлей живой (несохранённый) текст.
    buf = LiveBuffer()
    buf.update(str(target), "LIVE unsaved content v7", version=7)
    monkeypatch.setattr("src.sync.live_buffer.get_live_buffer", lambda: buf)

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(target))

    assert res["status"] == "ok"
    assert res["source"] == "live_buffer"
    assert "LIVE unsaved content v7" in res["content"]
    # Дисковый текст не должен попасть, когда есть живой.
    assert "DISK content" not in res["content"]


@pytest.mark.asyncio
async def test_live_buffer_absent_falls_back_to_disk(tmp_path, monkeypatch):
    """Без оверлея — обычное чтение с диска."""
    from src.sync.live_buffer import LiveBuffer

    root = tmp_path / "project"
    root.mkdir()
    target = root / "a.py"
    target.write_text("DISK content", encoding="utf-8")

    buf = LiveBuffer()  # пустой — нет живого
    monkeypatch.setattr("src.sync.live_buffer.get_live_buffer", lambda: buf)

    tool = _make_tool(root)
    res = await _run(tool, absolute_path=str(target))

    assert res["status"] == "ok"
    assert res["source"] == "disk"
    assert "DISK content" in res["content"]
