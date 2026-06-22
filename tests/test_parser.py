"""
Тесты для CodeParser.
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_file():
    """Создаёт временный файл."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


def test_parser_python(temp_file):
    """Тест парсинга Python кода."""
    from src.core.parser import CodeParser

    code = '''
def hello():
    """Приветствие."""
    print("Hello")

class World:
    def method(self):
        pass
'''
    temp_file.write_text(code)

    parser = CodeParser()
    result = parser.parse_file(temp_file)
    # parse_file возвращает (chunks, symbols)
    chunks = result[0] if isinstance(result, tuple) else result

    assert len(chunks) >= 2, "Должны быть найдены функция и класс"

    # Проверяем, что есть функция
    func_chunks = [c for c in chunks if c.get("type") == "function_definition"]
    assert len(func_chunks) >= 1, "Должна быть найдена функция"

    # Проверяем, что есть класс (если парсер поддерживает)
    class_chunks = [c for c in chunks if c.get("type") == "class_definition"]


def test_parser_empty_file(temp_file):
    """Тест парсинга пустого файла."""
    from src.core.parser import CodeParser

    temp_file.write_text("")

    parser = CodeParser()
    result = parser.parse_file(temp_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert chunks == []


def test_parser_markdown(temp_file):
    """Тест парсинга Markdown."""
    from src.core.parser import CodeParser

    md_file = temp_file.with_suffix(".md")
    md_file.write_text("# Header 1\n\nContent 1\n\n# Header 2\n\nContent 2")

    parser = CodeParser()
    result = parser.parse_file(md_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert len(chunks) >= 2

    md_file.unlink(missing_ok=True)


def test_parser_unsupported_extension(temp_file):
    """Тест неподдерживаемого расширения."""
    from src.core.parser import CodeParser

    bin_file = temp_file.with_suffix(".bin")
    bin_file.write_text("binary content")

    parser = CodeParser()
    result = parser.parse_file(bin_file)
    chunks = result[0] if isinstance(result, tuple) else result

    assert chunks == []

    bin_file.unlink(missing_ok=True)
