"""Регрессионные тесты: инструменты берут корень проекта из resolve_project_root.

История (аудит Bot_snow #6/#7): stale_detector и _grep_fallback вычисляли корень
проекта через Path(__file__).parent... — в installed-режиме (запуск из расширения
Zed) это каталог РАСШИРЕНИЯ, а не проект пользователя. Инструменты сканировали
чужую документацию и давали мусорные результаты.

Фикс (INC-MULTI-WINDOW): оба используют resolve_project_root() — тот же резолвер
(CWD-first, per-window), что и основной выбор проекта.
"""

from __future__ import annotations

import asyncio

import pytest

from src.mcp.tools import search_tools
from src.mcp.tools.doc_tools import StaleDetectorTool


@pytest.fixture()
def fake_user_project(tmp_path):
    """«Проект пользователя»: отдельная директория с уникальным символом."""
    project = tmp_path / "user_project"
    project.mkdir()
    (project / "target.py").write_text(
        "class UniqueTargetClassForGrep:\n    pass\n", encoding="utf-8"
    )
    return project


@pytest.fixture()
def patch_resolver(monkeypatch, fake_user_project):
    """Перенаправляем резолвер на «проект пользователя»."""
    monkeypatch.setattr(
        "src.core.project_resolution.resolve_project_root",
        lambda: fake_user_project,
    )
    return fake_user_project


class TestGrepFallbackProjectRoot:
    def test_searches_resolved_project(self, patch_resolver):
        """_grep_fallback ищет в проекте пользователя, не в каталоге __file__."""
        out = search_tools._grep_fallback("UniqueTargetClassForGrep")
        assert "target.py" in out, (
            f"grep_fallback должен искать в проекте пользователя (resolve_project_root), "
            f"а не в каталоге расширения. Результат:\n{out}"
        )

    def test_does_not_scan_extension_dir(self, patch_resolver):
        """Мусор из каталога расширения не должен попадать в выдачу.

        Раньше корень брался из __file__ → в dev-режиме это сам репозиторий
        MSCodeBase, и в выдачу попадали файлы вроде search_tools.py.
        """
        out = search_tools._grep_fallback("UniqueTargetClassForGrep")
        assert "search_tools.py" not in out
        assert "doc_tools.py" not in out


class TestStaleDetectorProjectRoot:
    def test_uses_resolved_project(self, patch_resolver):
        """stale_detector сканирует проект пользователя, не каталог расширения."""
        captured: dict = {}

        tool = StaleDetectorTool.__new__(StaleDetectorTool)  # без DI-контейнера
        tool._load_config = lambda path: captured.setdefault("config", path) or {}
        tool._get_actual_version = lambda path: captured.setdefault("version", path) or "9.9.9"
        tool._scan_docs = lambda path, ver, cfg: captured.setdefault("scan", path) or []

        result = asyncio.run(tool.execute(None))

        assert captured.get("scan") == patch_resolver, (
            f"_scan_docs должен получить проект пользователя (resolve_project_root), "
            f"получил: {captured.get('scan')!r}"
        )
        assert "VERSION DRIFT" not in result  # пустой отчёт → «up to date»
