"""
test_index_runner_deadlock.py — регрессионный тест на deadlock в Phase 1 (Parallel Parse).

ВОСПРОИЗВЕДЕНИЕ (регрессия ac6e5ba0e P1-3, 2026-07-31):
IndexProjectRunner.run() захватывает begin_write() (= тот же RLock, что
Indexer._table_write_lock) и держит его на весь run(). До фикса воркеры
Phase 1 вызывали _parse_file_only() БЕЗ known_hashes → шли в ветку else
(self.table.search под _table_write_lock) → тот же RLock из другого потока
(RLock реентерабелен только в одном потоке) → вечный deadlock:
- индексация зависала на первом же файле (progress: 0, current_file: "")
- все MCP-инструменты, читающие БД (get_status/count_rows), таймаутили.

ФИКС: known_hashes загружается ОДИН раз в главном потоке (RLock reentrant)
и передаётся воркерам → воркеры не ходят в БД под lock вовсе.

ПРОВЕРКА КОРРЕКТНОСТИ (не только "не упало"):
1. run() завершается за ограниченное время (deadlock = вечный hang).
2. Каждый вызов _parse_file_only получил known_hashes (dict, не None) —
   т.е. воркеры НЕ идут в ветку self.table.search.
3. Результаты парсинга попали в индексацию (вход → выход).

Запуск: pytest tests/test_index_runner_deadlock.py -v
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.core.indexing.index_project_runner import IndexProjectRunner

# ─── Моки ───────────────────────────────────────────────────────────────────

class _FakeTable:
    """Минимальная имитация LanceDB-таблицы: to_lance().to_pandas(columns=...).

    НЕ реализует search() — воркеры с known_hashes не должны его вызывать.
    Если кто-то вызовет search — упадёт AttributeError, что и докажет баг.
    """

    def __init__(self, known: dict):
        self._known = known

    def to_lance(self):
        return self

    def to_pandas(self, columns=None):
        import pandas as pd
        if not self._known:
            return pd.DataFrame(columns=(columns or []))
        fp = list(self._known.keys())
        fh = list(self._known.values())
        return pd.DataFrame({"file_path": fp, "file_hash": fh})

    def count_rows(self) -> int:
        return len(self._known)

    # Намеренно НЕТ search() — см. docstring.


class _FakeFileGuard:
    def should_skip_dir(self, d) -> bool:
        return False

    def should_skip_file(self, f) -> bool:
        return False


class _FakePathManager:
    def is_safe_to_process(self, p) -> bool:
        return True


class _FakeEmbedder:
    def __init__(self, dim: int = 4):
        self.dim = dim
        self.calls = 0

    def is_ready(self) -> bool:
        return True

    def embed_batch(self, texts):
        self.calls += 1
        return [[0.1] * self.dim for _ in texts]


class _FakeSearcher:
    def reindex(self):
        pass


class _FakeDbWriter:
    def __init__(self):
        self.written = 0

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
        self.written = total
        return total


class _FakeDbManager:
    """begin_write() возвращает RLock — как в реальном LanceDBManager."""

    def __init__(self):
        self._write_lock = threading.RLock()

    def begin_write(self):
        return self._write_lock


def _make_parsed(rel: str, n_chunks: int = 2) -> dict:
    """Минимальный parsed-словарь, который ожидает run()/db_writer."""
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


def _make_runner(tmp_path: Path, known_hashes: dict):
    """Собирает IndexProjectRunner с моками и файлами проекта."""
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    rel_paths = []
    for i in range(4):
        rel = f"src/mod_{i}.py"
        (project / rel).write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
        rel_paths.append(rel)

    parsed_calls = []
    parse_lock_calls = []

    def fake_parse_file_only(full_path, rel_path_str, source="filesystem", known_hashes=None):
        parsed_calls.append((str(rel_path_str), known_hashes))
        # Симуляция ветки else (до фикса): воркер пытался взять тот же RLock.
        # После фикса known_hashes != None → воркер НЕ заходит сюда.
        if known_hashes is None:
            parse_lock_calls.append(rel_path_str)
        return _make_parsed(rel_path_str)

    def fake_prune(active):
        return 0

    def fake_get_status():
        return {"total_chunks": 10}

    dbm = _FakeDbManager()
    runner = IndexProjectRunner(
        parse_file_only=fake_parse_file_only,
        write_file_records=lambda parsed, vecs: True,
        embedder=_FakeEmbedder(),
        file_guard=_FakeFileGuard(),
        searcher=_FakeSearcher(),
        table=_FakeTable(known_hashes),
        path_manager=_FakePathManager(),
        project_path=project,
        notification_broker=None,
        summarizer=None,
        db_manager=dbm,
        db_writer=_FakeDbWriter(),
    )
    return runner, parsed_calls, parse_lock_calls


def test_run_completes_without_deadlock_when_known_hashes_passed(tmp_path):
    """run() завершается (нет hang) — regression-тест на deadlock Phase 1."""
    runner, parsed_calls, parse_lock_calls = _make_runner(tmp_path, known_hashes={})

    # Запускаем в отдельном потоке: если deadlock — join(timeout) упадёт.
    result_box = {}
    thread = threading.Thread(target=lambda: result_box.setdefault("count", runner.run(runner.project_path)))
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive(), (
        "IndexProjectRunner.run() завис — deadlock Phase 1 (воркер взял "
        "_table_write_lock, который главный поток держит через begin_write). "
        "known_hashes не был передан воркерам."
    )

    assert result_box.get("count", 0) > 0, "run() вернул 0 — ничего не проиндексировано"
    assert len(parsed_calls) == 4, f"ожидали 4 файла, обработано {len(parsed_calls)}"


def test_workers_receive_known_hashes_not_none(tmp_path):
    """Фикс: воркеры получают known_hashes (dict), не None.

    Это гарантирует, что ветка else (self.table.search под _table_write_lock)
    из _parse_file_only НЕ выполняется из воркеров.
    """
    runner, parsed_calls, parse_lock_calls = _make_runner(tmp_path, known_hashes={"src/mod_0.py": "h0"})
    runner.run(runner.project_path)

    assert parsed_calls, "парсинг не вызывался"
    for rel, kh in parsed_calls:
        assert kh is not None, f"воркер {rel} получил known_hashes=None — пойдёт в БД под lock (deadlock)"
        assert isinstance(kh, dict)

    # Ни один воркер не попал в ветку «known_hashes is None».
    assert parse_lock_calls == [], (
        f"воркеры попали в ветку self.table.search под lock: {parse_lock_calls}"
    )


def test_run_with_existing_known_hashes_skips_unchanged(tmp_path):
    """Корректность: файл с известным хэшем, не изменившийся, пропускается.

    known_hashes передаётся воркеру → fake_parse_file_only может вернуть None
    для неизменённого файла (как реальный IndexParser), и этот файл не
    попадёт в индексацию. Вход → выход: только изменённые файлы.
    """
    project = tmp_path / "project2"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("A", encoding="utf-8")
    (project / "src" / "b.py").write_text("B", encoding="utf-8")
    # Windows: str(Path.relative_to) даёт backslash — ключи таблицы должны
    # совпадать с тем, что реально передаётся воркерам.
    rel_a = str((project / "src" / "a.py").relative_to(project))
    rel_b = str((project / "src" / "b.py").relative_to(project))

    seen = {}

    def fake_parse(full_path, rel_path_str, source="filesystem", known_hashes=None):
        # Симуляция реального поведения: файл a.py неизменён (known_hashes
        # совпадает с текущим) → вернуть None; b.py изменён → вернуть parsed.
        seen[rel_path_str] = known_hashes
        if rel_path_str == rel_a and known_hashes and known_hashes.get(rel_path_str) == "hash_a":
            return None
        return _make_parsed(rel_path_str)

    dbm = _FakeDbManager()
    runner = IndexProjectRunner(
        parse_file_only=fake_parse,
        write_file_records=lambda parsed, vecs: True,
        embedder=_FakeEmbedder(),
        file_guard=_FakeFileGuard(),
        searcher=_FakeSearcher(),
        table=_FakeTable({rel_a: "hash_a"}),
        path_manager=_FakePathManager(),
        project_path=project,
        db_manager=dbm,
        db_writer=_FakeDbWriter(),
    )

    count = runner.run(project)
    # a.py пропущен (None), b.py проиндексирован → 1 файл.
    assert count == 1, f"ожидали 1 изменённый файл, получено {count}"
    assert seen.get(rel_a) == {rel_a: "hash_a"}, "a.py получил неверные known_hashes"
    assert seen.get(rel_b) is not None, "b.py не получил known_hashes"


def test_run_survives_single_cpu_host(tmp_path):
    """A1 (внешний аудит): на 1-CPU хосте пул воркеров не должен быть 0.

    Регрессия: `_max_workers = min(4, (os.cpu_count() or 4) // 2)` → на 1-CPU
    `1 // 2 = 0` → `ThreadPoolExecutor(max_workers=0)` кидает ValueError и
    full reindex (intel_trigger_reindex mode=full) падает ДО парсинга.
    Фикс: `max(1, ...)` — минимум 1 воркер.

    До фикса этот тест падает на 1-CPU хосте (mock os.cpu_count → 1);
    после фикса run() создаёт пул с 1 воркером и индексирует все 4 файла.
    """
    from unittest import mock

    runner, parsed_calls, _ = _make_runner(tmp_path, known_hashes={})
    with mock.patch("src.core.indexing.index_project_runner.os.cpu_count", return_value=1):
        count = runner.run(runner.project_path)
    assert count > 0, "run() на 1-CPU хосте не проиндексировал ни одного файла"
    assert len(parsed_calls) == 4, f"ожидали 4 файла, обработано {len(parsed_calls)}"
