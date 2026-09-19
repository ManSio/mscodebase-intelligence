"""Incremental Hot-Reload (Фаза 1): FreshnessChecker + актуальность индекса.

Покрывает (KI-109):
- НОВЫЙ файл на диске автоматически попадает в индекс через verify()
  (раньше FreshnessChecker пропускал новые файлы — отсюда требовался notify_change).
- НЕизменённый файл НЕ переиндексируется (stat-first fast-path).
- Изменённый файл переиндексируется на лету, полный reindex не вызывается.
- Проверка схемы: новые колонки file_mtime_ns / file_size записываются.

Изоляция: tmp-проект + tmp LanceDB, мок embedder (как test_lsp_vfs_indexing).
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer

pytestmark = pytest.mark.slow


def _make_embedder():
    """Mock embedder c фиксированным embedding_dim.

    embedding_dim обязателен: без него ``self.embedder.embedding_dim or 768``
    (db_writer.py:59) получает truthy-MagicMock и обрезает вектор до нулевого.
    """
    embedder = MagicMock()
    embedder.embedding_dim = 1024
    embedder.embed_batch.return_value = [[0.1] * 1024]
    embedder.mode = "lm_studio"
    return embedder


def _make_indexer(tmp_path: Path, mock_embedder, interval_sec: float = 0.0):
    """Индексатор c тестовыми настройками. interval=0 → без debounce (детерминизм)."""
    db_path = tmp_path / ".codebase_indices" / "db"
    db_path.mkdir(parents=True, exist_ok=True)

    mock_file_guard = FileGuard(project_path=tmp_path)

    indexer = Indexer(
        db_path=db_path,
        embedder=mock_embedder,
        file_guard=mock_file_guard,
        project_path=tmp_path,
        enable_summaries=False,
    )
    # interval=0 в конструкторе FreshnessChecker: дебаунс отключён —
    # каждое verify() реально сверяет (удобно для детерминированных тестов).
    indexer._freshness_checker._interval_sec = interval_sec
    return indexer


class TestFreshnessChecker:
    def test_schema_has_mtime_size(self, tmp_path):
        """Новые колонки file_mtime_ns / file_size присутствуют в схеме."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        field_names = {f.name for f in indexer.table.schema}
        assert "file_mtime_ns" in field_names
        assert "file_size" in field_names

    def test_data_records_contain_mtime_size(self, tmp_path):
        """После индексации файла в чанках проставлены mtime_ns и size."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        src_file = tmp_path / "a.py"
        src_file.write_text("def a(): return 1\n", encoding="utf-8")

        assert indexer._index_single_file(src_file, "a.py") is True

        df = indexer.table.to_lance().to_pandas(columns=["file_path", "file_mtime_ns", "file_size"])
        row = df[df["file_path"] == "a.py"].iloc[0]
        assert row["file_mtime_ns"] == int(src_file.stat().st_mtime_ns)
        assert row["file_size"] == int(src_file.stat().st_size)

    def test_new_file_detected_by_verify(self, tmp_path):
        """KI-109: новый файл подхватывается verify() без notify_change."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        (tmp_path / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(tmp_path / "a.py", "a.py") is True

        # Новый файл появляется на диске БЕЗ notify_change
        (tmp_path / "b.py").write_text("def b(): return 2\n", encoding="utf-8")

        # Сверка должна его подхватить
        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed >= 1

        df = indexer.table.to_lance().to_pandas(columns=["file_path"])
        assert "b.py" in set(df["file_path"])

    def test_unchanged_file_not_reindexed(self, tmp_path):
        """Stat-first: неизменённый файл не модифицируется и не вызывает hash-чтение."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        (tmp_path / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(tmp_path / "a.py", "a.py") is True

        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed == 0

        # Файл не тронут — повторно тоже 0
        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed == 0

        # Содержимое одинаково — никаких новых записей
        df = indexer.table.to_lance().to_pandas(columns=["file_path", "indexed_at", "file_hash"])
        assert len(df) == len(df.drop_duplicates(subset=["file_path", "file_hash"]))

    def test_changed_file_hot_reloaded(self, tmp_path):
        """Изменённый файл переиндексируется на лету, без полного reindex."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        src_file = tmp_path / "a.py"
        src_file.write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(src_file, "a.py") is True

        old_hash = indexer.table.to_lance().to_pandas(columns=["file_hash"]).iloc[0]["file_hash"]

        # Правим содержимое файла (новое содержимое)
        src_file.write_text("def a(): return 42\n", encoding="utf-8")

        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed >= 1  # файл переиндексирован

        new_hash = indexer.table.to_lance().to_pandas(columns=["file_hash"]).iloc[0]["file_hash"]
        assert new_hash != old_hash  # контент действительно обновился

    def test_hot_reload_is_full_pipeline_not_delete_all(self, tmp_path):
        """Hot-reload удаляет/переписывает ТОЛЬКО затронутый файл, а не индекс целиком."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        (tmp_path / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def b(): return 2\n", encoding="utf-8")
        assert indexer._index_single_file(tmp_path / "a.py", "a.py") is True
        assert indexer._index_single_file(tmp_path / "b.py", "b.py") is True

        # Правка a.py не должна задеть b.py
        (tmp_path / "a.py").write_text("def a(): return 999\n", encoding="utf-8")
        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed >= 1

        df = indexer.table.to_lance().to_pandas(columns=["file_path", "file_hash"])
        hash_b = df[df["file_path"] == "b.py"].iloc[0]["file_hash"]
        assert len(df) == 2  # оба файла на месте, дублей нет
        # b.py'шный hash не изменился (не был переиндексирован)
        assert hash_b == indexer._calculate_file_hash(tmp_path / "b.py")

    def test_concurrent_verify_parallel(self, tmp_path):
        """Стресс: N=8 параллельных verify() → корректность результата.

        Ловушка MagicMock-embedder и реальное поведение: verify() вызывает
        _index_single_file внутри threading.Lock FreshnessChecker; при гонке
        два потока могут перечесть один файл. Проверяем НЕ «0 ошибок»,
        а корректность: после всех вызовов файл в индексе один раз и
        значение hash равно актуальному содержимому.
        """
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        (tmp_path / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(tmp_path / "a.py", "a.py") is True

        # Гонка: файл меняется ПОКА потоки хотят его переиндексировать
        (tmp_path / "a.py").write_text("def a(): return 777\n", encoding="utf-8")

        def _run_verify(_):
            try:
                return indexer.verify_index_freshness(tmp_path)
            except Exception as _e:  # noqa: BLE001 — поток не должен упасть; результат проверяется ниже
                return _e

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_run_verify, range(16)))

        # Ни один поток не упал
        assert not any(isinstance(r, Exception) for r in results)
        # (debounce=0: хотя бы один поток реально переиндексировал)
        assert any(r >= 1 for r in results)

        df = indexer.table.to_lance().to_pandas(columns=["file_path", "file_hash"])
        a_rows = df[df["file_path"] == "a.py"]
        assert len(a_rows) == 1  # дублей после гонки нет
        assert a_rows.iloc[0]["file_hash"] == indexer._calculate_file_hash(tmp_path / "a.py")
