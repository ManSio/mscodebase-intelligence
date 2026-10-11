"""INVESTIGATE-SCALE: why our load/match numbers differ from Tom's by 100-200x.

Protocol: components measured separately, cold vs warm, with controls.
Deterministic, no model, $0. Raw output only; interpretation in the report.
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
STORE_SRC = HERE / "store2"
TEMPLATE = (STORE_SRC / "memory" / "crystals"
            / "crystal-a-positive-control-cannot-detect-a-yes-machine.md").read_text(encoding="utf-8")

sys.path.insert(0, str(CODE / "scripts"))
import crystal_act as ca  # noqa: E402
import crystal_registry as cr  # noqa: E402

HEAD_BYTES = getattr(cr, "HEAD_BYTES", 8192)


def build_store(base: Path, n: int) -> None:
    if base.exists():
        shutil.rmtree(base, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    dest = base / "memory" / "crystals"
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (dest / f"syn_{i:05d}.md").write_text(
            TEMPLATE.replace("positive-control-cannot-detect-a-yes-machine", f"synthetic-{i:05d}")
                    .replace("--selftest, selftest, gold control, benchmark, eval, scorer, checker",
                             f"kw{i:05d}alpha, kw{i:05d}beta"),
            encoding="utf-8")


def files_of(base: Path):
    dest = base / "memory" / "crystals"
    return [dest / f for f in sorted(os.listdir(dest)) if f.endswith(".md")]


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    r = fn(*a, **k)
    return time.perf_counter() - t0, r


def main() -> None:
    report = {"template_chars": len(TEMPLATE), "head_bytes": HEAD_BYTES,
              "ctrls": {}, "rows": []}

    # ── CONTROLS (harness must be able to see cost and to show zero) ──
    t0 = time.perf_counter()
    time.sleep(0.05)
    report["ctrls"]["sleep_50ms"] = round(time.perf_counter() - t0, 4)
    empty = HERE / "scale_empty"
    if empty.exists():
        shutil.rmtree(empty)
    (empty / "memory" / "crystals").mkdir(parents=True)
    c_load, c_cand = timed(cr.load_crystals, str(empty))
    report["ctrls"]["empty_load_s"] = round(c_load, 5)
    report["ctrls"]["empty_load_n"] = len(c_cand)
    os.environ["CRYSTAL_STORE_ROOT"] = str(empty)
    report["ctrls"]["empty_candidates"] = len(cr.for_act(cr.load_crystals(str(empty)), "bash"))

    for n in (100, 1000, 5000):
        base = HERE / f"scale_{n}"
        build_store(base, n)
        os.environ["CRYSTAL_STORE_ROOT"] = str(base)
        fs = files_of(base)
        row = {"n": n}

        # raw file operations (metadata vs content), cold (files just written)
        t_walk, _ = timed(lambda: [os.path.join(r, f)
                                   for r, d, ff in os.walk(base) for f in ff if f.endswith(".md")])
        row["walk_s"] = round(t_walk, 4)
        t_stat, _ = timed(lambda: [os.stat(f) for f in fs])
        row["stat_s"] = round(t_stat, 4)
        t_head, _ = timed(lambda: [_read_head(f) for f in fs])
        row["open_head_s"] = round(t_head, 4)
        t_full, texts = timed(lambda: [_read_full(f) for f in fs])
        row["open_full_s"] = round(t_full, 4)
        t_parse, _ = timed(lambda: [cr._parse_binding(cr._frontmatter(x)) for x in texts])
        row["parse_binding_s"] = round(t_parse, 4)
        t_ess, _ = timed(lambda: [cr._essence(x) for x in texts])
        row["essence_s"] = round(t_ess, 4)

        # full load, cold (as originally measured)
        t_load_cold, loaded = timed(cr.load_crystals, str(base))
        row["load_cold_s"] = round(t_load_cold, 4)
        # full load, warm (page cache; AV re-scan behaviour differs)
        t_load_warm, _ = timed(cr.load_crystals, str(base))
        row["load_warm_s"] = round(t_load_warm, 4)

        # candidates(repo=) == ORIGINAL method: re-loads internally
        t_cand_repo, _ = timed(ca.candidates, "bash", ctx="please run eval please", repo=str(base))
        row["candidates_repo_s"] = round(t_cand_repo, 4)
        # candidates(crystals=preloaded) == PURE match, no re-load
        t_cand_pre, _ = timed(ca.candidates, "bash", ctx="please run eval please",
                              repo=str(base), crystals=loaded)
        row["candidates_preloaded_s"] = round(t_cand_pre, 5)

        row["per_file_load_cold_us"] = round(t_load_cold / n * 1e6, 1)
        row["per_file_load_warm_us"] = round(t_load_warm / n * 1e6, 1)
        row["per_crystal_match_us"] = round(t_cand_pre / n * 1e6, 3)
        row["essence_chars"] = len(loaded[0]["essence"]) if loaded else 0
        row["loaded_n"] = len(loaded)
        report["rows"].append(row)
        print(json.dumps(row, ensure_ascii=False))
        shutil.rmtree(base, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))

    (HERE / "results" / "INVESTIGATE_SCALE.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nctrls:", json.dumps(report["ctrls"], ensure_ascii=False))
    print("wrote results/INVESTIGATE_SCALE.json")


def _read_head(p):
    with open(p, encoding="utf-8") as f:
        return f.read(HEAD_BYTES)


def _read_full(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    main()
