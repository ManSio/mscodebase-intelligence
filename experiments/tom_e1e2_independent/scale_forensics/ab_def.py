"""A/B: Defender Real-Time ON vs OFF, same session, same harness, fresh store
per run with a nonce in filenames (so AV path-cache cannot help). Deterministic.
Usage: python ab_def.py <label> <nonce> <n>
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
HERE = Path(__file__).parent
TEMPLATE = (HERE / "store2" / "memory" / "crystals"
            / "crystal-a-positive-control-cannot-detect-a-yes-machine.md").read_text(encoding="utf-8")
sys.path.insert(0, str(CODE / "scripts"))
import crystal_act as ca  # noqa: E402
import crystal_registry as cr  # noqa: E402


def main() -> None:
    label, nonce, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    base = HERE / f"ab_{label}"
    if base.exists():
        shutil.rmtree(base, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    dest = base / "memory" / "crystals"
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (dest / f"syn_{nonce}_{i:05d}.md").write_text(
            TEMPLATE.replace("positive-control-cannot-detect-a-yes-machine", f"syn-{nonce}-{i:05d}")
                    .replace("--selftest, selftest, gold control, benchmark, eval, scorer, checker",
                             f"kw{i:05d}alpha, kw{i:05d}beta"),
            encoding="utf-8")
    os.environ["CRYSTAL_STORE_ROOT"] = str(base)

    t0 = time.perf_counter()
    loaded = cr.load_crystals(str(base))
    load_cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    cr.load_crystals(str(base))
    load_warm = time.perf_counter() - t0

    t0 = time.perf_counter()
    ca.candidates("bash", ctx="please run eval please", repo=str(base))
    cand_repo = time.perf_counter() - t0

    t0 = time.perf_counter()
    ca.candidates("bash", ctx="please run eval please", repo=str(base), crystals=loaded)
    cand_pre = time.perf_counter() - t0

    out = {"label": label, "n": n, "nonce": nonce,
           "load_cold_s": round(load_cold, 4), "load_warm_s": round(load_warm, 4),
           "candidates_repo_s": round(cand_repo, 4),
           "candidates_preloaded_s": round(cand_pre, 5),
           "load_cold_us_per_file": round(load_cold / n * 1e6, 1),
           "match_us_per_crystal": round(cand_pre / n * 1e6, 3)}
    print(json.dumps(out))
    res = HERE / "results" / "AB_DEFENDER.jsonl"
    with open(res, "a", encoding="utf-8") as f:
        f.write(json.dumps(out) + "\n")
    shutil.rmtree(base, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))


if __name__ == "__main__":
    main()
