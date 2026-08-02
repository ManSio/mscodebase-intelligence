"""Тесты ArtifactPaths — единая точка путей артефактов ВНЕ проекта (Задача 4/5).

Покрывает:
1. Резолюция data root (default / MSCODEBASE_DATA_DIR / legacy BASE_INDEX_DIR).
2. Per-project изоляция через хэш (разные проекты → разные папки).
3. Детерминизм (один проект → одна папка).
4. Миграция legacy-артефактов из проекта (.codebase_indices, .codebase/graph.db,
   .mscodebase/telemetry) в системную папку — best-effort и идемпотентная.
"""

from pathlib import Path

import pytest

from src.core.artifact_paths import (
    get_branches_dir,
    get_db_path,
    get_data_root,
    get_graph_db_path,
    get_intelligence_dir,
    get_metrics_dir,
    get_project_dir,
    get_progress_file,
    get_telemetry_dir,
    legacy_project_dirs,
    migrate_legacy_artifacts,
    project_hash,
)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch) -> Path:
    """Изолированный data root (не трогаем реальный LOCALAPPDATA)."""
    root = tmp_path / "data_root"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(root))
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Временный проект."""
    p = tmp_path / "my_proj"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ══════════════════════════════════════════════════════════
# Data root
# ══════════════════════════════════════════════════════════


def test_data_root_uses_env_override(tmp_path, monkeypatch):
    root = tmp_path / "custom_root"
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(root))
    assert get_data_root() == root
    assert root.exists()


def test_data_root_legacy_absolute_base_index_dir(tmp_path, monkeypatch):
    """Абсолютный BASE_INDEX_DIR уважается как legacy data root."""
    monkeypatch.delenv("MSCODEBASE_DATA_DIR", raising=False)
    legacy = tmp_path / "legacy_indices"
    monkeypatch.setenv("BASE_INDEX_DIR", str(legacy))
    assert get_data_root() == legacy


def test_data_root_default_not_in_project(tmp_path, monkeypatch):
    """Default root — системная папка, НЕ внутри проекта."""
    monkeypatch.delenv("MSCODEBASE_DATA_DIR", raising=False)
    monkeypatch.delenv("BASE_INDEX_DIR", raising=False)
    root = get_data_root()
    # На любой платформе default root находится вне проекта
    assert not str(root).lower().startswith(str(tmp_path).lower())


# ══════════════════════════════════════════════════════════
# Per-project изоляция и детерминизм
# ══════════════════════════════════════════════════════════


def test_project_hash_deterministic(project):
    assert project_hash(project) == project_hash(project)
    assert len(project_hash(project)) == 8


def test_project_isolation(data_root, tmp_path):
    p_a = tmp_path / "proj_a"
    p_b = tmp_path / "proj_b"
    p_a.mkdir()
    p_b.mkdir()
    assert get_project_dir(p_a) != get_project_dir(p_b)


def test_db_path_outside_project(data_root, project):
    db = get_db_path(project)
    assert db.is_absolute()
    # Путь БД не внутри проекта
    assert not str(db).lower().startswith(str(project.resolve()).lower())
    # Структура: <root>/projects/<hash>/lancedb_v2/index_my_proj_<hash>.db
    assert db.parent.name == "lancedb_v2"
    assert db.name.startswith("index_my_proj_")
    assert db.parent.exists()


def test_all_paths_inside_project_dir(data_root, project):
    """Все артефакты — под <root>/projects/<hash>/, вне проекта."""
    proj_dir = get_project_dir(project)
    for path in [
        get_db_path(project),
        get_graph_db_path(project),
        get_intelligence_dir(project),
        get_metrics_dir(project),
        get_branches_dir(project),
        get_telemetry_dir(project),
        get_progress_file(project),
    ]:
        assert str(path.resolve()).startswith(str(proj_dir.resolve()))
        assert not str(path.resolve()).startswith(str(project.resolve()))


# ══════════════════════════════════════════════════════════
# Миграция legacy-артефактов
# ══════════════════════════════════════════════════════════


def test_legacy_project_dirs_detected(project):
    (project / ".codebase_indices").mkdir(parents=True)
    (project / ".codebase").mkdir(parents=True)
    (project / ".mscodebase").mkdir(parents=True)
    found = legacy_project_dirs(project)
    assert len(found) == 3


def test_migrate_moves_legacy_index(data_root, project):
    old = project / ".codebase_indices" / "lancedb_v2"
    old.mkdir(parents=True)
    (old / "index_proj.db").touch()

    report = migrate_legacy_artifacts(project)
    new_dir = get_project_dir(project)

    assert (new_dir / "lancedb_v2" / "index_proj.db").exists()
    assert not (project / ".codebase_indices" / "lancedb_v2").exists()
    assert ".codebase_indices/lancedb_v2" in report


def test_migrate_moves_graph_db(data_root, project):
    old_codebase = project / ".codebase"
    old_codebase.mkdir(parents=True)
    (old_codebase / "graph.db").write_text("sqlite", encoding="utf-8")

    migrate_legacy_artifacts(project)
    new_dir = get_project_dir(project)

    assert (new_dir / "graph.db").exists()
    assert not (old_codebase / "graph.db").exists()


def test_migrate_moves_telemetry(data_root, project):
    old_telemetry = project / ".mscodebase" / "telemetry"
    old_telemetry.mkdir(parents=True)
    (old_telemetry / "2026-08-01.json").write_text("[]", encoding="utf-8")

    migrate_legacy_artifacts(project)
    new_dir = get_project_dir(project)

    assert (new_dir / "telemetry" / "2026-08-01.json").exists()


def test_migrate_idempotent(data_root, project):
    old = project / ".codebase_indices" / "metrics"
    old.mkdir(parents=True)
    (old / "job_history.json").write_text("[]", encoding="utf-8")

    migrate_legacy_artifacts(project)
    report2 = migrate_legacy_artifacts(project)

    new_dir = get_project_dir(project)
    assert (new_dir / "metrics" / "job_history.json").exists()
    # Повторный вызов ничего не переносит (идемпотентность)
    assert ".codebase_indices/metrics" not in report2


def test_migrate_skips_absent_legacy(data_root, project):
    """Проект без legacy-артефактов — миграция не падает, отчёт пуст."""
    report = migrate_legacy_artifacts(project)
    assert report == {}
    assert get_project_dir(project).exists()


def test_get_project_dir_triggers_migration_on_first_create(data_root, project):
    """get_project_dir мигрирует при ПЕРВОМ создании папки (автоматически)."""
    old = project / ".codebase_indices" / "intelligence"
    old.mkdir(parents=True)
    (old / "project_memory.json").write_text("[]", encoding="utf-8")

    new_dir = get_project_dir(project)  # первый вызов — миграция
    assert (new_dir / "intelligence" / "project_memory.json").exists()


def test_db_path_after_migration_matches_legacy_name(data_root, project):
    """Имя БД после миграции совпадает с legacy (данные не пересоздаются)."""
    old = project / ".codebase_indices" / "lancedb_v2"
    old.mkdir(parents=True)
    db_name = f"index_my_proj_{project_hash(project)}.db"
    (old / db_name).write_text("lance", encoding="utf-8")

    db = get_db_path(project)
    assert db.name == db_name
    assert db.exists()  # файл перенесён, не пересоздан
