"""
Sandbox EXP10: in-process race (exact MCP imitation).

Root cause (2026-07-20): MCP holds self.table open (from __init__).
intel_trigger_reindex(full) does shutil.rmtree('.codebase_indices')
OUTSIDE guard. In ONE process: rmtree with ignore_errors=True cannot
delete files locked by the live self.table (OS handle), but deletes
the unlocked ones -> manifest becomes mixed/broken. Reading self.table
AFTER rmtree -> Not found.

Reproduces ONLY in-process (like MCP), not in 2 separate processes
(EXP7-9 failed because LanceDB in separate processes uses handles correctly).

Run: python experiments/sandbox_lancedb_inproc.py
"""
import sys
import time
import shutil
import subprocess
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

VENV_PY = r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\venv\Scripts\python.exe"
SANDBOX = Path(r"D:\Project\MSCodeBase\.sandbox_lancedb_inproc")

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
db.create_table("t", pa.Table.from_pylist(
    [{"id": i, "text": "c" + str(i), "vector": [0.0,0.0,0.0,0.0]} for i in range(100)],
    schema=schema))
self_table = db.open_table("t")

errors = 0
shutil.rmtree(str(SANDBOX), ignore_errors=True)
import pathlib as _pl
_pl.Path(SANDBOX).mkdir(parents=True, exist_ok=True)

for _ in range(20):
    try:
        self_table.to_pandas()
        self_table.search([0.0,0.0,0.0,0.0]).limit(5).to_pandas()
    except Exception as e:
        errors += 1
        if errors <= 3:
            print("READER_ERR:", str(e)[:140], flush=True)
    time.sleep(0.05)

try:
    db2 = lancedb.connect(SANDBOX)
    if not db2.table_names():
        db2.create_table("t", pa.Table.from_pylist(
            [{"id": 1, "text": "x", "vector": [0.0,0.0,0.0,0.0]}], schema=schema))
    self_table = db2.open_table("t")
    self_table.to_pandas()
    print("AFTER_RESET: OK", flush=True)
except Exception as e:
    print("AFTER_RESET_ERR:", str(e)[:140], flush=True)

print("DONE_errors=" + str(errors), flush=True)
'''


def run():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    print("=== EXP10: in-process rmtree + read self.table (like MCP) ===")
    wf = SANDBOX / "w.py"
    wf.write_text(WORKER.replace("__SANDBOX__", str(SANDBOX)))

    p = subprocess.Popen([VENV_PY, str(wf)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    for line in p.stdout:
        line = line.strip()
        out.append(line)
        print("  " + line, flush=True)
    p.wait()

    print("")
    print("=== VERDICT EXP10 ===")
    errs = sum(1 for l in out if "READER_ERR" in l)
    if errs > 0:
        print(f"  OK race REPRODUCED: {errs} Not found errors (in-process rmtree)")
        print("  >>> Root cause CONFIRMED: rmtree DB with live self.table = Not found")
    else:
        print("  WARN not reproduced")
    if any("AFTER_RESET: OK" in l for l in out):
        print("  OK reset_connection() (reopen table) FIXES dangling self.table")
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    run()
