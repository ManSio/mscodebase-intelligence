"""Тесты ArtifactGC и защитных механизмов путей (аудит 2026-08-13).

Покрывает:
1. prune_stale_artifacts: неактивные папки старше порога удаляются; активные — нет.
2. Пустые проектные папки удаляются сразу (мусор от прерванных тестов).
3. Удаляются ТОЛЬКО папки вида <hash8> (hex) — случайные папки не трогаются.
4. Старая телеметрия (>90 дней) чистится и в активных проектах.
5. check_disk_space возвращает структуру с ok/free_mb.
6. get_crash_log_path / get_logs_dir живут в data_root (не HOME).
7. get_onnx_models_base — единый общий кэш моделей в data_root.
"""

import os
import time
from pathlib import Path

from src.core.artifact_gc import prune_stale_artifacts
from src.core.artifact_paths import (
    check_disk_space,
    get_crash_log_path,
    get_data_root,
    get_logs_dir,
    get_onnx_models_base,
    get_project_dir,
    project_hash,
)


def _make_old(path: Path, days: float) -> None:
    """Делает папку/файл «старым» (mtime в прошлом)."""
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def _create_project_dir(data_root: Path, project: Path, days: float = 60) -> Path:
    """Создаёт проектный каталог с данными и «возрастом» days."""
    pd = get_project_dir(project)
    (pd / "lancedb_v2").mkdir(parents=True, exist_ok=True)
    (pd / "lancedb_v2" / "chunk.lance").write_text("data", encoding="utf-8")
    _make_old(pd, days)
    _make_old(pd / "lancedb_v2", days)
    _make_old(pd / "lancedb_v2" / "chunk.lance", days)
    return pd


# ══════════════════════════════════════════════════════════
# prune_stale_artifacts
# ══════════════════════════════════════════════════════════


def test_prune_removes_inactive_old_project(_isolated_data_root, tmp_path):
    project = tmp_path / "dead_proj"
    project.mkdir()
    pd = _create_project_dir(_isolated_data_root, project, days=60)
    assert pd.exists()

    report = prune_stale_artifacts(active_hashes=set())

    assert report["removed_projects"] == 1
    assert not pd.exists()


def test_prune_keeps_active_project(_isolated_data_root, tmp_path):
    project = tmp_path / "live_proj"
    project.mkdir()
    pd = _create_project_dir(_isolated_data_root, project, days=60)
    active = {project_hash(project)}

    report = prune_stale_artifacts(active_hashes=active)

    assert report["removed_projects"] == 0
    assert pd.exists()


def test_prune_removes_empty_dir_immediately(_isolated_data_root, tmp_path):
    """Пустая папка (только пустые поддиректории) удаляется сразу, без возраста."""
    project = tmp_path / "ghost_proj"
    project.mkdir()
    pd = get_project_dir(project)  # создаст пустую папку
    (pd / "lancedb_v2").mkdir(parents=True, exist_ok=True)  # пустая вложенная

    report = prune_stale_artifacts(active_hashes=set())

    assert report["removed_projects"] == 1
    assert not pd.exists()


def test_prune_ignores_non_hash_dirs(_isolated_data_root):
    """Случайные папки в projects/ (не hex-хэш) не удаляются."""
    projects_root = _isolated_data_root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    stray = projects_root / "manual_backup"
    stray.mkdir()
    (stray / "notes.txt").write_text("keep me", encoding="utf-8")
    _make_old(stray, 200)

    report = prune_stale_artifacts(active_hashes=set())

    assert report["removed_projects"] == 0
    assert stray.exists()


def test_prune_removes_old_telemetry_even_active(_isolated_data_root, tmp_path):
    """Телеметрия старше 90 дней чистится даже в активных проектах (кэш)."""
    project = tmp_path / "live_proj"
    project.mkdir()
    pd = _create_project_dir(_isolated_data_root, project, days=1)
    tel = pd / "telemetry"
    tel.mkdir()
    old_file = tel / "2026-01-01.json"
    old_file.write_text("[]", encoding="utf-8")
    _make_old(old_file, 100)
    fresh_file = tel / "2026-08-13.json"
    fresh_file.write_text("[]", encoding="utf-8")

    report = prune_stale_artifacts(active_hashes={project_hash(project)})

    assert not old_file.exists()
    assert fresh_file.exists()
    assert report["removed_telemetry"] == 1


def test_prune_active_hashes_from_registry(_isolated_data_root, tmp_path):
    """При active_hashes=None — из глобального реестра (в тестах пуст)."""
    project = tmp_path / "proj"
    project.mkdir()
    _create_project_dir(_isolated_data_root, project, days=60)

    report = prune_stale_artifacts()

    # Реестр пуст → папка неактивна и стара → удалена
    assert report["removed_projects"] == 1


def test_prune_idempotent(_isolated_data_root, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _create_project_dir(_isolated_data_root, project, days=60)

    first = prune_stale_artifacts(active_hashes=set())
    second = prune_stale_artifacts(active_hashes=set())

    assert first["removed_projects"] == 1
    assert second["removed_projects"] == 0  # повторный вызов ничего не находит


# ══════════════════════════════════════════════════════════
# check_disk_space
# ══════════════════════════════════════════════════════════


def test_check_disk_space_shape(_isolated_data_root):
    result = check_disk_space()

    assert isinstance(result, dict)
    assert "ok" in result
    assert "free_mb" in result
    assert result["free_mb"] >= 0


# ══════════════════════════════════════════════════════════
# Централизация путей (унификация 2026-08-13)
# ══════════════════════════════════════════════════════════


def test_logs_dir_inside_data_root(_isolated_data_root):
    logs = get_logs_dir()

    assert logs == _isolated_data_root / "logs"
    assert logs.exists()


def test_crash_log_inside_data_root(_isolated_data_root):
    crash = get_crash_log_path()

    assert crash == _isolated_data_root / "logs" / "crash.json"
    # Не в HOME: путь обязан начинаться с data_root
    assert str(crash).startswith(str(_isolated_data_root))


def test_onnx_models_base_inside_data_root(_isolated_data_root):
    base = get_onnx_models_base()

    assert base == _isolated_data_root / "models" / ".codebase_models" / "onnx"


def test_data_root_never_in_home_when_env_set(_isolated_data_root):
    """MSCODEBASE_DATA_DIR побеждает HOME-пути (нет ~/.cache/mscodebase)."""
    root = get_data_root()

    assert str(root).startswith(str(_isolated_data_root))
    assert ".cache" not in str(root)
