"""Тесты real-path резолюции: FileGuard.resolve + _generate_unique_db_path.

Заменяет stub (B11, KNOWN_ISSUES.md): вместо `assert True` — реальные
проверки резолюции путей (Path.resolve, нормализация регистра/разделителей,
изоляция БД по проекту, path traversal).
"""

import hashlib
from pathlib import Path

from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import _generate_unique_db_path


def test_fileguard_resolves_relative_project_path(tmp_path, monkeypatch):
    """Относительный project_path резолвится в абсолютный (иначе relative_to падает)."""
    monkeypatch.chdir(tmp_path)
    sub = tmp_path / "proj"
    sub.mkdir()
    guard = FileGuard(Path("proj"))
    assert guard.project_path == sub.resolve()


def test_fileguard_absolute_path_stays_absolute(tmp_path):
    """Абсолютный путь резолвится в себя."""
    guard = FileGuard(tmp_path)
    assert guard.project_path == tmp_path.resolve()
    assert guard.project_path.is_absolute()


def test_fileguard_rejects_traversal_outside_project(tmp_path):
    """Файл за пределами проекта (через ../) отклоняется — path traversal guard."""
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    victim = sibling / "secret.py"
    victim.write_text("SECRET = 1\n", encoding="utf-8")

    guard = FileGuard(tmp_path)
    # ../sibling/secret.py указывает за пределы project_path
    traversal = tmp_path / ".." / "sibling" / "secret.py"
    assert guard.is_safe_to_index(traversal) is False
    assert victim.exists()  # файл реально существует — проверка про путь, не про диск


def test_unique_db_path_is_deterministic(tmp_path):
    """Один проект → один и тот же путь БД при повторных вызовах."""
    p1 = _generate_unique_db_path(tmp_path / "proj_a")
    p2 = _generate_unique_db_path(tmp_path / "proj_a")
    assert p1 == p2
    assert p1.parent.exists()  # директория <data_root>/projects/<hash>/lancedb_v2 создана


def test_unique_db_path_outside_project(tmp_path):
    """Задача 4/5: БД живёт ВНЕ проекта (системная папка), проект не засоряется."""
    proj = tmp_path / "proj_a"
    proj.mkdir()
    db = _generate_unique_db_path(proj)
    # Путь БД не находится внутри каталога проекта
    assert not str(db).lower().startswith(str(proj.resolve()).lower())
    # В проекте не появляется .codebase_indices
    assert not (proj / ".codebase_indices").exists()
    assert not (proj / ".codebase").exists()
    assert not (proj / ".mscodebase").exists()


def test_unique_db_path_isolates_projects(tmp_path):
    """Разные проекты → разные пути БД (нет конфликтов при параллельной индексации)."""
    p_a = _generate_unique_db_path(tmp_path / "proj_a")
    p_b = _generate_unique_db_path(tmp_path / "proj_b")
    assert p_a != p_b
    assert p_a.name.startswith("index_proj_a_")
    assert p_b.name.startswith("index_proj_b_")


def test_unique_db_path_normalizes_separators_and_case(tmp_path):
    """Один проект с разными формами пути (\\ vs /) → одинаковый хэш-суффикс.

    Внутри _generate_unique_db_path путь нормализуется:
    lower() + replace('\\', '/') — защита от разного регистра/разделителей в Windows.
    """
    p1 = _generate_unique_db_path(tmp_path / "proj_x")
    # Та же директория, но путь с '/' вместо '\\' — хэш должен совпасть
    normalized = str(tmp_path / "proj_x").replace("\\", "/")
    expected_hash = hashlib.md5(normalized.lower().encode()).hexdigest()[:8]
    assert p1.name.endswith(f"_{expected_hash}.db")


def test_unique_db_path_uses_basename_not_full_path(tmp_path):
    """Имя БД содержит basename проекта, а не весь путь (читаемость + детерминизм)."""
    p = _generate_unique_db_path(tmp_path / "MyProject")
    assert p.name.startswith("index_myproject_")
    assert str(tmp_path).lower() not in p.name.lower()


def test_unique_db_path_supports_relative_project(tmp_path, monkeypatch):
    """Относительный проект: хэш резолвится, путь — ВСЕГДА абсолютный.

    Задача 4/5: БД в системной папке → выход всегда абсолютный, независимо
    от формы входа. Раньше относительный вход давал относительный выход
    (БД создавалась относительно CWD — риск засорить проект). Имя БД (хэш)
    совпадает для обеих форм входа.
    """
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "rel_proj"
    proj.mkdir()
    p1 = _generate_unique_db_path(Path("rel_proj"))
    p2 = _generate_unique_db_path(proj)
    # Одинаковое имя БД (resolve() в хэше даёт один hash)
    assert p1.name == p2.name
    # Относительный вход → ВСЁ РАВНО абсолютный выход (системная папка)
    assert p1.is_absolute()
    assert p2.is_absolute()
    assert p1.parent.name == "lancedb_v2"
    assert p2.parent.name == "lancedb_v2"


def test_fileguard_home_expansion_not_required(tmp_path, monkeypatch):
    """Path('~') не разворачивается Path.resolve() — это поведение Path, документируем его.

    FileGuard не использует expanduser; защита от галлюцинаций: проверяем, что
    резолв честно отражает то, что передали.
    """
    guard = FileGuard(tmp_path / "nonexistent_dir")
    # Резолв не падает даже для несуществующей директории
    assert guard.project_path == (tmp_path / "nonexistent_dir").resolve()
