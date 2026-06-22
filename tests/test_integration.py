"""
Интеграционные тесты.
"""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_project():
    """Создаёт временный проект."""
    temp_dir = Path(tempfile.mkdtemp())

    # Создаём тестовые файлы
    (temp_dir / "main.py").write_text('''
def main():
    """Главная функция."""
    print("Hello")

if __name__ == "__main__":
    main()
''')

    (temp_dir / "utils.py").write_text('''
def helper():
    """Вспомогательная функция."""
    return 42
''')

    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.slow
@pytest.mark.integration
def test_full_indexing_pipeline(temp_project):
    """Тест полного цикла индексации."""
    import shutil
    import tempfile

    from src.core.embedder import Embedder
    from src.core.indexer import Indexer
    from src.core.searcher import Searcher

    # Создаем уникальные директории для каждой тестовой функции
    temp_index_dir = Path(tempfile.mkdtemp())
    temp_model_dir = Path(tempfile.mkdtemp())

    try:
        # Инициализируем
        embedder = Embedder(model_dir=temp_model_dir)
        assert embedder.load()

        from src.core.file_guard import FileGuard

        file_guard = FileGuard(temp_project)
        indexer = Indexer(temp_index_dir, embedder, file_guard=file_guard)
        searcher = Searcher(indexer, embedder)
        indexer.searcher = searcher

        # Индексируем
        count = indexer.index_project(temp_project)
        assert count >= 2, (
            f"Должно быть проиндексировано минимум 2 файла, получено {count}"
        )

        # Проверяем статус
        status = indexer.get_status()
        assert status.get("total_files", 0) >= 2
        assert status.get("total_chunks", 0) >= 2

        # Ищем
        result = searcher.search("главная функция")
        assert "main" in result.lower() or "функци" in result.lower()

        # Проверяем, что результат содержит что-то полезное
        assert len(result) > 50, "Результат поиска должен быть содержательным"
    finally:
        # Очистка
        shutil.rmtree(temp_index_dir, ignore_errors=True)
        shutil.rmtree(temp_model_dir, ignore_errors=True)


@pytest.mark.slow
@pytest.mark.integration
def test_incremental_indexing(temp_project):
    """Тест инкрементальной индексации."""
    from src.core.embedder import Embedder
    from src.core.indexer import Indexer

    model_dir = temp_project / ".codebase_models"
    index_dir = temp_project / ".codebase_index"

    embedder = Embedder(model_dir=model_dir)
    embedder.load()

    from src.core.file_guard import FileGuard

    file_guard = FileGuard(temp_project)
    indexer = Indexer(index_dir, embedder, file_guard=file_guard)

    # Первая индексация
    count1 = indexer.index_project(temp_project)
    assert count1 >= 2

    # Вторая индексация (ничего не изменилось)
    count2 = indexer.index_project(temp_project)
    assert count2 == 0, "Ничего не должно переиндексироваться"

    # Меняем файл
    (temp_project / "main.py").write_text('''
def main():
    """Обновлённая главная функция."""
    print("Updated")
''')

    # Третья индексация (один файл изменился)
    count3 = indexer.index_project(temp_project)
    assert count3 == 1, "Должен переиндексироваться один файл"


@pytest.mark.slow
@pytest.mark.integration
def test_file_deletion(temp_project):
    """Тест удаления файла из индекса."""
    import shutil
    import tempfile

    from src.core.embedder import Embedder
    from src.core.indexer import Indexer

    # Создаем уникальные директории для каждой тестовой функции
    temp_index_dir = Path(tempfile.mkdtemp())
    temp_model_dir = Path(tempfile.mkdtemp())

    try:
        embedder = Embedder(model_dir=temp_model_dir)
        embedder.load()

        from src.core.file_guard import FileGuard

        file_guard = FileGuard(temp_project)
        indexer = Indexer(temp_index_dir, embedder, file_guard=file_guard)

        # Индексируем
        indexer.index_project(temp_project)
        status1 = indexer.get_status()

        # Удаляем файл
        (temp_project / "utils.py").unlink()

        # Переиндексируем
        indexer.index_project(temp_project)
        status2 = indexer.get_status()

        assert status2.get("total_files", 0) < status1.get("total_files", 0)
    finally:
        # Очистка
        shutil.rmtree(temp_index_dir, ignore_errors=True)
        shutil.rmtree(temp_model_dir, ignore_errors=True)
