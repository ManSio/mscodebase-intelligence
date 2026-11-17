"""Guard: ONNX-сервер запускается скрыто (окно консоли не создаётся).

Живой симптом 2026-11-15: при работе агента раз в ~60 секунд мигало окно
`cmd`/Windows Terminal. Источник — `_launch_server()` с комбинацией
`DETACHED_PROCESS | CREATE_NO_WINDOW`; эти флаги взаимоисключающие, и Windows
игнорировал запрет окна. Плюс сервер не поднимался и клиент ретраил раз в 60 с,
то есть окно появлялось на каждом retry.
"""
from __future__ import annotations

import sys

import pytest

from src.core.embedder import onnx_client as oc

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only флаги")


def test_launch_server_uses_create_no_window_without_detached(monkeypatch, tmp_path):
    captured: dict = {}

    class _FakePopen:
        pid = 4242

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            captured["argv"] = args[0]

    script = tmp_path / "src" / "core" / "embedder" / "onnx_server.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")

    monkeypatch.setattr(oc, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(oc.subprocess, "Popen", _FakePopen)

    # _launch_server отказывает без каталога модели (быстрый отказ ONNX):
    # здесь проверяются флаги окна, поэтому модель подставляем.
    from src.core.embedder import model_paths

    monkeypatch.setattr(model_paths, "resolve_model_dir", lambda _name: tmp_path / "model")
    monkeypatch.setattr(model_paths, "candidate_dirs", lambda _name: [tmp_path / "model"])

    client = oc.OnnxEmbedderClient(port=9877)
    assert client._launch_server() is True, "запуск сервера не состоялся"

    flags = captured.get("creationflags", 0)
    assert flags & CREATE_NO_WINDOW, f"нет CREATE_NO_WINDOW: {flags:#x}"
    assert not flags & DETACHED_PROCESS, (
        "DETACHED_PROCESS вместе с CREATE_NO_WINDOW: Windows игнорирует запрет окна "
        f"({flags:#x})"
    )
