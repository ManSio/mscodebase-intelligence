"""
Module-docstring chunk (P3 drill-down): chunker emits the module docstring
as chunk 0 per .py file that has one; files without docstrings unchanged.
"""

import tempfile
from pathlib import Path

import pytest

from src.core.indexing.parser import CodeParser


@pytest.fixture
def tmp_py():
    """Временный .py-файл (удаляется после теста)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


def _chunks(path):
    parser = CodeParser()
    result = parser.parse_file(path)
    return result[0] if isinstance(result, tuple) else result


def test_module_docstring_is_chunk_zero(tmp_py):
    """Файл с docstring: chunk 0 — module docstring."""
    tmp_py.write_text(
        '"""ArtifactGC — очистка устаревших артефактов MCP."""\n'
        "\n"
        "import os\n"
        "\n"
        "\n"
        "def hello():\n"
        '    """Hi."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    chunks = _chunks(tmp_py)
    assert len(chunks) == 2
    head = chunks[0]
    assert head["type"] == "module_docstring"
    assert head["symbol_name"] == CodeParser.MODULE_DOC_SYMBOL
    assert "ArtifactGC" in head["text"]
    assert head["start_line"] == 1
    assert head["hierarchy_level"] == "module"
    # Остальные чанки — функции, порядок сохранён
    assert chunks[1]["type"] == "function_definition"


def test_no_docstring_unchanged(tmp_py):
    """Файл без docstring: chunk 0 — первая функция, как раньше."""
    tmp_py.write_text(
        "import os\n"
        "\n"
        "\n"
        "def hello():\n"
        '    """Hi."""\n'
        "    return 1\n"
        "\n"
        "\n"
        "def world():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    chunks = _chunks(tmp_py)
    assert len(chunks) == 2
    assert chunks[0]["type"] == "function_definition"
    assert chunks[0]["symbol_name"] == "hello"
    assert all(c["type"] != "module_docstring" for c in chunks)


def test_chunk_counts_fixture_file():
    """Фикстура репо: N функций + docstring → N+1 чанков, head — docstring."""
    from src.core.indexing.parser import CodeParser as _CP

    fixture = Path(__file__).resolve().parent.parent / "src" / "core" / "artifact_gc.py"
    assert fixture.exists()
    parser = _CP()
    chunks, _symbols = parser.parse_file(fixture)
    rest = [c for c in chunks if c["type"] != "module_docstring"]
    assert len(rest) >= 2  # функции (+ parts гигантской prune_stale_artifacts)
    assert len(chunks) == len(rest) + 1
    assert chunks[0]["type"] == "module_docstring"
    assert "ArtifactGC" in chunks[0]["text"]


def test_syntax_error_no_crash(tmp_py):
    """Битый файл: без исключений, поведение fallback без изменений."""
    tmp_py.write_text("def broken(:\n  ???\n", encoding="utf-8")
    chunks = _chunks(tmp_py)
    assert all(c["type"] != "module_docstring" for c in chunks)


def test_non_python_unchanged(tmp_py):
    """Не-Python: module-чанк не эмитится."""
    js_file = tmp_py.with_suffix(".js")
    js_file.write_text(
        "function hello() {\n  return 1;\n}\n",
        encoding="utf-8",
    )
    try:
        chunks = _chunks(js_file)
    finally:
        js_file.unlink(missing_ok=True)
    assert all(c.get("type") != "module_docstring" for c in chunks)
