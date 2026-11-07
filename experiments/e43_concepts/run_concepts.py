"""E43: deterministic domain-concept tags as an extra retrieval signal."""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("MSCODEBASE_DENSE_OFF", "true")
os.environ.setdefault("MSCODEBASE_SQLITE_CHUNKS", "true")
os.environ.setdefault("MSCODEBASE_ONDEMAND_RERANK", "false")
os.environ.setdefault("MSCODEBASE_DEMOTE_NON_CODE", "true")
os.environ.setdefault("MSCODEBASE_P3_ANCHOR", "false")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = Path(__file__).resolve().parent / "frozen" / "QUERIES.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

CONCEPTS = {
    "auth": ["auth", "login", "session", "credential", "authorization",
             "authenticate", "авторизация", "аутентификация", "логин", "сессия",
             "токен", "доступ"],
    "cache": ["cache", "caching", "кэш", "кэширование", "кэшировать"],
    "database": ["database", "sqlite", "lancedb", "schema", "база", "данных"],
    "config": ["config", "configuration", "settings", "env", "конфиг", "настройка"],
    "error": ["error", "exception", "failure", "ошибка", "исключение", "сбой"],
    "rate_limit": ["rate limit", "rate_limiter", "throttle", "ограничитель",
                   "скорости", "лимит"],
    "graph": ["graph", "node", "edge", "caller", "callee", "граф", "узел",
              "ребро", "вызов"],
    "search": ["search", "retrieval", "hybrid", "bm25", "fts5", "rerank",
               "поиск", "поисковый", "реранкер"],
    "index": ["index", "indexing", "reindex", "индекс", "индексация",
              "переиндексация"],
    "memory": ["memory", "recall", "prompt", "context", "память", "контекст"],
    "concurrency": ["thread", "lock", "mutex", "async", "await", "race",
                    "поток", "блокировка", "мьютекс"],
    "network": ["http", "request", "response", "server", "client", "port",
                "network", "запрос", "ответ", "сервер", "клиент", "порт"],
    "file": ["file", "path", "module", "package", "файл", "путь", "модуль"],
    "test": ["test", "pytest", "тест", "проверка"],
    "process": ["process", "pid", "start", "stop", "процесс", "запуск"],
    "security": ["security", "secret", "redact", "trust", "credential",
                 "безопасность", "секрет", "доверие"],
}


class FakeIndexer:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.db_manager = None
        self.table = object()
        self._symbol_index = None


def hit_at(files, gold, k):
    return int(any(f == gold or f.endswith(gold) for f in files[:k]))


def mrr_at(files, gold):
    for i, f in enumerate(files, 1):
        if f == gold or f.endswith(gold):
            return 1.0 / i
    return 0.0


def _term_re(term: str):
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def build_concepts(store):
    rows = store.all_records()
    compiled = {
        c: [_term_re(t) for t in terms] for c, terms in CONCEPTS.items()
    }
    index = {c: [] for c in CONCEPTS}
    for row in rows:
        blob = " ".join(
            [
                str(row.get("symbol_name", "") or ""),
                str(row.get("file_path", "") or ""),
                str(row.get("text", "") or "")[:4000],
            ]
        )
        for concept, pats in compiled.items():
            n = sum(len(p.findall(blob)) for p in pats)
            if n:
                index[concept].append((n, row))
    for concept in index:
        index[concept].sort(key=lambda x: (-x[0], x[1].get("file_path", "")))
        index[concept] = [r for _, r in index[concept][:20]]
    return index


def query_concepts(query: str):
    q = query.lower()
    hits = []
    for concept, terms in CONCEPTS.items():
        if any(t.lower() in q for t in terms):
            hits.append(concept)
    return hits


def add_concept_candidates(pool, concept_index, query, factor):
    concepts = query_concepts(query)
    if not concepts or not pool:
        return
    base = max(float(r.get("final_score", 0.0) or 0.0) for r in pool)
    have = {
        (
            str((r.get("metadata") or {}).get("file", "")),
            int((r.get("metadata") or {}).get("chunk_index", 0) or 0),
        )
        for r in pool
    }
    for concept in concepts:
        for row in concept_index.get(concept, []):
            key = (str(row.get("file_path", "")), int(row.get("chunk_index", 0) or 0))
            if key in have:
                continue
            have.add(key)
            pool.append(
                {
                    "text": row.get("text", ""),
                    "text_full": row.get("text_full", row.get("text", "")),
                    "metadata": {
                        "file": row.get("file_path", ""),
                        "chunk_index": int(row.get("chunk_index", 0) or 0),
                        "symbol_name": row.get("symbol_name", ""),
                        "layer": row.get("layer", ""),
                        "start_line": row.get("start_line", 0),
                        "end_line": row.get("end_line", 0),
                        "concept": concept,
                    },
                    "final_score": base * factor,
                }
            )


async def run_arm(name, concept_factor, queries):
    from src.core.search.engine import Searcher

    searcher = Searcher(FakeIndexer(ROOT), None)
    searcher._ondemand_rerank = False
    searcher._multi_reranker_initialized = True
    searcher._multi_reranker = None
    searcher._demote_non_code = True
    searcher._p3_anchor = False
    concept_index = build_concepts(searcher._chunk_store) if concept_factor else {}

    async def one(q):
        t0 = time.perf_counter()
        pool = await searcher.hybrid_search_async(q["query"], limit=30)
        if concept_factor:
            add_concept_candidates(pool, concept_index, q["query"], concept_factor)
            pool.sort(
                key=lambda r: float(r.get("final_score", 0.0) or 0.0),
                reverse=True,
            )
        res = pool[:5]
        files = [(r.get("metadata") or {}).get("file", "") for r in res]
        return {
            "id": q["id"],
            "query": q["query"],
            "gold": q["gold_file"],
            "files": files,
            "ms": (time.perf_counter() - t0) * 1000,
            "h1": hit_at(files, q["gold_file"], 1),
            "h5": hit_at(files, q["gold_file"], 5),
            "rr": mrr_at(files, q["gold_file"]),
        }

    await one(queries[0])
    rows = [await one(q) for q in queries]
    await searcher.close()

    lat = sorted(r["ms"] for r in rows)
    summary = {
        "arm": name,
        "concept_factor": concept_factor,
        "n": len(rows),
        "hit1": sum(r["h1"] for r in rows) / len(rows),
        "hit5": sum(r["h5"] for r in rows) / len(rows),
        "mrr": sum(r["rr"] for r in rows) / len(rows),
        "p50_ms": statistics.median(lat),
        "p95_ms": lat[int(len(lat) * 0.95) - 1],
        "mean_ms": sum(lat) / len(lat),
        "rows": rows,
    }
    (RESULTS / f"{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:<12} h1={summary['hit1']:.3f} h5={summary['hit5']:.3f} "
        f"mrr={summary['mrr']:.3f} p50={summary['p50_ms']:.0f}ms "
        f"p95={summary['p95_ms']:.0f}ms"
    )
    return summary


async def main():
    queries = [
        json.loads(line)
        for line in FROZEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not queries:
        print("FATAL: empty query set", file=sys.stderr)
        return 2
    await run_arm("baseline", 0.0, queries)
    await run_arm("concept_09", 0.9, queries)
    await run_arm("concept_11", 1.1, queries)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
