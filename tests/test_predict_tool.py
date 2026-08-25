"""test_predict_tool.py — predict_change: MCP-обёртка над core-предиктором.

Лёгкие тесты: статический режим на мини-репо + INCONCLUSIVE без изменений.
Полный (worktree) режим покрыт e2e в test_change_preview.py.
"""

import subprocess
from pathlib import Path

import pytest

from src.mcp.tools.predict_tools import PredictChangeTool


class _StubServices:
    def resolve(self, name, *args, **kwargs):
        raise KeyError(name)


def _make_repo(tmp_path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    assert subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, capture_output=True
    ).returncode == 0
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True)
    (repo / "src").mkdir()
    (repo / "src" / "widget.py").write_text("def render():\n    return 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_widget.py").write_text(
        "from src.widget import render\n\ndef test_render():\n    assert render() == 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, capture_output=True)
    return repo


@pytest.mark.asyncio
async def test_static_mode_returns_blast_radius(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    (repo / "src" / "widget.py").write_text(
        "def render():\n    return 2\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.core.project_resolution.resolve_project_root", lambda: str(repo)
    )
    tool = PredictChangeTool(_StubServices())
    out = await tool.execute({"mode": "static"})
    assert "VERDICT: STATIC" in out
    assert "src/widget.py" in out
    assert "tests/test_widget.py" in out
    assert "Gates:" in out


@pytest.mark.asyncio
async def test_inconclusive_when_no_changes(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        "src.core.project_resolution.resolve_project_root", lambda: str(repo)
    )
    tool = PredictChangeTool(_StubServices())
    out = await tool.execute({"mode": "static"})
    assert "VERDICT: INCONCLUSIVE" in out


@pytest.mark.asyncio
async def test_tool_name_and_defaults(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        "src.core.project_resolution.resolve_project_root", lambda: str(repo)
    )
    tool = PredictChangeTool(_StubServices())
    assert tool.name == "predict_change"
    # дефолтный режим — static; timeout-мусор не роняет
    out = await tool.execute({"timeout": "abc"})
    assert "VERDICT:" in out
