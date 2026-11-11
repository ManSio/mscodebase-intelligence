"""Поведенческий тест: LSP VFS indexing before disk save.

Проверяет, что notify_change корректно индексирует контент из памяти (LSP VFS)
даже если файл ещё не сохранён на диск (TOCTOU race condition).

Переписано 2026-11-08 под Phase 3: чанки лежат в SQLite (`chunks.db`), а не в
LanceDB-таблице, поэтому проверки идут через `indexer._chunk_store`, а не через
`indexer.table`. Поле `source` в text-first хранилище не сохраняется — тесты на
него удалены вместе с LanceDB-схемой; сама гарантия (индексируется буфер, а не
диск) проверяется здесь напрямую.
"""

from unittest.mock import MagicMock

import pytest

from src.core.indexing.indexer import Indexer
from src.sources.local_fs import LocalFsSource

pytestmark = pytest.mark.slow


class TestLSPVFSIndexing:
    """Тесты индексации из LSP VFS (память IDE) vs файловой системы."""

    def _make_indexer(self, project_path):
        """Индексатор на временном проекте (Phase 3: SQLite chunk store)."""
        mock_embedder = MagicMock()
        mock_embedder.embed_batch.return_value = [[0.1] * 1024]
        mock_embedder.mode = "lm_studio"

        mock_file_guard = MagicMock()
        mock_file_guard.should_skip_file.return_value = False
        mock_file_guard.should_skip_dir.return_value = False
        mock_file_guard.is_safe_to_index.return_value = True

        indexer = Indexer(
            db_path=project_path / ".codebase_indices" / "db",
            embedder=mock_embedder,
            file_guard=mock_file_guard,
            project_path=project_path,
            enable_summaries=False,
            # core не конструирует источник сам: его передаёт composition root
            # или тест (Фаза 2, гейт слоёв). Без него Indexer падает с
            # ValueError — 4 slow-теста дрейфовали, потому что маркер `slow`
            # исключён addopts и CI их не видел (KNOWN_ISSUES 2026-11-11).
            source=LocalFsSource(project_path),
        )
        return indexer

    @staticmethod
    def _records(indexer):
        store = indexer._chunk_store
        assert store is not None, "Phase 3 SQLite chunk store не подключён"
        return store.all_records()

    def test_lsp_vfs_content_indexed_without_disk(self, tmp_path):
        """Файла нет на диске, но content из буфера индексируется."""
        indexer = self._make_indexer(tmp_path)

        result = indexer._index_single_file(
            tmp_path / "test_module.py",
            "test_module.py",
            content="def hello():\n    return 'universe'\n",
            source="lsp_vfs",
        )

        assert result is True
        records = self._records(indexer)
        assert records, "буфер LSP VFS не попал в индекс"
        assert any("universe" in r["text"] for r in records)

    def test_lsp_vfs_content_beats_disk(self, tmp_path):
        """Критический тест TOCTOU: диск = v1, буфер = v2 → в индексе v2.

        Регрессия 2026-11-08: IndexParser читал файл с диска и игнорировал
        переданный content, поэтому notify_change индексировал старую версию.
        """
        indexer = self._make_indexer(tmp_path)
        test_file = tmp_path / "module.py"
        test_file.write_text("def process():\n    return 'v1'\n", encoding="utf-8")

        result = indexer._index_single_file(
            test_file,
            "module.py",
            content="def process():\n    return 'v2'\n    # new line\n",
            source="lsp_vfs",
        )

        assert result is True
        records = self._records(indexer)
        assert records
        joined = "\n".join(r["text"] for r in records)
        assert "v2" in joined
        assert "v1" not in joined

    def test_indexed_at_timestamp(self, tmp_path):
        """indexed_at заполняется при записи в SQLite-хранилище."""
        indexer = self._make_indexer(tmp_path)

        indexer._index_single_file(
            tmp_path / "test.py", "test.py", content="x = 1\n", source="lsp_vfs"
        )

        records = self._records(indexer)
        assert records
        assert all(r.get("indexed_at") for r in records)

    def test_hash_based_on_content_not_disk(self, tmp_path):
        """Хэш вычисляется из content, а не с диска.

        Ключевая защита от TOCTOU: даже если диск не обновлён, хэш изменится
        при новом content и повторная запись не будет пропущена как «не
        изменилось».
        """
        indexer = self._make_indexer(tmp_path)
        test_file = tmp_path / "test.py"
        # На диске пусто/старое — оба раза индексируем буфер.
        test_file.write_text("original = True\n", encoding="utf-8")

        indexer._index_single_file(
            test_file, "test.py", content="original = True\n", source="filesystem"
        )
        hash1 = self._records(indexer)[0]["file_hash"]

        indexer._index_single_file(
            test_file, "test.py", content="modified = True\n", source="lsp_vfs"
        )
        hash2 = self._records(indexer)[0]["file_hash"]

        assert hash1 != hash2, "Хэш должен меняться при изменении content"


class TestSummaryGeneration:
    """LLM-описания чанков относятся к legacy dense-пути записи.

    В Phase 3 `DBWriter.write_text_records` пишет только текст: колонки
    `summary` в SQLite-схеме нет, суммаризатор не вызывается. Тесты сохранены
    как явные skip, чтобы не выдавать отсутствие покрытия за зелёный прогон;
    при возврате dense-пути их нужно раскомментировать и перевести на
    LanceDB-таблицу.
    """

    @pytest.mark.skip(
        reason="Phase 3 text-first store (chunks.db) has no `summary` column; "
        "summaries are produced only by the legacy dense write path"
    )
    def test_summary_field_in_schema(self, tmp_path):
        indexer = self._make_indexer(tmp_path)
        indexer._index_single_file(tmp_path / "test.py", "test.py")
        assert "summary" in indexer._chunk_store.all_records()[0]

    @pytest.mark.skip(
        reason="Phase 3 text-first store (chunks.db) has no `summary` column; "
        "summaries are produced only by the legacy dense write path"
    )
    def test_summary_disabled(self, tmp_path):
        indexer = self._make_indexer(tmp_path)
        indexer._index_single_file(tmp_path / "test.py", "test.py")
        assert indexer._chunk_store.all_records()[0].get("summary", "") == ""

    @pytest.mark.skip(
        reason="Phase 3 text-first store (chunks.db) has no `summary` column; "
        "summaries are produced only by the legacy dense write path"
    )
    def test_summary_with_mock_summarizer(self, tmp_path):
        indexer = self._make_indexer(tmp_path)
        indexer._index_single_file(tmp_path / "test.py", "test.py")
        assert indexer._chunk_store.all_records()[0].get("summary", "") == ""
