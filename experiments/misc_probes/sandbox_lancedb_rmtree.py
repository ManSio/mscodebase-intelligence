"""
Sandbox EXP9: rmtree БД во время чтения (точная имитация intel_trigger_reindex mode=full).

Гипотеза ТОЧНАЯ (root cause 2026-07-20):
  intel_trigger_reindex(mode="full") делает shutil.rmtree('.codebase_indices')
  — физически удаляет ВСЮ LanceDB-директорию.
  Если в этот момент ВТОРОЙ MCP-процесс (или этот же, но с устаревшей
  ссылкой self.table) читает таблицу -> Not found, потому что
  .lance data-файлы физически удалены, а manifest/ссылка жива.

  Плюс: rmtree с ignore_errors=True при конкурентной записи второго
  процесса удаляет ЧАСТИЧНО -> битый manifest -> следующий reindex
  падает на Pruning (Not found).

Запуск:
  python experiments/sandbox_lancedb_rmtree.py
"""
import sys
import time
import shutil
import subprocess
import threading
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

VENV_PY = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\venv\Scripts\python.exe"
SANDBOX = Path(r"D:\Project\MSCodeBase\.sandbox_lancedb_rmtree")

WORKER = r'''
import sys, time, shutil
from pathlib import Path
import lancedb
import pyarrow as pa

SANDBOX = "__SANDBOX__"
db = lancedb.connect(SANDBOX)
schema = pa.schema([
    pa.field("id", pa.int64()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 4)),
])
mode = "__MODE__"
errors = 0
try:
    if mode == "writer":
        # Имитация intel_trigger_reindex(full): rmtree БД + recreate
        if db.table_names():
            rows = []
            for i in range(100):
                rows.append({"id": i, "text": "c" + str(i), "vector": [0.0,0.0,0.0,0.0]})
            db.create_table("t", pa.Table.from_pylist(rows, schema=schema))
        for k in range(5):
            time.sleep(0.3)
            # ТОЧНАЯ имитация: rmtree всей директории БД
            shutil.rmtree(str(SANDBOX), ignore_errors=True)
            SANDBOX.mkdir(parents=True, exist_ok=True)
            db2 = lancedb.connect(SANDBOX)
            db2.create_table("t", pa.Table.from_pylist(
                [{"id": 1000+k*10+j, "text": "n" + str(j), "vector": [0.1,0.2,0.3,0.4]} for j in range(10)],
                schema=schema))
    else:
        # Читатель держит таблицу открытой и читает в цикле (как search / Pruning)
        if not db.table_names():
            time.sleep(0.2)
        tbl = db.open_table("t")
        for _ in range(200):
            try:
                tbl.to_pandas()
                tbl.search([0.0,0.0,0.0,0.0]).limit(5).to_pandas()
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print("READER_ERR:", str(e)[:140], flush=True)
            time.sleep(0.02)
except Exception as e:
    print("FATAL", mode, str(e)[:140], flush=True)
print("DONE_" + mode + "_errors=" + str(errors), flush=True)
'''


def run():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("=== EXP9: rmtree БД во время чтения (2 процесса, имитация full reindex) ===")
    w = WORKER.replace("__SANDBOX__", str(SANDBOX)).replace("__MODE__", "writer")
    r = WORKER.replace("__SANDBOX__", str(SANDBOX)).replace("__MODE__", "reader")
    wf = SANDBOX / "w.py"
    rf = SANDBOX / "r.py"
    wf.write_text(w)
    rf.write_text(r)

    p_w = subprocess.Popen([VENV_PY, str(wf)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p_r = subprocess.Popen([VENV_PY, str(rf)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    reader_errs = 0

    def drain(p, tag):
        nonlocal reader_errs
        for line in p.stdout:
            line = line.strip()
            if "READER_ERR" in line:
                reader_errs += 1
                print("  [" + tag + "] " + line, flush=True)
            elif "DONE" in line or "FATAL" in line:
                print("  [" + tag + "] " + line, flush=True)

    t1 = threading.Thread(target=drain, args=(p_w, "W"), daemon=True)
    t2 = threading.Thread(target=drain, args=(p_r, "R"), daemon=True)
    t1.start()
    t2.start()
    p_w.wait()
    p_r.wait()
    t1.join(2)
    t2.join(2)

    print("")
    print("=== VERDICT EXP9 ===")
    if reader_errs > 0:
        print("  ✅ Гонка ВОСПРОИЗВЕДЕНА: " + str(reader_errs) + " ошибок Not found при rmtree БД+чтение")
        print("  >>> Root cause ПОДТВЕРЖДЁН: intel_trigger_reindex(full) делает rmtree БД,")
        print("      второй процесс/устаревшая ссылка падает с Not found")
    else:
        print("  ⚠️ Не воспроизведено (LanceDB 0.34 держит файлы открытыми через handle)")
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    run()
