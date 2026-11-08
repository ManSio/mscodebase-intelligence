"""Does dense bridge a RUSSIAN question to ENGLISH code? (the actual no-id problem)

Full-corpus dense indexing was abandoned: the llama.cpp server answered 3 short
texts in 11.4 s (0.26 text/s, shared with the host), so 7 103 chunks would take
hours. This runs the same comparison on a 147-chunk corpus, where the question is
still the same one that matters: BM25 needs the query token in the text; a
multilingual embedding should not.

Gold files were read from the source: signer.py has `sep`, timed.py has
`expire`/`max_age`, url_safe.py has `base64`, _parse.py has `duplicate`,
__init__.py has `comment`/`strip`.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPOS = {
    "itsdangerous": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pallets__itsdangerous__HEAD-672971d"),
    "iniconfig": Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11\pytest-dev__iniconfig__HEAD-a9e0ad1"),
}
# Russian questions - the class BM25 failed on in our own corpus.
QUESTIONS = [
    ("itsdangerous", "Где подпись отделяется от полезной нагрузки?", "signer.py", "EN: how is the signature separated from the payload"),
    ("itsdangerous", "Что отвергает просроченную подпись?", "timed.py", "EN: what rejects an expired signature"),
    ("itsdangerous", "Где применяется url-safe base64?", "url_safe.py", "EN: where is url-safe base64 applied"),
    ("iniconfig", "Где отклоняются повторяющиеся секции?", "_parse.py", "EN: where are duplicate sections rejected"),
    ("iniconfig", "Как вырезается строчный комментарий из значения?", "__init__.py", "EN: how is an inline comment stripped"),
]


def main() -> int:
    dense = (sys.argv[1] if len(sys.argv) > 1 else "lexical") == "dense"
    os.environ["MSCODEBASE_DENSE_OFF"] = "false" if dense else "true"

    from src.core.di_container import (
        IndexerFactoryKey, ProjectIndexerRegistry, create_service_collection,
    )

    hits = 0
    for name, project in REPOS.items():
        services = create_service_collection(project)
        try:
            registry = services.resolve(ProjectIndexerRegistry)
            indexer = registry.get_indexer(project, factory=services.resolve(IndexerFactoryKey))
            if dense:
                from src.providers.embedder.remote_embedder import RemoteEmbedder
                embedder = services.resolve(RemoteEmbedder)
                with embedder._mode_lock:
                    embedder.mode = "llama_cpp"
                # Pin the dimension to what the server actually returns (checked
                # with a direct /v1/embeddings call: 768). The config path still
                # resolves 384 here, and an index built at 384 while the model
                # answers 768 is the failure this experiment is about.
                embedder.embedding_dim = int(os.getenv("AB_DIM", "768"))
                indexer.index_project(str(project))
                print(f"{name}: dense index ready (dim={embedder.embedding_dim})")
            searcher = indexer.searcher
            for corpus, question, gold, gloss in QUESTIONS:
                if corpus != name:
                    continue
                rows = asyncio.run(searcher.hybrid_search_async(question, limit=10)) or []
                rank, sources = 0, set()
                for i, row in enumerate(rows, 1):
                    sources.add(str(row.get("source")))
                    meta = row.get("metadata") or {}
                    path = str(meta.get("file") or row.get("file") or "")
                    if path.endswith(gold) and not rank:
                        rank = i
                hits += bool(rank)
                mode = "dense" if dense else "lexical"
                print(f"  [{mode}] {question[:44]:<44} gold={gold:<13} "
                      f"rank={rank or 'absent':<7} sources={sorted(sources)}")
        finally:
            sd = getattr(services, "shutdown", None)
            if callable(sd):
                try:
                    asyncio.run(sd())
                except Exception:
                    pass
    print(f"\n{'dense' if dense else 'lexical'}: top-10 hits {hits}/{len(QUESTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
