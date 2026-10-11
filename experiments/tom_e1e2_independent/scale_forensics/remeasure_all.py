"""REMEASURE-ALL: re-run every wall-clock experiment with Defender OFF,
fixed harness (load and match separated; no hidden re-load). Persist raw.
Deterministic, $0.

Covers: (A) scale load vs true match; (B) ledger-size due_for; (C) 10MB ctx.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CODE = Path(r"D:\Project\tom_e1e2_2026-10-10\code-fe4e465")
DELIV = Path(r"D:\Project\tom_e1e2_2026-10-10\delivery")
HERE = Path(__file__).parent
TEMPLATE = (HERE / "store2" / "memory" / "crystals"
            / "crystal-a-positive-control-cannot-detect-a-yes-machine.md").read_text(encoding="utf-8")
sys.path.insert(0, str(CODE / "scripts"))
import crystal_act as ca  # noqa: E402
import crystal_registry as cr  # noqa: E402

OUT = HERE / "results" / "REMEASURE.json"
res = {"defender_rt": os.popen(
    'powershell -NoProfile -Command "(Get-MpComputerStatus).RealTimeProtectionEnabled"'
).read().strip()}


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, x, e: (os.chmod(x, 0o700), f(x)))


def build(base: Path, n: int, nonce: str) -> None:
    rmtree(base)
    dest = base / "memory" / "crystals"
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (dest / f"syn_{nonce}_{i:05d}.md").write_text(
            TEMPLATE.replace("positive-control-cannot-detect-a-yes-machine", f"syn-{nonce}-{i:05d}")
                    .replace("--selftest, selftest, gold control, benchmark, eval, scorer, checker",
                             f"kw{i:05d}alpha, kw{i:05d}beta"), encoding="utf-8")


# ── A. SCALE ──
res["A_scale"] = []
for n in (100, 1000, 5000):
    base = HERE / f"rm_{n}"
    build(base, n, "rm")
    os.environ["CRYSTAL_STORE_ROOT"] = str(base)
    t0 = time.perf_counter(); loaded = cr.load_crystals(str(base)); load = time.perf_counter() - t0
    t0 = time.perf_counter(); ca.candidates("bash", ctx="please run eval please", repo=str(base)); cand_repo = time.perf_counter() - t0
    t0 = time.perf_counter(); ca.candidates("bash", ctx="please run eval please", repo=str(base), crystals=loaded); match = time.perf_counter() - t0
    row = {"n": n, "load_s": round(load, 4), "load_us_per_file": round(load / n * 1e6, 1),
           "candidates_repo_s": round(cand_repo, 4), "true_match_s": round(match, 5),
           "true_match_us_per_crystal": round(match / n * 1e6, 3),
           "essence_chars": len(loaded[0]["essence"]) if loaded else 0}
    res["A_scale"].append(row); print("A", json.dumps(row))
    rmtree(base)

# ── B. LEDGER SIZE ──
sys.path.insert(0, str(DELIV))
import check_delivery2 as cd  # noqa: E402
cd.build_store()
os.environ["CRYSTAL_STORE_ROOT"] = str(cd.STORE)
os.environ["CRYSTAL_ELIGIBILITY_LOG"] = "0"
os.environ["CRYSTAL_WHO"] = "frontier"
led = Path(str(ca.LEDGER))
GREEN = "crystal-green-tests-do-not-prove-head-builds.md"
res["B_ledger"] = []
for n in (0, 1000, 10000, 20000):
    now = time.time()
    blob = {"_ledger-schema": 2, "session-last:S0": now, "act:bash:" + GREEN: now - 3600}
    for i in range(n):
        blob[f"act-session:S{i}:bash:some-crystal-{i}.md"] = 1
        blob[f"session-last:S{i}"] = now
    for i in range(n):  # second pass (was dead in ledger_perf.py); ensure written variant
        blob[f"act-session:S{i}:bash:some-crystal-{i}.md"] = 1
    led.write_text(json.dumps(blob), encoding="utf-8")
    t0 = time.perf_counter()
    ca.due_for("bash", "Sprobe", dry=False, ctx="please run tsc now", repo=str(cd.STORE))
    dt = time.perf_counter() - t0
    row = {"entries": len(blob), "due_for_s": round(dt, 4)}
    res["B_ledger"].append(row); print("B", json.dumps(row))
led.unlink(missing_ok=True)

# ── C. 10MB CONTEXT (failmode / ReDoS) ──
cs = {os.path.basename(c["path"]): c for c in cr.load_crystals(str(cd.STORE))}
big = "word " * (10 * 1024 * 1024 // 5)
t0 = time.perf_counter()
ca.due_for("bash", "C1", dry=True, ctx="run eval please " + big, repo=str(cd.STORE))
dt = time.perf_counter() - t0
res["C_ctx10mb_s"] = round(dt, 3)
print("C 10MB ctx:", res["C_ctx10mb_s"])

OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", OUT)
