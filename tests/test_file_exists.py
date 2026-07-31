"""Тесты FileGuard: проверка существования и безопасности файлов для индексации.

Заменяет stub (B11, KNOWN_ISSUES.md): вместо `assert True` — реальные
проверки `src/core/indexing/file_guard.py` на файлах во временной директории.
"""

from pathlib import Path

import pytest

from src.core.indexing.file_guard import FileGuard


def _write(path: Path, content: bytes = b"def foo():\n    return 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_existing_python_file_is_safe(tmp_path):
    """Существующий .py файл проходит все проверки FileGuard."""
    f = _write(tmp_path / "main.py")
    guard = FileGuard(tmp_path)
    assert f.exists()
    assert guard.is_safe_to_index(f) is True


def test_missing_file_is_not_safe(tmp_path):
    """Несуществующий файл отклоняется (stat → FileNotFoundError → False)."""
    guard = FileGuard(tmp_path)
    missing = tmp_path / "ghost.py"
    assert not missing.exists()
    assert guard.is_safe_to_index(missing) is False


def test_unsupported_extension_is_skipped(tmp_path):
    """Расширение вне INDEX_EXTENSIONS → False до обращения к диску."""
    f = _write(tmp_path / "image.png", b"\x89PNG\r\n\x1a\n")
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(f) is False


def test_binary_file_with_null_byte_is_skipped(tmp_path):
    """Null-байт в первых 1024 байтах = 100% бинарник → False."""
    f = _write(tmp_path / "blob.bin", b"\x00\x01\x02\x03")
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(f) is False


def test_empty_file_is_safe(tmp_path):
    """Пустой файл не считается бинарным и проходит проверку."""
    f = _write(tmp_path / "empty.py", b"")
    guard = FileGuard(tmp_path)
    guard.retry_delay = 0  # ускоряем retry-цикл для st_size == 0
    assert guard.is_safe_to_index(f) is True


def test_minified_file_is_skipped(tmp_path):
    """.min. в имени файла → False (эвристика минификации)."""
    f = _write(tmp_path / "bundle.min.js")
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(f) is False


def test_large_file_is_skipped(tmp_path):
    """Файл больше MAX_FILE_SIZE_BYTES → False."""
    big = b"x" * (FileGuard.MAX_FILE_SIZE_BYTES + 1)
    f = _write(tmp_path / "huge.py", big)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(f) is False


def test_file_outside_project_is_rejected(tmp_path, tmp_path_factory):
    """Файл вне корня проекта → relative_to ValueError → False."""
    outside = tmp_path_factory.mktemp("outside") / "other.py"
    _write(outside)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(outside) is False


def test_should_skip_system_dir(tmp_path):
    """Системные директории (venv, .git) пропускаются Layer 1."""
    guard = FileGuard(tmp_path)
    assert guard.should_skip_dir(".git") is True
    assert guard.should_skip_dir("venv") is True
    assert guard.should_skip_dir("src") is False


def test_should_skip_file_in_system_dir(tmp_path):
    """Файл внутри системной директории пропускается."""
    f = _write(tmp_path / ".git" / "config.py")
    guard = FileGuard(tmp_path)
    assert guard.should_skip_file(f) is True


@pytest.mark.parametrize(
    "name,expected",
    [
        ("app.py", True),
        ("script.sh", True),
        ("readme.md", True),
        ("notes.txt", True),
        ("data.json", True),
        ("image.png", False),
        ("archive.zip", False),
        ("Makefile", False),
    ],
)
def test_extension_matrix(tmp_path, name, expected):
    """Матрица расширений против INDEX_EXTENSIONS (без I/O-зависимых проверок)."""
    f = _write(tmp_path / name, b"x" * 4)
    guard = FileGuard(tmp_path)
    assert guard.is_safe_to_index(f) is expected
