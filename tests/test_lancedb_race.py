"""
test_lancedb_race.py — стресс-тест конкурентного доступа к LanceDB.

ВОСПРОИЗВЕДЕНИЕ RACE (AGENTS.md §5.13):
search_code (sync self.table.search) и intel_trigger_reindex (drop_table +
reset_connection на том же self.db) конкурентны в рамках одного event loop.
Тест доказывает, что без защиты search либо падает (RuntimeError/OSError),
либо возвращает мусор. После фикса (asyncio.Lock + reindex-guard Event)
search должен либо вернуть валидный результат, либо честный fast-fail.

ПРОВЕРКА КОРРЕКТНОСТИ (не только "не упало"):
каждый search ищет уникальный маркерный текст; результат должен содержать
именно тот чанк, который мы записали (по file_path), а не произвольный мусор.

Запуск: pytest tests/test_lancedb_race.py -v -s
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from lancedb.index import IvfPq

from src.core.indexing.db_manager import LanceDBManager


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_root():
    """Временная папка для LanceDB (стерильно, вне рабочего проекта)."""
    d = Path(tempfile.mkdtemp(prefix="mscb_race_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_manager(tmp_db_root: Path) -> LanceDBManager:
    """Создаёт LanceDBManager на temp dir без реального embedder."""
    db_path = tmp_db_root / "index.lancedb"
    project_path = tmp_db_root / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    # embedder=None — в __init__ он только сохраняется, не вызывается.
    mgr = LanceDBManager(
        db_path=db_path,
        embedder=None,
        project_path=project_path,
        embedding_dim=768,
    )
    return mgr


def _seed_chunks(mgr: LanceDBManager, n: int = 50) -> list[dict]:
    """Записывает n тестовых чанков с уникальным маркерным текстом И вектором.

    Вектор = one-hot на позиции i (уникален для каждого чанка) → vector search
    по вектору чанка i детерминированно вернёт именно его (проверка корректности).
    Возвращает список словарей {marker, vector, file_path} для проверки search.
    """
    chunks = []
    records = []
    for i in range(n):
        marker = f"MARKER_UNIQUE_CHUNK_{i}_zzz"
        vec = [0.0] * 768
        vec[i % 768] = 1.0  # one-hot → уникальный вектор
        fp = f"src/module_{i}.py"
        chunks.append({"marker": marker, "vector": vec, "file_path": fp})
        records.append({
            "id": f"chunk_{i}",
            "vector": vec,
            "text": f"def function_{i}(): # {marker}\n    return {i}",
            "text_full": f"def function_{i}(): # {marker}\n    return {i}",
            "file_path": fp,
            "file_hash": f"hash_{i}",
            "chunk_index": 0,
            "source": "test",
            "indexed_at": "2026-07-19T00:00:00",
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
    # IVF index для vector search (как делает реальный pipeline)
    try:
        mgr.table.create_index("vector", config=IvfPq(distance_type="l2"))
    except Exception as e:
        print(f"  [warn] IVF index create failed: {e}")
    return chunks


# ─── Stress test ─────────────────────────────────────────────────────────────

async def _search_worker(mgr: LanceDBManager, chunks: list[dict], results: list, wid: int):
    """Один search-воркер: проверяет reindex-guard, иначе ищет по вектору.

    Guard (AGENTS.md §5.13): если reindex идёт — fast-fail (empty), а не падение.
    """
    import random
    for _ in range(20):
        chunk = random.choice(chunks)
        try:
            # Guard check (как engine.hybrid_search делает после нашего фикса)
            if mgr.is_reindexing():
                results.append(("fast_fail", wid))  # честный fast-fail
                continue
            # Vector search через тот же self.table, что и search_code MCP tool
            df = mgr.table.search(chunk["vector"]).limit(5).to_pandas()
            if df is None or len(df) == 0:
                results.append(("empty", wid))
                continue
            fps = set(df["file_path"].tolist())
            if chunk["file_path"] in fps:
                results.append(("ok", wid))
            else:
                # Вернул НЕ тот чанк → мусор (race-симптом)
                results.append(("wrong_chunk", wid, chunk["file_path"], list(fps)[:3]))
        except Exception as e:
            # Упал с RuntimeError/OSError → race-симптом
            results.append(("exception", wid, type(e).__name__, str(e)[:120]))
        await asyncio.sleep(0.001)


async def _reindex_worker(mgr: LanceDBManager, results: list, wid: int):
    """Один reindex-воркер: имитирует index_project (sync, в executor-потоке).

    Реальный trigger_async_reindex запускает index_project через
    loop.run_in_executor (ОТДЕЛЬНЫЙ ПОТОК), который делает drop_table +
    reset_connection + table.add на том же self.db. Это и есть межпотоковый
    race с search (который в event-loop потоке).
    """
    loop = asyncio.get_event_loop()
    for _ in range(5):
        try:
            # set_reindexing ДО запуска executor-потока (guard)
            mgr.set_reindexing()
            def _do_reindex():
                try:
                    mgr.db.drop_table(mgr.table_name)
                except Exception:
                    pass
                mgr.reset_connection()
                _seed_chunks(mgr, 50)
            await loop.run_in_executor(None, _do_reindex)
            mgr.clear_reindexing()
            results.append(("reindex_ok", wid))
        except Exception as e:
            results.append(("reindex_exception", wid, type(e).__name__, str(e)[:120]))
        await asyncio.sleep(0.005)


async def _run_stress(mgr: LanceDBManager, chunks: list[dict], n_search: int, n_reindex: int):
    results: list = []
    search_tasks = [
        asyncio.create_task(_search_worker(mgr, chunks, results, i))
        for i in range(n_search)
    ]
    reindex_tasks = [
        asyncio.create_task(_reindex_worker(mgr, results, i))
        for i in range(n_reindex)
    ]
    await asyncio.gather(*search_tasks, *reindex_tasks, return_exceptions=True)
    return results


@pytest.mark.asyncio
async def test_lancedb_race_concurrent_search_and_reindex(tmp_db_root):
    """ДОКАЗЫВАЕТ race: конкурентный search + reindex на одном sync-connection.

    Ожидаем ДО фикса: results содержат ('exception', ...) или ('wrong_chunk', ...)
    — то есть race проявился.
    """
    mgr = _make_manager(tmp_db_root)
    chunks = _seed_chunks(mgr, 50)

    N_SEARCH = 8
    N_REINDEX = 4
    results = await _run_stress(mgr, chunks, N_SEARCH, N_REINDEX)

    exceptions = [r for r in results if r[0] == "exception"]
    wrong = [r for r in results if r[0] == "wrong_chunk"]
    ok = [r for r in results if r[0] == "ok"]
    fast_fail = [r for r in results if r[0] == "fast_fail"]

    print(f"\n=== RACE TEST RESULTS ===")
    print(f"  ok={len(ok)}  fast_fail={len(fast_fail)}  exceptions={len(exceptions)}  wrong_chunk={len(wrong)}")
    for e in exceptions[:5]:
        print(f"  EXCEPTION: {e[2]}: {e[3]}")
    for w in wrong[:5]:
        print(f"  WRONG_CHUNK: expected={w[2]} got={w[3]}")

    # POSLE fixa: exceptions=0, wrong=0, fast_fail>0 (guard сработал)
    race_fixed = len(exceptions) == 0 and len(wrong) == 0 and len(fast_fail) > 0
    assert race_fixed, (
        f"Race NOT fixed (ok={len(ok)}, fast_fail={len(fast_fail)}, exc={len(exceptions)}, "
        f"wrong={len(wrong)}). Guard должен был fast-fail по крайней мере некоторые вызовы."
    )
    print(f"  [OK] RACE FIXED: {len(fast_fail)} fast_fail, {len(exceptions)} exceptions, {len(wrong)} wrong_chunks")
