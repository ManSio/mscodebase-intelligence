"""RU question -> blind English translation -> the SAME lexical search.

The owner's hypothesis: for an agent, a dense index is unnecessary because the
LLM can translate the question into English itself. This measures the lexical
arm only, with translations produced blind (fresh context, no repo access, no
gold names, no invented identifiers), so the result is not hindsight.

Gold files were read from the source earlier (signer.py: sep; timed.py:
expire/max_age; url_safe.py: base64; _parse.py: duplicate; __init__.py: comment).

Run: python experiments/xerj_2026_11/probe_translated_ru.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["MSCODEBASE_DENSE_OFF"] = "true"

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

CASES = [
    ("itsdangerous", "signer.py", [
        "split signature from payload",
        "separate signature payload",
        "verify signature payload parsing",
    ]),
    ("itsdangerous", "timed.py", [
        "reject expired signature",
        "signature expiry validation",
        "check signature expiration time",
    ]),
    ("itsdangerous", "url_safe.py", [
        "url-safe base64 encode",
        "base64url decode encoding",
        "url safe base64 conversion",
    ]),
    ("iniconfig", "_parse.py", [
        "reject duplicate sections",
        "duplicate section detection",
        "detect repeated sections input",
    ]),
    ("iniconfig", "__init__.py", [
        "strip line comment",
        "remove inline comment value",
        "parse comment from value",
    ]),
]


def main() -> int:
    from src.core.di_container import (
        IndexerFactoryKey,
        ProjectIndexerRegistry,
        create_service_collection,
    )

    first_hits = best_hits = 0
    for name, project in REPOS.items():
        services = create_service_collection(project)
        try:
            registry = services.resolve(ProjectIndexerRegistry)
            indexer = registry.get_indexer(
                project, factory=services.resolve(IndexerFactoryKey)
            )
            searcher = indexer.searcher
            for corpus, gold, queries in CASES:
                if corpus != name:
                    continue
                ranks = []
                for query in queries:
                    rows = asyncio.run(
                        searcher.hybrid_search_async(query, limit=10)
                    ) or []
                    rank = 0
                    for index, row in enumerate(rows, 1):
                        meta = row.get("metadata") or {}
                        path = str(meta.get("file") or row.get("file") or "")
                        if path.endswith(gold):
                            rank = index
                            break
                    ranks.append(rank or None)
                first_hits += bool(ranks[0])
                best_hits += bool([r for r in ranks if r])
                print(
                    f"  [{name}] gold={gold:<13} ranks={ranks} "
                    f"{queries[0][:38]!r}"
                )
        finally:
            shutdown = getattr(services, "shutdown", None)
            if callable(shutdown):
                try:
                    asyncio.run(shutdown())
                except Exception:
                    pass

    total = len(CASES)
    print(f"\nfirst translated query: top-10 hits {first_hits}/{total}")
    print(f"best of 3 retries     : top-10 hits {best_hits}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
