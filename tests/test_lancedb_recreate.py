"""
test_lancedb_recreate.py — регрессия INC-6C62 (LanceDB «вечная ошибка»).

Корень: drop_table + create_table в LanceDB НЕ удаляет физические файлы.
Новая таблица наследует цепочку версий старой, включая ссылки на мёртвые
фрагменты (*.lance, которых нет на диске) → финальная фаза optimize падает
с 'Not found' (симптом «вечной» ошибки полного реиндекса).

Фикс: LanceDBManager.recreate_table_physical() — close (mmap) → gc → пауза
→ rmtree директории таблицы (ignore_errors=False) → reconnect с нуля.

Запуск: pytest tests/test_lancedb_recreate.py -v
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import lancedb
import pytest

from src.core.indexing.db_manager import LanceDBManager
from src.core.indexing.db_writer import LanceDBWriter

# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_root():
    """Временная папка для LanceDB (стерильно, вне рабочего проекта)."""
    d = Path(tempfile.mkdtemp(prefix="mscb_recreate_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_manager(tmp_db_root: Path) -> LanceDBManager:
    """Создаёт LanceDBManager на temp dir без реального embedder."""
    db_path = tmp_db_root / "index.lancedb"
    project_path = tmp_db_root / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    mgr = LanceDBManager(
        db_path=db_path,
        embedder=None,
        project_path=project_path,
        embedding_dim=768,
    )
    return mgr


def _seed_chunks(mgr: LanceDBManager, n: int = 3) -> list[dict]:
    """Записывает n тестовых чанков (полная схема из db_manager)."""
    records = []
    for i in range(n):
        vec = [0.0] * 768
        vec[i % 768] = 1.0
        records.append({
            "id": f"chunk_{i}",
            "vector": vec,
            "text": f"def function_{i}():  # INC6C62_MARKER_{i}\n    return {i}",
            "text_full": f"def function_{i}():  # INC6C62_MARKER_{i}\n    return {i}",
            "file_path": f"src/module_{i}.py",
            "file_hash": f"hash_{i}",
            "chunk_index": 0,
            "source": "test",
            "indexed_at": "2026-08-02T00:00:00",
            "summary": "",
            "layer": "core",
            "module_name": f"module_{i}",
            "hierarchy_level": "function",
            "is_public": True,
            "symbol_type": "function",
            "parent_id": "",
            "callees": "",
            "health_score": 0.0,
            "health_band": "",
            "chunk_hash": f"chash_{i}",
            "start_line": 1,
            "end_line": 2,
        })
    mgr.table.add(records)
    return records


# ─── Regression: drop+create не должен наследовать мёртвые фрагменты ─────────

def test_drop_create_does_not_inherit_fragments(tmp_path):
    """Регрессия INC-6C62: пересоздание таблицы не наследует старые фрагменты.

    В ЧИСТОМ окружении (нет живого mmap-лока) drop_table должен удалить
    физические файлы, а create_table — создать новую директорию с одним
    фрагментом. Если LanceDB оставит старые фрагменты/версии — тест падает,
    и это сигнал, что в этом окружении нужен recreate_table_physical().
    """
    db_path = tmp_path / "test_db"
    db = lancedb.connect(str(db_path))

    # Создаём таблицу с данными (2 записи → минимум 1 фрагмент)
    table1 = db.create_table("test", data=[{"text": "a", "vector": [0.1, 0.2]}])
    table1.add([{"text": "b", "vector": [0.2, 0.3]}])

    # Drop и пересоздаём
    db.drop_table("test")
    table2 = db.create_table("test", data=[{"text": "c", "vector": [0.3, 0.4]}])

    # Верификация: новая таблица НЕ ссылается на старые фрагменты
    data_dir = db_path / "test.lance" / "data"
    fragments = list(data_dir.glob("*.lance"))

    assert len(fragments) == 1, (
        f"Expected 1 fragment after fresh create, got {len(fragments)}: "
        f"{[f.name for f in fragments]} — drop+create наследовал старые фрагменты (INC-6C62)"
    )
    assert table2.count_rows() == 1
    results = table2.search([0.3, 0.4]).limit(1).to_pandas()
    assert len(results) == 1


# ─── LanceDBManager.recreate_table_physical ─────────────────────────────────

def test_recreate_table_physical_fresh_table(tmp_db_root):
    """recreate_table_physical: физическое пересоздание без наследования версий.

    - Закрывает handle'ы (db/table → None после close_for_maintenance)
    - Удаляет ВСЮ директорию БД с диска (INC-6C62-v2: db-level __manifest
      несёт wrapped-версии со ссылкой на мёртвый фрагмент и переживает
      удаление только таблицы)
    - Пересоздаёт чистую таблицу (0 строк)
    - PID-lock перезахвачен на новой директории
    """
    mgr = _make_manager(tmp_db_root)
    _seed_chunks(mgr, 3)
    assert mgr.table.count_rows() == 3
    table_dir = mgr.db_path / f"{mgr.table_name}.lance"
    assert table_dir.exists()

    # Маркер на db-уровне (аналог битого __manifest): должен исчезнуть при
    # удалении ВСЕЙ директории БД, но пережил бы удаление только таблицы.
    poison_marker = mgr.db_path / "poison_marker.txt"
    poison_marker.write_text("dead fragment ref", encoding="utf-8")

    ok = mgr.recreate_table_physical()

    assert ok is True
    assert mgr.table is not None
    assert mgr.table.count_rows() == 0, "Таблица должна быть пустой после физического пересоздания"

    # Директория таблицы существует (пересоздана с нуля)
    assert table_dir.exists()
    # INC-6C62-v2: db-level мусор удалён вместе со всей директорией БД
    assert not poison_marker.exists(), (
        "poison_marker должен исчезнуть: удалялась ВСЯ директория БД, "
        "а не только таблица (иначе db-level manifest наследует мёртвый фрагмент)"
    )
    # PID-lock перезахвачен после пересоздания директории
    assert mgr._db_lock.is_held(), "PID-lock должен быть перезахвачен после recreate"
    # Старых фрагментов быть не должно (директория удалялась целиком)
    data_dir = table_dir / "data"
    fragments = list(data_dir.glob("*.lance")) if data_dir.exists() else []
    assert len(fragments) <= 1, (
        f"Expected no inherited fragments, got {len(fragments)}: {[f.name for f in fragments]}"
    )

    # Новая таблица пишется и читается нормально
    _seed_chunks(mgr, 2)
    assert mgr.table.count_rows() == 2


def test_close_for_maintenance_releases_handles(tmp_db_root):
    """close_for_maintenance: db/table обнуляются (освобождение mmap)."""
    mgr = _make_manager(tmp_db_root)
    _seed_chunks(mgr, 1)
    assert mgr.db is not None and mgr.table is not None

    mgr.close_for_maintenance()

    assert mgr.db is None
    assert mgr.table is None
    assert mgr._async_db is None
    assert mgr._async_table is None


# ─── Stale ghost table: switch_db/fresh-path обязан синхронизировать ссылки ──

def test_switch_db_fires_recreate_callback(tmp_db_root):
    """switch_db вызывает _on_recreate → компоненты не держат stale-ссылку.

    Регрессия stale ghost table (AGENT_DIARY 2026-08-02 00:26): fresh-path
    fallback (intel_reset_index / recreate_table_physical при залоченных
    файлах) переключал БД через switch_db БЕЗ вызова callback — writer/runner/
    freshness продолжали писать/читать УДАЛЁННУЮ таблицу по старому пути
    ('known_hashes bulk load failed', integrity check на мёртвый путь).
    """
    mgr = _make_manager(tmp_db_root)
    _seed_chunks(mgr, 2)
    old_table = mgr.table

    # Регистрируем callback, как Indexer._sync_table_ref
    captured = {}
    def on_recreate(new_table):
        captured["table"] = new_table
        captured["called"] = True
    mgr.set_on_recreate_callback(on_recreate)

    # Переключение на новый путь (аналог fresh-path fallback)
    new_path = tmp_db_root / "fresh.lancedb"
    mgr.switch_db(new_path)

    # Callback вызван с НОВОЙ таблицей (не stale-ссылкой на старый путь)
    assert captured.get("called") is True, "switch_db должен вызывать _on_recreate"
    assert captured.get("table") is not None
    assert captured.get("table") is mgr.table
    assert captured.get("table") is not old_table
    assert mgr.table.count_rows() == 0, "Новая таблица на fresh-пути должна быть пустой"


def test_reset_connection_fires_recreate_callback(tmp_db_root):
    """reset_connection вызывает _on_recreate (синхронизация после recreate)."""
    mgr = _make_manager(tmp_db_root)
    _seed_chunks(mgr, 1)

    captured = {}
    def on_recreate(new_table):
        captured["table"] = new_table
        captured["called"] = True
    mgr.set_on_recreate_callback(on_recreate)

    mgr.reset_connection()

    assert captured.get("called") is True
    assert captured.get("table") is mgr.table
    assert mgr.table.count_rows() == 1, "Данные должны пережить reset_connection"


# ─── INC-6C62-v2: рендер не должен показывать error-dict как результат ───────


def test_is_real_result_filters_error_dict():
    """_is_real_result: error-dict от vector_search — НЕ результат (пустой рендер)."""
    from src.mcp.tools.search_tools import SearchCodeTool

    # Searcher.vector_search при сбое возвращал [{"error": ...}] — мусор
    assert SearchCodeTool._is_real_result({"error": "lance error: Not found ..."}) is False
    # Пустой dict — тоже мусор
    assert SearchCodeTool._is_real_result({}) is False
    # Настоящий чанк — результат
    real = {
        "text": "def f(): pass",
        "metadata": {"file": "src/a.py", "chunk_index": 0, "layer": "core"},
    }
    assert SearchCodeTool._is_real_result(real) is True


def test_write_records_rollback_on_failed_add(tmp_db_root, monkeypatch):
    """Регрессия deep-research-report.md P1: сбой add после delete НЕ теряет чанки.

    Было: delete затем add; add падает (≠ table-not-found) → файл остаётся
    без чанков («база сломана»). Фикс: перед delete фиксируем table.version;
    при сбое add — restore(prev_version), старые данные возвращаются.
    """
    mgr = _make_manager(tmp_db_root)
    mgr.table.add([{
        "id": "old_0",
        "vector": [0.5] * 768,
        "text": "OLD_MARKER",
        "text_full": "OLD_MARKER",
        "file_path": "test.py",
        "file_hash": "h1",
        "chunk_index": 0,
        "source": "test",
        "indexed_at": "2026-08-08T00:00:00",
        "summary": "",
        "layer": "core",
        "module_name": "test",
        "hierarchy_level": "function",
        "is_public": True,
        "symbol_type": "function",
        "parent_id": "",
        "callees": "",
        "health_score": 0.0,
        "health_band": "",
        "chunk_hash": "c1",
        "start_line": 1,
        "end_line": 2,
    }])
    assert mgr.table.count_rows() == 1

    writer = LanceDBWriter(
        table=mgr.table,
        table_write_lock=threading.RLock(),
        index_lock=threading.RLock(),
        embedder=SimpleNamespace(embedding_dim=768),
        db_manager=mgr,
    )

    parsed = {
        "rel_path": "test.py",
        "current_hash": "h2",
        "escaped_path": "test.py",
        "existing_hash": "h1",
        "chunk_texts": ["new chunk"],
        "chunk_hashes": ["c2"],
        "chunk_texts_full": ["new chunk"],
        "chunk_metadatas": [{}],
        "health": {},
        "source": "test",
    }
    embeddings = [[0.1] * 768]

    def _boom(records):
        raise ValueError("dimension mismatch")

    monkeypatch.setattr(mgr.table, "add", _boom)

    with pytest.raises(ValueError):
        writer.write_records(parsed=parsed, embeddings=embeddings)

    # Старые чанки на месте: сбой add откатил delete (rollback по версии)
    assert mgr.table.count_rows() == 1, "Сбой add не должен оставлять таблицу без чанков файла"
    df = mgr.table.search([0.5] * 768).limit(5).to_pandas()
    assert (df["text"] == "OLD_MARKER").any(), "Старый чанк должен пережить rollback"


def test_rollback_serialized_with_reset_connection(tmp_db_root):
    """Регрессия F3: rollback (restore) и reset_connection сериализованы одним lock.

    Риск: restore(prev_version) при конкурентном внешнем reset_connection мог бы
    откатить чужую версию (например, пересозданную таблицу). В проде Indexer
    передаёт ОДИН _table_write_lock и в LanceDBManager, и в LanceDBWriter, а
    reset_connection/switch_db/recreate_table_physical захватывают его. Тест
    фиксирует: (1) identity lock'ов; (2) reset_connection блокируется, пока
    writer держит lock (т.е. не может пересечь delete→add→restore-окно).
    """
    shared_lock = threading.RLock()
    project_path = tmp_db_root / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    mgr = LanceDBManager(
        db_path=tmp_db_root / "index.lancedb",
        embedder=None,
        project_path=project_path,
        embedding_dim=768,
        table_write_lock=shared_lock,
    )
    mgr.table.add([{
        "id": "old_0",
        "vector": [0.5] * 768,
        "text": "OLD_MARKER",
        "text_full": "OLD_MARKER",
        "file_path": "test.py",
        "file_hash": "h1",
        "chunk_index": 0,
        "source": "test",
        "indexed_at": "2026-08-08T00:00:00",
        "summary": "",
        "layer": "core",
        "module_name": "test",
        "hierarchy_level": "function",
        "is_public": True,
        "symbol_type": "function",
        "parent_id": "",
        "callees": "",
        "health_score": 0.0,
        "health_band": "",
        "chunk_hash": "c1",
        "start_line": 1,
        "end_line": 2,
    }])
    writer = LanceDBWriter(
        table=mgr.table,
        table_write_lock=shared_lock,
        index_lock=threading.RLock(),
        embedder=SimpleNamespace(embedding_dim=768),
        db_manager=mgr,
    )

    # (1) writer и manager обязаны разделять ОДИН lock-объект (как в Indexer)
    assert writer._table_write_lock is mgr._write_lock, (
        "writer и manager должны использовать один lock (иначе reset_connection "
        "может пересечься с rollback-restore)"
    )

    # (2) пока writer держит lock (окно delete→add→restore) — reset_connection ждёт
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with writer._table_write_lock:
            entered.set()
            release.wait(5)

    t1 = threading.Thread(target=holder)
    t1.start()
    assert entered.wait(5), "holder не захватил lock"

    reset_result = {}

    def do_reset():
        try:
            mgr.reset_connection()
            reset_result["done"] = True
        except Exception as e:  # noqa: BLE001 — поток-обёртка: любой сбой reset_connection фиксируется в reset_result для assert
            reset_result["err"] = repr(e)

    t2 = threading.Thread(target=do_reset)
    t2.start()
    time.sleep(0.3)
    assert "done" not in reset_result, (
        "reset_connection не должен выполняться, пока writer держит lock "
        "(иначе restore откатит чужую версию)"
    )

    release.set()
    t1.join(5)
    t2.join(5)
    assert reset_result.get("done") is True, f"reset_connection должен пройти после освобождения lock: {reset_result}"


def test_format_results_no_garbage_render():
    """_format_results: error-dict не рендерится как «📄 — (line , —)»."""
    from src.mcp.tools.search_tools import SearchCodeTool

    raw = {
        "results": [{"error": "lance error: Not found"}],
        "timing_ms": {"total_ms": 12},
        "query": "def search_with_mode",
    }
    out = SearchCodeTool._format_results(raw, "fast")
    # Ни одного битого заголовка результата
    assert "📄" not in out, f"Error-dict не должен рендериться как результат:\n{out}"
    assert "**0** results" in out, f"Ожидался счётчик 0 результатов:\n{out}"
