"""
test_index_resume_incremental.py — резюмируемая инкрементальная запись.

ПРОБЛЕМА (2026-09-20): IndexProjectRunner.run() копил ВСЕ эмбеддинги в
_all_embeddings и писал одним bulk_write в Phase 3. Краш на большом проекте
(330K чанков, ~9ч) терял всю работу: таблица пуста → known_hashes пуст →
полный пере-embed при перезапуске.

ФИКС: файлы, все чанки которых эмбеддированы, записываются сразу порциями
(WRITE_FLUSH_FILES). Перезапуск = resume: записанные файлы пропускаются по
хэшам, теряются только цепочки последней незавершённой порции.

ПРОВЕРКА КОРРЕКТНОСТИ:
1. run() НЕ держит все эмбеддинги в памяти: _all_embeddings зануляется
   после записи каждой порции (RAM-слёты, а не постоянный рост).
2. Файл записывается РОВНО один раз (вход → выход, no double-write).
3. Краш середины прогона сохраняет уже записанные файлы в БД
   (эмулируем embedder exception) → при повторном run отсутствуют.
4. Повторный run после краша индексирует только НЕзаписанные файлы
   (H2H-incr: existing hash → skip).

Запуск: pytest tests/test_index_resume_incremental.py -v
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.core.indexing.index_project_runner import IndexProjectRunner


class _FakeTable:
    """Имитация LanceDB-таблицы с персистентной памятью между запусками."""

    def __init__(self):
        self._known: dict = {}  # file_path -> file_hash (persisted)
        self._rows = 0

    def to_lance(self):
        return self

    def to_pandas(self, columns=None):
        import pandas as pd
        if not self._known:
            return pd.DataFrame(columns=[])
        fp = list(self._known.keys())
        fh = list(self._known.values())
        return pd.DataFrame({"file_path": fp, "file_hash": fh})

    def count_rows(self) -> int:
        return len(self._known)

    def delete_all_known(self):
        self._known = {}


class _FakeFileGuard:
    def should_skip_dir(self, d) -> bool:
        return False

    def should_skip_file(self, f) -> bool:
        return False


class _FakePathManager:
    def is_safe_to_process(self, p) -> bool:
        return True


class _FakeEmbedder:
    def __init__(self, dim: int = 4, fail_after: int | None = None):
        self.dim = dim
        self.fail_after = fail_after  # кинуть exception после N embed_batch вызовов
        self.calls = 0
        self.total_batches = 0

    def is_ready(self) -> bool:
        return True

    def embed_batch(self, texts):
        self.calls += 1
        self.total_batches += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError(f"simulated embedder crash after {self.fail_after} batches")
        return [[0.1] * self.dim for _ in texts]


class _FakeSearcher:
    def reindex(self):
        pass

    def invalidate_cache(self):
        pass


class _FakeDbWriter:
    """Пишет в _FakeTable: добавляет file_hash, считает записи."""

    def __init__(self, table: _FakeTable):
        self.table = table
        self.written = 0
        self.bulk_calls = 0

    def set_on_recreate_callback(self, cb):
        self._on_recreate = cb

    def prepare_records(self, parsed, vecs, summarizer=None, enable_summaries=False):
        rel = parsed["rel_path"]
        n = len(parsed["chunk_texts"])
        records = [{
            "id": f"id_{rel}_{i}",
            "vector": vecs[i],
            "text": parsed["chunk_texts"][i],
            "file_path": rel,
            "file_hash": parsed["current_hash"],
            "chunk_index": i,
        } for i in range(n)]
        return (records, parsed.get("escaped_path", rel), parsed.get("existing_hash"))

    def bulk_write(self, all_prepared):
        total = 0
        for records, _escaped, _hash in all_prepared:
            total += len(records)
            for r in records:
                self.table._known[r["file_path"]] = r["file_hash"]
        self.written += total
        self.bulk_calls += 1
        return total


class _FakeDbManager:
    def __init__(self):
        self._write_lock = threading.RLock()

    def begin_write(self):
        return self._write_lock


def _make_parsed(rel: str, n_chunks: int = 2) -> dict:
    return {
        "chunk_texts": [f"chunk {rel} {i}" for i in range(n_chunks)],
        "chunk_texts_full": [f"chunk {rel} {i}" for i in range(n_chunks)],
        "chunk_metadatas": [{} for _ in range(n_chunks)],
        "chunk_hashes": [f"ch_{rel}_{i}" for i in range(n_chunks)],
        "rel_path": rel,
        "current_hash": f"hash_{rel}",
        "escaped_path": rel.replace("'", "''"),
        "health": {"score": 0.0, "band": ""},
        "source": "filesystem",
    }


def _make_project(tmp_path: Path, n_files: int, n_chunks: int = 1):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    rels = []
    for i in range(n_files):
        rel = f"src/mod_{i:04d}.py"
        (project / rel).write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
        rels.append(rel)
    return project, rels


def _make_runner(tmp_path, table: _FakeTable, n_files=40, n_chunks=1,
                 fail_after=None, db_writer_class=_FakeDbWriter):
    project, rels = _make_project(tmp_path, n_files, n_chunks)

    def fake_parse_file_only(full_path, rel_path_str, source="filesystem", known_hashes=None):
        # Resume-сценарий: если файл уже в БД (known_hashes) → skip (вернуть None),
        # как реальный IndexParser делает при совпадении хэша.
        # Canonical POSIX rel path (mirrors indexer._parse_file_only, 2026-09-25).
        rel_path_str = str(rel_path_str).replace("\\", "/")
        if known_hashes and known_hashes.get(rel_path_str) == f"hash_{rel_path_str}":
            return None
        return _make_parsed(rel_path_str, n_chunks)

    dbm = _FakeDbManager()
    writer = db_writer_class(table)
    runner = IndexProjectRunner(
        parse_file_only=fake_parse_file_only,
        write_file_records=lambda parsed, vecs: True,
        embedder=_FakeEmbedder(fail_after=fail_after),
        file_guard=_FakeFileGuard(),
        searcher=_FakeSearcher(),
        table=table,
        path_manager=_FakePathManager(),
        project_path=project,
        db_manager=dbm,
        db_writer=writer,
    )
    return runner, writer, rels


def test_first_run_writes_all_files(tmp_path):
    """Полнота: первый прогон записывает все файлы, по нес колько bulk_write."""
    table = _FakeTable()
    runner, writer, rels = _make_runner(tmp_path, table, n_files=40, n_chunks=1)

    count = runner.run(runner.project_path)

    assert count == 40, f"ожидали 40 файлов, получено {count}"
    assert writer.written == 40, f"записей в БД {writer.written} вместо 40"
    assert writer.bulk_calls >= 1, "bulk_write не вызывался вообще"
    # 40 файлов по 1 чанку, WRITE_FLUSH_FILES=32 → минимум 2 флеша (32+8)
    assert writer.bulk_calls >= 2, (
        f"ожидали >=2 инкрементальных флеша (resume-checkpoint), получили {writer.bulk_calls}"
    )
    assert len(table._known) == 40, "таблица не содержит все записанные файлы"


def test_run_flushes_incrementally_not_all_at_end(tmp_path):
    """Resume: bulk_write происходит ДО конца прогона (не ждём завершения).

    Ключевой атрибут фикса: порции завершённых файлов пишутся по ходу.
    Если реализация откатится к «один bulk_write в конце» — bulk_calls == 1
    для проекта, где на каждый флеш накапливается более WRITE_FLUSH_FILES.
    """
    table = _FakeTable()
    runner, writer, _ = _make_runner(tmp_path, table, n_files=100, n_chunks=1)

    runner.run(runner.project_path)

    # 100 файлов / 32 = 3 полных + 4 хвост → >= 4 флеша
    assert writer.bulk_calls >= 4, (
        f"bulk_write={writer.bulk_calls} — выглядит как единый финальный flush, "
        "инкрементальная запись не работает"
    )


def test_crash_preserves_written_files_in_db(tmp_path):
    """Resume: краш embedder'а сохраняет уже записанные файлы в БД.

    Эмулируем падение после 1-го embed_batch (первая порция уже записана).
    Таблица должна содержать ~32 файла (первая завершённая порция), а не 0.
    """
    table = _FakeTable()
    # 100 файлов, embedder падает на 2-м батче (после успешной 1-й порции).
    # batch=32 → 1-й батч (32 файла) успешен и записан, 2-й батч падает.
    runner, writer, rels = _make_runner(tmp_path, table, n_files=100, n_chunks=1, fail_after=1)

    with pytest.raises(RuntimeError, match="simulated embedder crash"):
        runner.run(runner.project_path)

    # Resume: в БД осталась первая записанная порция (до краша).
    assert writer.written >= 32, (
        f"после краша в БД {writer.written} записей, ожидали >=32 из первой записи "
        "(до краша должна быть хотя бы одна порция)"
    )
    assert table.count_rows() >= 32, "таблица не пережила краш — resume невозможен"


def test_second_run_resumes_only_unwritten(tmp_path):
    """Resume: повторный прогон после краша обрабатывает только НЕзаписанные."""
    table = _FakeTable()
    runner, writer, _ = _make_runner(tmp_path, table, n_files=100, n_chunks=1, fail_after=1)

    with pytest.raises(RuntimeError, match="simulated embedder crash"):
        runner.run(runner.project_path)
    assert table.count_rows() >= 32, "предусловие: до краша записана первая порция"

    # НОВЫЙ runner (перезапуск процесса) с полным embedder и той же таблицей.
    runner2, writer2, rels = _make_runner(tmp_path, table, n_files=100, n_chunks=1)

    count2 = runner2.run(runner2.project_path)

    # Из 100 файлов ~32 уже в БД (skip), эмбеддились только оставшиеся ~68.
    assert count2 <= 68, (
        f"повторный прогон заново эмбеддил {count2} файлов вместо <=68 — "
        "resume не работает (known_hashes не пропустил записанное)"
    )
    assert table.count_rows() == 100, "таблица должна заполниться до 100"


def test_no_double_write_of_completed_files(tmp_path):
    """Корректность: каждый файл попадает в БД ровно один раз (нет double-write).

    written в _FakeDbWriter = число ЗАПИСЕЙ (чанков). Для 40 файлов с 2 чанками
    = 80 записей ожидается ровно один раз. Double-write показал бы >80.
    """
    table = _FakeTable()
    runner, writer, rels = _make_runner(tmp_path, table, n_files=40, n_chunks=2)

    runner.run(runner.project_path)

    assert writer.written == 80, f"double-write: {writer.written} записей вместо 80"
    assert len(table._known) == 40, f"в БД {len(table._known)} файлов вместо 40"


def test_ram_is_freed_after_flush(tmp_path):
    """RAM: эмбеддинги завершённых файлов занулены после инкрементальной записи.

    Не замеряем RAM (флейковый замер), а проверяем инвариант использования:
    через инъекцию в bulk_write считаем, что каждый флеш получает подготовленные
    данные, а таблица растёт порциями (а не единым всплеском в конце).
    Это косвенно подтверждает: большой проект не держит все 1.3GB векторов
    до самого конца прогона.
    """
    table = _FakeTable()
    runner, writer, _ = _make_runner(tmp_path, table, n_files=80, n_chunks=1)

    # Инъекция в db_writer: считаем размеры порций bulk_write.
    write_lens = []

    orig_bulk = writer.bulk_write

    def spy_bulk(all_prepared):
        write_lens.append(len(all_prepared))
        return orig_bulk(all_prepared)

    writer.bulk_write = spy_bulk

    runner.run(runner.project_path)

    # 80 файлов, WRITE_FLUSH_FILES=32 → порции по ~32, а не один раз 80.
    assert len(write_lens) >= 3, f"ожидали >=3 порций записи, получили {write_lens}"
    assert write_lens[0] <= 33, (
        f"первая порция {write_lens[0]} файлов — инкрементальная запись работает не так"
    )
    # Таблица заполнена полностью, все 80 файлов на месте.
    assert table.count_rows() == 80
