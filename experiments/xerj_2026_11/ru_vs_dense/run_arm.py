"""One arm of the RU-vs-dense experiment.

A/B use lexical retrieval (dense_off=true); C uses the rebuilt 768-d dense
table (dense_off=false). Every question gets the SAME 3-query budget, so
"turns" is comparable across arms.

Run: python experiments/xerj_2026_11/ru_vs_dense/run_arm.py --arm A|B|C
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FROZEN = HERE / "frozen"
sys.path.insert(0, str(ROOT))

REPOS = {
    "itsdangerous": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pallets__itsdangerous__HEAD-672971d"
    ),
    "iniconfig": Path(
        r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11"
        r"\pytest-dev__iniconfig__HEAD-a9e0ad1"
    ),
}

ARM_LANG = {"A": "ru", "B": "en", "C": "ru"}


def matches_gold(path: str, repo: str, gold: str) -> bool:
    """Exact implementation path, not any file with the same basename.

    `endswith(gold)` matched tests/test_<repo>/test_<gold> and scored a test file
    as the gold (found by independent review, 2026-11-09). The gold is the file
    that contains the implementation: src/<repo>/<gold>.
    """
    normalized = path.replace("\\", "/")
    return normalized.endswith(f"src/{repo}/{gold}")


def rank_of(rows, repo, gold):
    for index, row in enumerate(rows, 1):
        meta = row.get("metadata") or {}
        path = str(meta.get("file") or row.get("file") or "")
        if matches_gold(path, repo, gold):
            return index
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["A", "B", "C"], required=True)
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()

    dense = args.arm == "C"
    os.environ["MSCODEBASE_DENSE_OFF"] = "false" if dense else "true"
    if args.no_rerank:
        os.environ["MSCODEBASE_ONDEMAND_RERANK"] = "false"

    questions = json.loads((FROZEN / "questions.json").read_text(encoding="utf-8"))
    queries = json.loads((FROZEN / "queries.json").read_text(encoding="utf-8"))["queries"]
    lang = ARM_LANG[args.arm]

    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )

    out = {
        "arm": args.arm,
        "mode": "dense" if dense else "lexical",
        "lang": lang,
        "limit": 10,
        "ondemand_rerank": None,  # filled from config below
        "cases": {},
        "controls": {},
    }
    try:
        services_by_repo = {}
        searchers = {}
        embedder_modes = {}
        for name, project in REPOS.items():
            services = create_service_collection(project)
            services_by_repo[name] = services
            indexer = services.resolve(ProjectIndexerRegistry).get_indexer(
                project, factory=services.resolve(IndexerFactoryKey)
            )
            from src.providers.embedder.remote_embedder import RemoteEmbedder

            embedder = services.resolve(RemoteEmbedder)
            with embedder._mode_lock:
                embedder.mode = "llama_cpp"
            embedder_modes[name] = {
                "mode": embedder.mode,
                "dim": embedder.embedding_dim,
            }
            searchers[name] = indexer.searcher

        for case in questions["cases"]:
            searcher = searchers[case["repo"]]
            ranks, elapsed, top3 = [], [], []
            dense_rows = []
            for query in queries[case["id"]][lang]:
                started = time.perf_counter()
                rows = asyncio.run(searcher.hybrid_search_async(query, limit=10)) or []
                elapsed.append(round(time.perf_counter() - started, 3))
                dense_rows.append(
                    sum(1 for r in rows if (r.get("dense_score") or 0) > 0)
                )
                ranks.append(rank_of(rows, case["repo"], case["gold"]))
                if len(top3) < 1:
                    top3 = [
                        str((r.get("metadata") or {}).get("file") or "")
                        for r in rows[:3]
                    ]
            out["cases"][case["id"]] = {
                "gold": case["gold"],
                "repo": case["repo"],
                "queries": queries[case["id"]][lang],
                "ranks": ranks,
                "hit@turn1": bool(ranks[0] and ranks[0] <= 10),
                "hit@turn3": bool([r for r in ranks if r and r <= 10]),
                "turns_to_success": next(
                    (i for i, r in enumerate(ranks, 1) if r and r <= 10), None
                ),
                "top3_first_turn": top3,
                "seconds": elapsed,
                "dense_rows": dense_rows,
            }

        controls = questions["controls"]
        pos = asyncio.run(
            searchers["itsdangerous"].hybrid_search_async(
                controls["positive"]["query"], limit=10
            )
        ) or []
        neg = asyncio.run(
            searchers["itsdangerous"].hybrid_search_async(
                controls["negative"]["query"], limit=10
            )
        ) or []
        empty = asyncio.run(
            searchers["itsdangerous"].hybrid_search_async("   ", limit=10)
        ) or []
        out["controls"] = {
            "positive_rank": rank_of(
                pos, "itsdangerous", controls["positive"]["gold"]
            ),
            "negative_rows": len(neg),
            "empty_rows": len(empty),
        }
    finally:
        for services in locals().get("services_by_repo", {}).values():
            shutdown = getattr(services, "shutdown", None)
            if callable(shutdown):
                try:
                    asyncio.run(shutdown())
                except Exception:  # noqa: BLE001 - shutdown must not mask results
                    pass

    from src.config.settings import get_config

    out["ondemand_rerank"] = bool(get_config().search.ondemand_rerank)
    out["embedder"] = embedder_modes
    cases = out["cases"].values()
    total = len(out["cases"])
    out["summary"] = {
        "cases": total,
        "hit@turn1": sum(1 for c in cases if c["hit@turn1"]),
        "hit@turn3": sum(1 for c in cases if c["hit@turn3"]),
    }
    print(
        f"arm={args.arm} mode={out['mode']} lang={lang} "
        f"hit@turn1={out['summary']['hit@turn1']}/{total} "
        f"hit@turn3={out['summary']['hit@turn3']}/{total}"
    )
    for case_id, case in out["cases"].items():
        print(
            f"  {case_id} gold={case['gold']:<13} ranks={case['ranks']} "
            f"turns={case['turns_to_success']}"
        )
    print("  controls:", out["controls"])
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / (f"{args.arm}_norerank.json" if args.no_rerank else f"{args.arm}.json")).write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
