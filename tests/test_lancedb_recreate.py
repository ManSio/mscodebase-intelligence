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
from pathlib import Path

import pytest
import lancedb

from src.core.indexing.db_manager import LanceDBManager


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
    - Удаляет директорию таблицы с диска
    - Пересоздаёт чистую таблицу (0 строк)
    """
    mgr = _make_manager(tmp_db_root)
    _seed_chunks(mgr, 3)
    assert mgr.table.count_rows() == 3
    table_dir = mgr.db_path / f"{mgr.table_name}.lance"
    assert table_dir.exists()

    ok = mgr.recreate_table_physical()

    assert ok is True
    assert mgr.table is not None
    assert mgr.table.count_rows() == 0, "Таблица должна быть пустой после физического пересоздания"

    # Директория таблицы существует (пересоздана с нуля)
    assert table_dir.exists()
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
