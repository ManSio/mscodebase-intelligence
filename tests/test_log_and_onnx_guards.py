"""Guards по решению 2026-11-17: уровни логов и быстрый отказ ONNX.

Каждый тест краснеет, если поведение откатится:
- WARNING на подмену CWD — ровно один на пару (cwd, PROJECT_PATH);
- giant-function — INFO, не WARNING;
- клиент ONNX при отсутствии модели отвечает False сразу, без 60-секундного
  ожидания, и называет места поиска.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest


def _project(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text(
        "[project]\nname='guard'\nversion='0.1.0'\n", encoding="utf-8"
    )
    return path


def test_cwd_substitution_warns_once(tmp_path, monkeypatch, caplog):
    """Хост запускает сервер из каталога расширения: 3 203 одинаковых WARNING."""
    from src.core import project_resolution as pr

    project = _project(tmp_path / "real_project")
    elsewhere = tmp_path / "extension_dir"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PROJECT_PATH", str(project))
    monkeypatch.setattr(pr, "_CWD_SUBSTITUTIONS_WARNED", set(), raising=False)

    with caplog.at_level(logging.DEBUG, logger="mscodebase_server.project_resolution"):
        first = pr.resolve_project_root()
        second = pr.resolve_project_root()

    assert first == project and second == project
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "не похож на проект" in warnings[0].getMessage()


def test_giant_function_is_info_not_warning(tmp_path, caplog):
    """5 509 WARNING за неделю — это штатное дробление больших функций."""
    from src.core.indexing.parser import CodeParser

    big = "def huge():\n" + "".join(f"    x{i} = {i}\n" for i in range(4000))
    (tmp_path / "big.py").write_text(big, encoding="utf-8")

    parser = CodeParser()
    with caplog.at_level(logging.WARNING):
        parser.parse_file(tmp_path / "big.py")

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("Giant function chunked" in msg for msg in warnings), warnings


def test_missing_model_fails_fast(tmp_path, monkeypatch, caplog):
    """Без каталога модели сервер умирает сразу — ждать 60 с бессмысленно."""
    from src.core.embedder.onnx_client import OnnxEmbedderClient

    client = OnnxEmbedderClient(port=6199, model_name="no-such-model-xyz")
    started = time.perf_counter()
    with caplog.at_level(logging.ERROR, logger="mscodebase_server.onnx_client"):
        ok = client.ensure_server_running()
    elapsed = time.perf_counter() - started

    assert ok is False
    assert elapsed < 20.0, f"ожидание вместо отказа: {elapsed:.1f} с"
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "model directory not found" in messages
    assert "searched:" in messages


def test_resolver_is_shared_and_silent(tmp_path, monkeypatch):
    """Резолвер не создаёт каталогов и возвращает None для отсутствующей модели."""
    from src.core.embedder import model_paths

    assert model_paths.resolve_model_dir("definitely-not-a-model") is None
    monkeypatch.setattr(model_paths, "PROJECT_ROOT", tmp_path, raising=True)
    assert model_paths.resolve_model_dir("x") is None
    assert not (tmp_path / "models").exists()


@pytest.mark.parametrize("model", ["multilingual-e5-small-int8"])
def test_real_model_resolves_when_present(model):
    """На машине с моделями резолвер обязан найти рабочую копию (иначе skip)."""
    from src.core.embedder.model_paths import resolve_model_dir

    found = resolve_model_dir(model)
    if found is None:
        pytest.skip("модель не установлена в этом окружении")
    assert (found / "model_quantized.onnx").exists() or (found / "model.onnx").exists()
