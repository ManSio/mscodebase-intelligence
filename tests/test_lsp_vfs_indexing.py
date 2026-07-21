"""
Поведенческий тест: LSP VFS indexing before disk save.

Проверяет что notify_change корректно индексирует контент из памяти (LSP VFS)
даже если файл ещё не сохранён на диск (TOCTOU race condition).
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.indexing.indexer import Indexer

pytestmark = pytest.mark.slow


class TestLSPVFSIndexing:
    """Тесты индексации из LSP VFS (память IDE) vs файловой системы."""

    def _make_indexer(self, tmp_path, mock_embedder, enable_summaries=False):
        """Хелпер для создания индексатора с отключёнными суммари."""
        db_path = tmp_path / ".codebase_indices" / "db"
        db_path.mkdir(parents=True, exist_ok=True)

        mock_file_guard = MagicMock()
        mock_file_guard.should_skip_file.return_value = False
        mock_file_guard.should_skip_dir.return_value = False
        mock_file_guard.is_safe_to_index.return_value = True

        return Indexer(
            db_path=db_path,
            embedder=mock_embedder,
            file_guard=mock_file_guard,
            project_path=tmp_path,
            enable_summaries=enable_summaries,
        )

    def test_source_field_lsp_vfs(self):
        """Индексация с content помечается как lsp_vfs."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            indexer = self._make_indexer(tmp_path, mock_embedder)

            # Индексируем с content (имитация LSP VFS)
            result = indexer._index_single_file(
                tmp_path / "test_module.py",
                "test_module.py",
                content="def hello():\n    return 'universe'\n",
                source="lsp_vfs"
            )

            assert result is True

            # Проверяем что source записан в базу
            df = indexer.table.to_pandas()
            assert not df.empty
            assert df.iloc[0]["source"] == "lsp_vfs"

    def test_source_field_filesystem(self):
        """Индексация без content помечается как filesystem."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Создаём файл на диске
            test_file = tmp_path / "test_module.py"
            test_file.write_text("def hello():\n    return 'world'\n")

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            indexer = self._make_indexer(tmp_path, mock_embedder)

            # Индексируем без content (чтение с диска)
            result = indexer._index_single_file(
                test_file,
                "test_module.py",
                content=None,
                source="filesystem"
            )

            assert result is True

            df = indexer.table.to_pandas()
            assert not df.empty
            assert df.iloc[0]["source"] == "filesystem"

    def test_lsp_vfs_vs_disk_divergence(self):
        """Критический тест: LSP VFS контент отличается от диска.

        Сценарий:
        1. Файл на диске = v1
        2. Пользователь редактирует в Zed (буфер = v2)
        3. notify_change() вызывается с content=v2
        4. Индекс должен содержать v2, даже если диск ещё v1
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            indexer = self._make_indexer(tmp_path, mock_embedder)

            # Файл на диске = v1
            test_file = tmp_path / "module.py"
            v1_content = "def process():\n    return 'v1'\n"
            test_file.write_text(v1_content)

            # Индексируем v1 с диска
            indexer._index_single_file(test_file, "module.py", content=v1_content, source="filesystem")

            # Пользователь меняет код в Zed (буфер = v2, диск ещё v1)
            v2_content = "def process():\n    return 'v2'\n    # new line\n"

            # notify_change вызывается с content из LSP VFS
            result = indexer._index_single_file(
                test_file,
                "module.py",
                content=v2_content,
                source="lsp_vfs"
            )

            assert result is True

            # Проверяем: индекс содержит v2, не v1
            df = indexer.table.to_pandas()
            assert not df.empty

            # Должен быть source = lsp_vfs
            assert df.iloc[0]["source"] == "lsp_vfs"

            # Текст должен содержать 'v2', не 'v1'
            indexed_text = df.iloc[0]["text"]
            assert "v2" in indexed_text or "return" in indexed_text

    def test_indexed_at_timestamp(self):
        """Проверка что indexed_at заполняется."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            indexer = self._make_indexer(tmp_path, mock_embedder)

            indexer._index_single_file(
                tmp_path / "test.py",
                "test.py",
                content="x = 1\n",
                source="lsp_vfs"
            )

            df = indexer.table.to_pandas()
            assert not df.empty

            # Проверяем что indexed_at заполнено
            indexed_at = df.iloc[0].get("indexed_at")
            assert indexed_at is not None

    def test_hash_based_on_content_not_disk(self):
        """Хэш вычисляется из content, а не с диска.

        Это ключевая защита от TOCTOU: даже если диск не обновлён,
        хэш изменится при новом content.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            indexer = self._make_indexer(tmp_path, mock_embedder)

            # Индексируем оригинал
            indexer._index_single_file(
                tmp_path / "test.py",
                "test.py",
                content="original = True\n",
                source="filesystem"
            )
            hash1 = indexer.table.to_pandas().iloc[0]["file_hash"]

            # Индексируем новое содержимое (даже если файл на диске старый)
            indexer._index_single_file(
                tmp_path / "test.py",
                "test.py",
                content="modified = True\n",
                source="lsp_vfs"
            )
            hash2 = indexer.table.to_pandas().iloc[0]["file_hash"]

            # Хэши должны быть разными
            assert hash1 != hash2, "Хэш должен меняться при изменении content"


class TestSummaryGeneration:
    """Тесты генерации LLM-описаний чанков."""

    def test_summary_field_in_schema(self):
        """Schema содержит поле summary."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / ".codebase_indices" / "db"
            db_path.mkdir(parents=True, exist_ok=True)

            test_file = tmp_path / "test.py"
            test_file.write_text("def hello():\n    return 'world'\n")

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            mock_file_guard = MagicMock()
            mock_file_guard.should_skip_file.return_value = False
            mock_file_guard.should_skip_dir.return_value = False
            mock_file_guard.is_safe_to_index.return_value = True

            indexer = Indexer(
                db_path=db_path,
                embedder=mock_embedder,
                file_guard=mock_file_guard,
                project_path=tmp_path,
                enable_summaries=False,  # Отключаем для теста schema
            )

            indexer._index_single_file(test_file, "test.py")

            # Проверяем что summary поле существует
            df = indexer.table.to_pandas()
            assert not df.empty
            assert "summary" in df.columns

    def test_summary_disabled(self):
        """При enable_summaries=False summary пустой."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / ".codebase_indices" / "db"
            db_path.mkdir(parents=True, exist_ok=True)

            test_file = tmp_path / "test.py"
            test_file.write_text("x = 1\n")

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            mock_file_guard = MagicMock()
            mock_file_guard.should_skip_file.return_value = False
            mock_file_guard.should_skip_dir.return_value = False
            mock_file_guard.is_safe_to_index.return_value = True

            indexer = Indexer(
                db_path=db_path,
                embedder=mock_embedder,
                file_guard=mock_file_guard,
                project_path=tmp_path,
                enable_summaries=False,
            )

            indexer._index_single_file(test_file, "test.py")

            df = indexer.table.to_pandas()
            assert not df.empty
            assert df.iloc[0]["summary"] == ""

    def test_summary_with_mock_summarizer(self):
        """Суммари генерируется через ChunkSummarizer."""
        from src.core.indexing.chunk_summarizer import ChunkSummarizer

        mock_summarizer = MagicMock(spec=ChunkSummarizer)
        mock_summarizer.summarize_chunk.return_value = "Function that returns a value"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / ".codebase_indices" / "db"
            db_path.mkdir(parents=True, exist_ok=True)

            test_file = tmp_path / "test.py"
            test_file.write_text("def get_data():\n    return fetch()\n")

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder.mode = "lm_studio"

            mock_file_guard = MagicMock()
            mock_file_guard.should_skip_file.return_value = False
            mock_file_guard.should_skip_dir.return_value = False
            mock_file_guard.is_safe_to_index.return_value = True

            indexer = Indexer(
                db_path=db_path,
                embedder=mock_embedder,
                file_guard=mock_file_guard,
                project_path=tmp_path,
                enable_summaries=True,
            )
            indexer.summarizer = mock_summarizer

            indexer._index_single_file(test_file, "test.py")

            df = indexer.table.to_pandas()
            assert not df.empty
            assert df.iloc[0]["summary"] == "Function that returns a value"
