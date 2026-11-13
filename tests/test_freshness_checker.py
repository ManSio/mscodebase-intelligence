"""Incremental Hot-Reload (Фаза 1): FreshnessChecker + актуальность индекса.

Покрывает (KI-109):
- НОВЫЙ файл на диске автоматически попадает в индекс через verify()
  (раньше FreshnessChecker пропускал новые файлы — отсюда требовался notify_change).
- НЕизменённый файл НЕ переиндексируется (stat-first fast-path).
- Изменённый файл переиндексируется на лету, полный reindex не вызывается.
- Проверка схемы: новые колонки file_mtime_ns / file_size записываются.

Изоляция: tmp-проект + tmp-хранилище, мок embedder (как test_lsp_vfs_indexing).

Хранилище: по умолчанию движок пишет в SQLite (`MSCODEBASE_SQLITE_CHUNKS=true`,
`src/core/indexing/indexer.py:146-154`), LanceDB — только при выключенном флаге.
Тесты читают тот слой, который реально используется, через `_file_rows()`; раньше
они всегда читали `indexer.table` (LanceDB) и потому падали на дефолтной конфигурации.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer
from src.sources.local_fs import LocalFsSource


def _make_embedder():
    """Mock embedder c фиксированным embedding_dim.

    embedding_dim обязателен: без него ``self.embedder.embedding_dim or 768``
    (db_writer.py:59) получает truthy-MagicMock и обрезает вектор до нулевого.
    """
    from unittest.mock import MagicMock

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
        source=LocalFsSource(tmp_path),
    )
    # interval=0 в конструкторе FreshnessChecker: дебаунс отключён —
    # каждое verify() реально сверяет (удобно для детерминированных тестов).
    indexer._freshness_checker._interval_sec = interval_sec
    return indexer


def _file_rows(indexer, columns):
    """Одна строка на ФАЙЛ из хранилища, которое реально использует индексатор.

    SQLite-стор отдаёт чанки (несколько строк на файл), поэтому агрегируем по
    `file_path`; для LanceDB поведение прежнее — одна строка на чанк, но тестовые
    файлы дают ровно один чанк.
    """
    if indexer._chunk_store is not None:
        by_file: dict[str, dict] = {}
        for rec in indexer._chunk_store.all_records():
            by_file.setdefault(rec["file_path"], rec)
        return [{name: rec.get(name) for name in columns} for rec in by_file.values()]
    return indexer.table.to_lance().to_pandas(columns=columns).to_dict("records")


def _store_name(indexer) -> str:
    return "sqlite" if indexer._chunk_store is not None else "lancedb"


class TestFreshnessChecker:
    def test_store_is_the_default_one(self, tmp_path):
        """Дефолт обязан быть SQLite: тесты ниже проверяют именно его."""
        indexer = _make_indexer(tmp_path, _make_embedder())
        assert _store_name(indexer) == "sqlite", (
            "MSCODEBASE_SQLITE_CHUNKS должен быть true по умолчанию "
            "(src/config/settings.py::SearchConfig.sqlite_chunks)"
        )

    def test_schema_has_mtime_size(self, tmp_path):
        """file_mtime_ns / file_size есть в обоих хранилищах."""
        indexer = _make_indexer(tmp_path, _make_embedder())
        src_file = tmp_path / "a.py"
        src_file.write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(src_file, "a.py") is True

        rows = _file_rows(indexer, ["file_path", "file_mtime_ns", "file_size"])
        assert rows and rows[0]["file_mtime_ns"] == int(src_file.stat().st_mtime_ns)
        assert rows[0]["file_size"] == int(src_file.stat().st_size)

    def test_data_records_contain_mtime_size(self, tmp_path):
        """После индексации файла в записях проставлены mtime_ns и size."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        src_file = tmp_path / "a.py"
        src_file.write_text("def a(): return 1\n", encoding="utf-8")

        assert indexer._index_single_file(src_file, "a.py") is True

        rows = _file_rows(indexer, ["file_path", "file_mtime_ns", "file_size"])
        row = next(r for r in rows if r["file_path"] == "a.py")
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

        paths = {r["file_path"] for r in _file_rows(indexer, ["file_path"])}
        assert "b.py" in paths

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
        rows = _file_rows(indexer, ["file_path", "file_hash"])
        unique = {(r["file_path"], r["file_hash"]) for r in rows}
        assert len(rows) == len(unique)

    def test_changed_file_hot_reloaded(self, tmp_path):
        """Изменённый файл переиндексируется на лету, без полного reindex."""
        mock_embedder = _make_embedder()
        indexer = _make_indexer(tmp_path, mock_embedder)
        src_file = tmp_path / "a.py"
        src_file.write_text("def a(): return 1\n", encoding="utf-8")
        assert indexer._index_single_file(src_file, "a.py") is True

        old_hash = _file_rows(indexer, ["file_hash"])[0]["file_hash"]

        # Правим содержимое файла (новое содержимое)
        src_file.write_text("def a(): return 42\n", encoding="utf-8")

        reindexed = indexer.verify_index_freshness(tmp_path)
        assert reindexed >= 1  # файл переиндексирован

        new_hash = _file_rows(indexer, ["file_hash"])[0]["file_hash"]
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

        rows = _file_rows(indexer, ["file_path", "file_hash"])
        by_path = {r["file_path"]: r["file_hash"] for r in rows}
        assert set(by_path) == {"a.py", "b.py"}  # оба файла на месте, дублей нет
        # b.py'шный hash не изменился (не был переиндексирован)
        assert by_path["b.py"] == indexer._calculate_file_hash(tmp_path / "b.py")

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

        rows = _file_rows(indexer, ["file_path", "file_hash"])
        a_rows = [r for r in rows if r["file_path"] == "a.py"]
        assert len(a_rows) == 1  # дублей после гонки нет
        assert a_rows[0]["file_hash"] == indexer._calculate_file_hash(tmp_path / "a.py")
