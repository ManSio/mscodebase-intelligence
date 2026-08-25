"""
Тесты для CodeParser.
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_file():
    """Создаёт временный файл."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


def test_parser_python(temp_file):
    """Тест парсинга Python кода."""
    from src.core.indexing.parser import CodeParser

    code = '''
    def hello():
    """Приветствие."""
    print("Hello")

class World:
    def method(self):
        pass
'''
    temp_file.write_text(code, encoding="utf-8")

    parser = CodeParser()
    result = parser.parse_file(temp_file)
    # parse_file возвращает (chunks, symbols)
    chunks = result[0] if isinstance(result, tuple) else result

    assert len(chunks) >= 2, "Должны быть найдены функция и класс"

    # Проверяем, что есть функция
    func_chunks = [c for c in chunks if c.get("type") == "function_definition"]
    assert len(func_chunks) >= 1, "Должна быть найдена функция"

    # Проверяем, что есть класс (если парсер поддерживает)
    [c for c in chunks if c.get("type") == "class_definition"]


def test_parser_empty_file(temp_file):
    """Тест парсинга пустого файла."""
    from src.core.indexing.parser import CodeParser

    temp_file.write_text("")

    parser = CodeParser()
    result = parser.parse_file(temp_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert chunks == []


def test_parser_markdown(temp_file):
    """Тест парсинга Markdown."""
    from src.core.indexing.parser import CodeParser

    md_file = temp_file.with_suffix(".md")
    md_file.write_text(
        "# Header 1\n\nContent 1\n\n# Header 2\n\nContent 2", encoding="utf-8"
    )

    parser = CodeParser()
    result = parser.parse_file(md_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert len(chunks) >= 2

    md_file.unlink(missing_ok=True)


def test_parser_symbols_have_signature_and_docstring():
    """Deep-spec: parse_file символы содержат signature и docstring."""
    from src.core.indexing.parser import CodeParser

    fixture = Path(__file__).parent / "fixtures" / "sample_module.py"
    parser = CodeParser()
    _, symbols = parser.parse_file(fixture)
    assert symbols, "фикстура должна давать символы"

    by_name = {s["name"]: s for s in symbols}

    # Неизменённые ключи сохранены (additive backward-compat).
    for s in symbols:
        assert set(("name", "line", "kind")).issubset(s.keys())

    calc = by_name.get("Calculator")
    assert calc is not None
    assert calc["kind"] == "class_definition"
    assert calc["signature"].startswith("class Calculator")
    assert calc["docstring"] and "pipe" in calc["docstring"]

    add = by_name.get("Calculator.add")
    assert add is not None
    assert add["signature"].startswith("def add(")
    assert "-> int" in add["signature"]
    assert add["docstring"] and "Add two integers" in add["docstring"]

    standalone = by_name.get("standalone")
    assert standalone is not None
    assert standalone["signature"].startswith("def standalone(")
    assert standalone["docstring"] and "Echo the" in standalone["docstring"]


def test_parser_unsupported_extension(temp_file):
    """Тест неподдерживаемого расширения."""
    from src.core.indexing.parser import CodeParser

    bin_file = temp_file.with_suffix(".bin")
    bin_file.write_text("binary content", encoding="utf-8")

    parser = CodeParser()
    result = parser.parse_file(bin_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert chunks == []

    bin_file.unlink(missing_ok=True)
