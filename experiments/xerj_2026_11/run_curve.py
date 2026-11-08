"""Dependency curves: recall vs k, split by identifier presence, query language, corpus.

Why: each previous experiment answered one question on one corpus. This one asks
what the numbers depend on - with 70+ queries over 3 projects of very different
size (5, 15 and 523 files), in Russian and English, with and without an explicit
identifier.

Arms:
  search  - `searcher.hybrid_search_async` (the semantic/BM25 channel, wide limit)
  grep    - exact identifier matches over the same tree (the "plain tools" arm)

Output: recall@1/3/5/10/20 per group + the raw rows in curves.json.
Run: python experiments/xerj_2026_11/run_curve.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

OUT = HERE / "curves.json"
WIDE = 40
KS = (1, 3, 5, 10, 20)

# Positive identifiers from the frozen set (gold file per symbol).
OURS_ID = [
    ("build_call_graph", "src/core/indexing/symbol_index.py"),
    ("get_impact_analysis", "src/core/graph_rag.py"),
    ("ModificationGuard", None),  # invalid gold, kept to show the dependency
    ("FreshnessChecker", "src/core/indexing/freshness.py"),
    ("get_progress_file", "src/core/artifact_paths.py"),
    ("ModificationToken", "src/core/modification_guard.py"),
    ("SymbolIndexAdapter", "src/core/search/graph_adapter.py"),
    ("index_guard", "src/core/indexing/index_guard.py"),
    ("ModificationGuard", None),
]
# natural-language questions without an identifier (gold from the frozen E1 set)
OURS_NL = [
    ("Где решается, нужно ли переиндексировать файл?", "src/core/indexing/freshness.py",
     "Where is the decision made whether a file must be reindexed?",),
    ("Какая функция возвращает путь прогресса?", "src/core/artifact_paths.py",
     "Which function returns the progress file path?",),
    ("Какой документ является каноном публичных чисел?", "docs/FACTS.md",
     "Which document is the canon of published numbers?",),
    ("Где LSP-инструмент отправляет за ссылками?", "src/mcp/tools/lsp_tools.py",
     "Where does the LSP tool send the user for references?",),
]
EXT_ID = [
    ("Signer", "src/itsdangerous/signer.py"),
    ("TimestampSigner", "src/itsdangerous/timed.py"),
    ("Serializer", "src/itsdangerous/serializer.py"),
    ("URLSafeSerializer", "src/itsdangerous/url_safe.py"),
    ("BadSignature", "src/itsdangerous/exc.py"),
    ("want_bytes", "src/itsdangerous/encoding.py"),
    ("IniConfig", "src/iniconfig/__init__.py"),
    ("ParseError", "src/iniconfig/exceptions.py"),
    ("SectionWrapper", "src/iniconfig/__init__.py"),
]

RU_DEF = "Где определяется `{x}`?"
EN_DEF = "Where is `{x}` defined?"


def tasks() -> list[dict]:
    out = []
    for symbol, gold in OURS_ID:
        if not gold:
            continue
        out.append({"corpus": "ours", "lang": "en", "has_id": True, "id": symbol,
                    "q": EN_DEF.format(x=symbol), "gold": gold})
        out.append({"corpus": "ours", "lang": "ru", "has_id": True, "id": symbol,
                    "q": RU_DEF.format(x=symbol), "gold": gold})
    for ru, gold, en in OURS_NL:
        out.append({"corpus": "ours", "lang": "ru", "has_id": False, "id": gold.split("/")[-1],
                    "q": ru, "gold": gold})
        out.append({"corpus": "ours", "lang": "en", "has_id": False, "id": gold.split("/")[-1],
                    "q": en, "gold": gold})
    for symbol, gold in EXT_ID:
        corpus = "itsdangerous" if "itsdangerous" in gold else "iniconfig"
        out.append({"corpus": corpus, "lang": "en", "has_id": True, "id": symbol,
                    "q": EN_DEF.format(x=symbol), "gold": gold})
        out.append({"corpus": corpus, "lang": "ru", "has_id": True, "id": symbol,
                    "q": RU_DEF.format(x=symbol), "gold": gold})
    return out


def grep_rank(root: Path, query: str, gold: str) -> int:
    """Rank of `gold` among files containing the identifier, walk order."""
    tokens = re.findall(r"`([^`]+)`", query)[:2]
    if not tokens:
        words = [w for w in re.findall(r"[A-Za-zА-Яа-я_-]{5,}", query)][:3]
        tokens = words
    if not tokens:
        return 0
    patterns = [re.compile(re.escape(t).encode("utf-8")) for t in tokens]
    from src.core.indexing.file_guard import FileGuard

    guard = FileGuard(root)
    rank = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and not guard.should_skip_dir(d))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if guard.should_skip_file(path) or path.suffix not in (".py", ".md"):
                continue
            try:
                source = path.read_bytes()
            except OSError:
                continue
            if not any(p.search(source) for p in patterns):
                continue
            rank += 1
            if path.as_posix().endswith(gold):
                return rank
            if rank >= WIDE:
                return 0
    return 0


def main() -> int:
    from src.core.di_container import (  # noqa: E402
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )

    corpora = {
        "ours": ROOT,
        "itsdangerous": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d"),
        "iniconfig": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1"),
    }
    services = create_service_collection(ROOT)
    registry = services.resolve(ProjectIndexerRegistry)
    factory = services.resolve(IndexerFactoryKey)
    rows = []
    try:
        searchers = {}
        for name, path in corpora.items():
            indexer = registry.get_indexer(path, factory=factory)
            searchers[name] = (indexer.searcher, path)

        for task in tasks():
            searcher, path = searchers[task["corpus"]]
            raw = asyncio.run(searcher.hybrid_search_async(task["q"], limit=WIDE)) or []
            rank = 0
            for i, row in enumerate(raw, 1):
                meta = row.get("metadata") or {}
                file_path = str(meta.get("file") or row.get("file") or "").replace("\\", "/")
                if file_path.endswith(task["gold"]):
                    rank = i
                    break
            g_rank = grep_rank(path, task["q"], task["gold"])
            rows.append({**task, "search_rank": rank, "grep_rank": g_rank,
                         "search_rows": len(raw)})
            print(f"{task['corpus']:<12} {task['lang']} id={int(task['has_id'])} "
                  f"{task['id'][:24]:<24} search={rank or 'absent'} grep={g_rank or 'absent'}")
    finally:
        sd = getattr(services, "shutdown", None)
        if callable(sd):
            try:
                asyncio.run(sd())
            except Exception:
                pass

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8", newline="")

    print("\n=== recall@k (rank<=k) by group")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        for key in (f"{row['corpus']}",
                    f"lang={row['lang']}",
                    f"has_id={row['has_id']}",
                    f"corpus={row['corpus']},lang={row['lang']}"):
            groups.setdefault(key, []).append(row)
    print(f"{'group':<26} {'n':>3} " + " ".join(f"@{k:<4}" for k in KS) + "  grep@10")
    for name in sorted(groups):
        group = groups[name]
        cells = []
        for k in KS:
            cells.append(f"{sum(1 for r in group if 0 < r['search_rank'] <= k) / len(group):.3f}")
        g10 = sum(1 for r in group if 0 < r["grep_rank"] <= 10) / len(group)
        print(f"{name:<26} {len(group):>3} " + " ".join(f"{c:<5}" for c in cells) + f"  {g10:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
