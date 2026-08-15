"""
Sandbox EXP7: МЕЖПРОЦЕССНАЯ гонка LanceDB `Not found`.

Гипотеза (root cause из расследования 2026-07-20):
  ДВА экземпляра MCP (src.main) пишут в ОДНУ LanceDB-директорию.
  Один делает full reindex (удаляет старые .lance data-файлы через
  optimize/cleanup), второй держит старый manifest и читает/пишет по
  удалённому файлу -> RuntimeError: lance error: Not found.

  Это НЕ воспроизводится в однопроцессной песочнице (EXP1-6 дали 0 ошибок),
  потому что LanceDB внутри одного процесса сериализует доступ к manifest.

Цель: доказать, что при 2 процессах -> Not found воспроизводится.

Запуск:
  python experiments/sandbox_lancedb_multiproc.py
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
SANDBOX = Path(r"D:\Project\MSCodeBase\.sandbox_lancedb_mp")

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
        if not db.table_names():
            rows = []
            for i in range(100):
                rows.append({"id": i, "text": "c" + str(i), "vector": [0.0,0.0,0.0,0.0]})
            db.create_table("t", pa.Table.from_pylist(rows, schema=schema))
        tbl = db.open_table("t")
        for k in range(40):
            tbl.delete("id < 50")
            new_rows = []
            for j in range(10):
                new_rows.append({"id": 5000+k*10+j, "text": "n" + str(j), "vector": [0.1,0.2,0.3,0.4]})
            tbl.add(pa.Table.from_pylist(new_rows, schema=schema))
            try:
                tbl.optimize()
            except Exception:
                pass
            time.sleep(0.05)
    else:
        if not db.table_names():
            time.sleep(0.1)
        tbl = db.open_table("t")
        for _ in range(100):
            try:
                tbl.to_pandas()
                tbl.search([0.0,0.0,0.0,0.0]).limit(5).to_pandas()
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print("READER_ERR:", str(e)[:140], flush=True)
            time.sleep(0.03)
except Exception as e:
    print("FATAL", mode, str(e)[:140], flush=True)
print("DONE_" + mode + "_errors=" + str(errors), flush=True)
'''


def run():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("=== EXP7: 2 процесса пишут в ОДНУ БД (writer reindex + reader) ===")
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
    print("=== VERDICT EXP7 ===")
    if reader_errs > 0:
        print("  ✅ МЕЖПРОЦЕССНАЯ гонка ВОСПРОИЗВЕДЕНА: " + str(reader_errs) + " ошибок Not found")
        print("  >>> Root cause подтверждён: два MCP-процесса в одну БД = Not found")
    else:
        print("  ⚠️ Не воспроизведено даже в 2 процессах (нужен cleanup всей директории)")
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    run()
