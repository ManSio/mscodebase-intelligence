"""
Sandbox: воспроизведение гонки LanceDB `Not found` при optimize/compact + параллельное чтение.

Гипотеза (из AGENT_DIARY + комментария в index_project_runner.py):
  reindex вызывает table.optimize() / compact_files(), которые ФИЗИЧЕСКИ
  удаляют старые .lance data-файлы. Если В ЭТО ЖЕ ВРЕМЯ другой поток/процесс
  читает таблицу (search / incremental notify_change / _parse_file_only),
  LanceDB открывает manifest, который ссылается на уже-удалённый .lance-файл
  -> RuntimeError: lance error: Not found: .../data/<hash>.lance

Цель эксперимента:
  1. Воспроизвести `Not found` в изолированной песочнице (без прод-кода).
  2. Проверить 3 стратегии защиты:
     A) reindex_guard (Event) — читающий поток ждёт/фейлит пока reindex идёт
     B) checkout_version / snapshot isolation — читать фиксированную версию
     C) последовательность: дождаться optimize() ПОЛНОСТЬЮ (shutdown wait=True)
        перед тем как отдавать таблицу читателям (уже есть в коде, но не на всех путях)

Запуск:
  python experiments/sandbox_lancedb_race.py
"""
import sys
import os
import time
import shutil
import threading
import traceback
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Используем ТОТ ЖЕ venv, что и MCP (LanceDB 0.34.0)
VENV = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\venv\Scripts\python.exe")
SANDBOX = Path(r"D:\Project\MSCodeBase\.sandbox_lancedb_race")

import lancedb
from lancedb.table import Table

print(f"lancedb version: {lancedb.__version__}")

def make_schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("id", pa.int64()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 4)),
    ])

def seed(n=200):
    import pyarrow as pa
    rows = []
    for i in range(n):
        rows.append({
            "id": i,
            "text": f"chunk number {i} about function def foo_{i}",
            "vector": [float(i % 4), float((i*2) % 4), float((i*3) % 4), float((i*4) % 4)],
        })
    return pa.Table.from_pylist(rows, schema=make_schema())

def fresh_db():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(SANDBOX))
    tbl = db.create_table("t", seed(200))
    return db, tbl

# ── Эксперимент 1: optimize + параллельное чтение (без защиты) ──
def exp1_no_guard():
    print("\n=== EXP1: optimize() + параллельное чтение БЕЗ guard ===")
    db, tbl = fresh_db()
    errors = []

    def reader():
        for _ in range(50):
            try:
                # Имитация search / _parse_file_only: читает таблицу
                _ = tbl.to_arrow()
                _ = tbl.search([0.0, 1.0, 2.0, 3.0]).limit(5).to_arrow()
            except Exception as e:
                errors.append(str(e)[:120])
                # print("  reader error:", str(e)[:80])
            time.sleep(0.02)

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    # Запускаем optimize (он удаляет старые data-файлы)
    try:
        tbl.optimize()
    except Exception as e:
        print("  optimize error:", str(e)[:120])
    r.join(timeout=5)
    print(f"  reader errors: {len(errors)}")
    if errors:
        print(f"  SAMPLE: {errors[0]}")
    return len(errors)

# ── Эксперимент 2: compact_files + параллельное чтение ──
def exp2_compact():
    print("\n=== EXP2: compact_files() + параллельное чтение БЕЗ guard ===")
    db, tbl = fresh_db()
    # Сначала сделаем несколько версий (delete + add), чтобы compact имел что удалять
    for k in range(5):
        tbl.delete("id < 50")
        import pyarrow as pa
        new_rows = [{"id": 1000+k*10+j, "text": f"new {j}", "vector":[0.1,0.2,0.3,0.4]} for j in range(10)]
        tbl.add(pa.Table.from_pylist(new_rows, schema=make_schema()))
    errors = []
    def reader():
        for _ in range(50):
            try:
                _ = tbl.to_arrow()
            except Exception as e:
                errors.append(str(e)[:120])
            time.sleep(0.02)
    r = threading.Thread(target=reader, daemon=True)
    r.start()
    try:
        tbl.compact_files()
    except Exception as e:
        print("  compact error:", str(e)[:120])
    r.join(timeout=5)
    print(f"  reader errors: {len(errors)}")
    if errors:
        print(f"  SAMPLE: {errors[0]}")
    return len(errors)

# ── Эксперимент 3: reindex_guard (Event) защита ──
def exp3_with_guard():
    print("\n=== EXP3: optimize() + параллельное чтение С guard (Event) ===")
    db, tbl = fresh_db()
    guard = threading.Event()  # set = reindex идёт
    errors = []

    def reader():
        for _ in range(50):
            if guard.is_set():
                # fast-fail: не читаем поломанный индекс
                time.sleep(0.02)
                continue
            try:
                _ = tbl.to_arrow()
                _ = tbl.search([0.0, 1.0, 2.0, 3.0]).limit(5).to_arrow()
            except Exception as e:
                errors.append(str(e)[:120])
            time.sleep(0.02)

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    guard.set()  # reindex начался
    try:
        tbl.optimize()
    except Exception as e:
        print("  optimize error:", str(e)[:120])
    guard.clear()  # reindex закончился
    r.join(timeout=5)
    print(f"  reader errors (должно быть 0): {len(errors)}")
    return len(errors)

# ── Эксперимент 4: checkout_version (snapshot isolation) ──
def exp4_checkout():
    print("\n=== EXP4: checkout_version (snapshot) + optimize параллельно ===")
    db, tbl = fresh_db()
    # Зафиксируем версию ДО optimize
    try:
        version = tbl.version
    except Exception:
        version = None
    errors = []

    def reader():
        for _ in range(50):
            try:
                # Читаем зафиксированную версию (snapshot isolation)
                if version is not None:
                    t2 = tbl.checkout_version(version)
                    _ = t2.to_arrow()
                else:
                    _ = tbl.to_arrow()
            except Exception as e:
                errors.append(str(e)[:120])
            time.sleep(0.02)

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    try:
        tbl.optimize()
    except Exception as e:
        print("  optimize error:", str(e)[:120])
    r.join(timeout=5)
    print(f"  reader errors: {len(errors)}")
    if errors:
        print(f"  SAMPLE: {errors[0]}")
    return len(errors)

# ── Эксперимент 5: delete (Pruning) + параллельное чтение to_pandas ──
def exp5_delete_race():
    print("\n=== EXP5: delete() (Pruning) + параллельное to_pandas() БЕЗ guard ===")
    db, tbl = fresh_db()
    errors = []

    def reader():
        for _ in range(80):
            try:
                # Имитация _parse_file_only / prune_deleted_files чтение
                _ = tbl.to_pandas()
                _ = tbl.search().where("id < 10").limit(5).to_pandas()
            except Exception as e:
                errors.append(str(e)[:140])
            time.sleep(0.01)

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    # Имитация reindex: много delete + add (как в Pruning + rewrite)
    try:
        for k in range(30):
            tbl.delete(f"id >= {k*5} AND id < {k*5+5}")
            import pyarrow as pa
            new_rows = [{"id": 5000+k*10+j, "text": f"new {j}", "vector":[0.1,0.2,0.3,0.4]} for j in range(10)]
            tbl.add(pa.Table.from_pylist(new_rows, schema=make_schema()))
    except Exception as e:
        print("  writer error:", str(e)[:120])
    r.join(timeout=5)
    print(f"  reader errors: {len(errors)}")
    if errors:
        print(f"  SAMPLE: {errors[0]}")
    return len(errors)

# ── Эксперимент 6: delete + чтение С guard (Event) ──
def exp6_delete_guard():
    print("\n=== EXP6: delete() (Pruning) + параллельное чтение С guard (Event) ===")
    db, tbl = fresh_db()
    guard = threading.Event()
    errors = []

    def reader():
        for _ in range(80):
            if guard.is_set():
                time.sleep(0.01)
                continue
            try:
                _ = tbl.to_pandas()
                _ = tbl.search().where("id < 10").limit(5).to_pandas()
            except Exception as e:
                errors.append(str(e)[:140])
            time.sleep(0.01)

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    guard.set()
    try:
        for k in range(30):
            tbl.delete(f"id >= {k*5} AND id < {k*5+5}")
            import pyarrow as pa
            new_rows = [{"id": 5000+k*10+j, "text": f"new {j}", "vector":[0.1,0.2,0.3,0.4]} for j in range(10)]
            tbl.add(pa.Table.from_pylist(new_rows, schema=make_schema()))
    except Exception as e:
        print("  writer error:", str(e)[:120])
    guard.clear()
    r.join(timeout=5)
    print(f"  reader errors (должно быть 0): {len(errors)}")
    return len(errors)

if __name__ == "__main__":
    print("Starting LanceDB race reproduction experiments...\n")
    r1 = exp1_no_guard()
    r2 = exp2_compact()
    r3 = exp3_with_guard()
    r4 = exp4_checkout()
    r5 = exp5_delete_race()
    r6 = exp6_delete_guard()
    print("\n=== RESULTS ===")
    print(f"EXP1 (optimize, no guard):   errors={r1}")
    print(f"EXP2 (compact, no guard):   errors={r2}")
    print(f"EXP3 (guard Event):         errors={r3}")
    print(f"EXP4 (checkout_version):    errors={r4}")
    print(f"EXP5 (delete, no guard):    errors={r5}")
    print(f"EXP6 (delete + guard):      errors={r6}")
    print("\nВердикт:")
    if r1 > 0 or r2 > 0 or r5 > 0:
        print("  ✅ Гонка ВОСПРОИЗВЕДЕНА (Not found при write/delete + параллельное чтение)")
    else:
        print("  ⚠️ Гонка НЕ воспроизведена в песочнице (нужен другой сценарий)")
    if r3 == 0 and r6 == 0:
        print("  ✅ Guard (Event) защищает от чтения во время reindex")
    else:
        print("  ❌ Guard НЕ защитил — нужна сериализация write/read через _write_lock")
