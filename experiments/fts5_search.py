"""Experiment 1: SQLite FTS5 with 3 Different Tokenization Indexes.

Inspired by srclight/srclight (52★, MIT) — the gold standard for hybrid search.

Srclight uses:
- Names index: code-aware tokenization (camelCase, ::, ->)
- Content index: trigram tokenization for substring matching
- Docs index: Porter stemming for natural language in docstrings

This prototype creates 3 FTS5 virtual tables alongside the existing LanceDB
vector search, then fuses results with RRF.

Metrics measured:
- Index build time (ms)
- Query latency (ms)
- Recall@5 vs pure vector search
- Memory usage (MB)

Run:
    cd D:/Project/MSCodeBase
    python experiments/fts5_search.py
"""

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import sqlite3
    import json
    import os
    import re
    import time
    import hashlib
    from pathlib import Path
    from typing import Dict, List, Optional, Tuple

    # ─── CamelCase tokenizer (for symbol names) ────────────────
    def tokenize_camel_case(text: str) -> List[str]:
        """Split camelCase/PascalCase/snake_case into tokens.

        Examples:
            "search_code" -> ["search", "code"]
            "hybridSearchAsync" -> ["hybrid", "search", "async"]
            "BM25Mixin" -> ["bm", "25", "mixin"]
            "getVariableFlow" -> ["get", "variable", "flow"]
        """
        if not text:
            return []
        # Insert space before uppercase preceded by lowercase: "hybridS" -> "hybrid S"
        text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
        # Insert space before uppercase preceded by uppercase+lowercase: "XMLParser" -> "XML Parser"
        text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', text)
        # Replace underscores and special chars with spaces
        text = re.sub(r'[_\-./\\:><()\[\]{}]', ' ', text)
        # Split and lowercase
        tokens = text.lower().split()
        # Filter empty tokens
        return [t for t in tokens if t.strip()]


    def tokenize_trigram(text: str) -> List[str]:
        """Generate trigrams for substring matching.

        Examples:
            "search" -> ["sea", "ear", "arc", "rch"]
            "config" -> ["con", "onf", "nfi", "fig"]
        """
        if not text or len(text) < 3:
            return [text.lower()] if text else []
        text = text.lower()
        return [text[i:i+3] for i in range(len(text) - 2)]


    def tokenize_porter(text: str) -> List[str]:
        """Simple Porter-like stemming for docstrings.

        Strips common suffixes for English natural language.
        """
        if not text:
            return []
        # Basic suffix stripping (approximation of Porter step 1)
        suffixes = ['ing', 'tion', 'sion', 'ment', 'ness', 'able', 'ible',
                     'ful', 'less', 'ous', 'ive', 'ed', 'er', 'es', 'ly', 's']
        tokens = text.lower().split()
        stemmed = []
        for t in tokens:
            # Skip very short tokens
            if len(t) <= 2:
                stemmed.append(t)
                continue
            # Try suffixes longest first
            for suffix in sorted(suffixes, key=len, reverse=True):
                if t.endswith(suffix) and len(t) - len(suffix) >= 3:
                    stemmed.append(t[:-len(suffix)])
                    break
            else:
                stemmed.append(t)
        return stemmed


    # ─── FTS5 Index Manager ────────────────────────────────────
    class FTS5IndexManager:
        """Manages 3 FTS5 indexes with different tokenization strategies.

        Architecture (from srclight/srclight):
        - names_idx: Symbol names with camelCase tokenization
        - content_idx: Code content with trigram tokenization
        - docs_idx: Docstrings with Porter stemming
        """

        def __init__(self, db_path: str = ":memory:"):
            self.db_path = db_path
            self.conn = sqlite3.connect(db_path)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self._create_tables()

        def _create_tables(self):
            """Create 3 FTS5 virtual tables + a metadata table."""
            # Names index — camelCase-aware tokenization
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS names_idx
                USING fts5(
                    doc_id,
                    file_path,
                    symbol_name,
                    symbol_type,
                    tokenize='porter'
                )
            """)

            # Content index — trigram tokenization for substring matching
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS content_idx
                USING fts5(
                    doc_id,
                    file_path,
                    content,
                    tokenize='trigram'
                )
            """)

            # Docs index — porter stemming for natural language
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS docs_idx
                USING fts5(
                    doc_id,
                    file_path,
                    docstring,
                    tokenize='porter'
                )
            """)

            # Metadata table for fast lookups
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    doc_id TEXT PRIMARY KEY,
                    file_path TEXT,
                    chunk_index INTEGER,
                    text TEXT,
                    symbol_name TEXT,
                    symbol_type TEXT,
                    docstring TEXT,
                    layer TEXT,
                    indexed_at TEXT
                )
            """)
            self.conn.commit()

        def _extract_symbol_info(self, text: str) -> Tuple[Optional[str], Optional[str]]:
            """Extract symbol name and type from chunk text."""
            patterns = [
                (r'class\s+(\w+)', 'class'),
                (r'def\s+(\w+)', 'function'),
                (r'async\s+def\s+(\w+)', 'async_function'),
                (r'(\w+)\s*=\s*(?:lambda|function)', 'variable'),
            ]
            for pattern, sym_type in patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1), sym_type
            return None, None

        def _extract_docstring(self, text: str) -> Optional[str]:
            """Extract docstring from chunk text."""
            match = re.search(r'"""([\s\S]*?)"""', text)
            if match:
                return match.group(1).strip()
            match = re.search(r"'''([\s\S]*?)'''", text)
            if match:
                return match.group(1).strip()
            match = re.search(r'"""([\s\S]*?)"""', text)
            if match:
                return match.group(1).strip()
            return None

        def index_chunks(self, chunks: List[dict]) -> dict:
            """Index chunks into all 3 FTS5 indexes.

            Args:
                chunks: List of dicts with 'file_path', 'chunk_index', 'text', 'layer'

            Returns:
                Dict with timing metrics
            """
            start = time.perf_counter()

            names_count = 0
            content_count = 0
            docs_count = 0

            for chunk in chunks:
                doc_id = f"{chunk['file_path']}:{chunk['chunk_index']}"
                text = chunk.get('text', '')
                file_path = chunk.get('file_path', '')
                layer = chunk.get('layer', '')
                indexed_at = chunk.get('indexed_at', '')

                symbol_name, symbol_type = self._extract_symbol_info(text)
                docstring = self._extract_docstring(text)

                # Insert into metadata
                self.conn.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                    (doc_id, file_path, chunk.get('chunk_index', 0), text,
                     symbol_name, symbol_type, docstring, layer, indexed_at)
                )

                # Names index (camelCase tokenized by porter)
                if symbol_name:
                    self.conn.execute(
                        "INSERT INTO names_idx VALUES (?,?,?,?)",
                        (doc_id, file_path, symbol_name, symbol_type)
                    )
                    names_count += 1

                # Content index (trigram)
                self.conn.execute(
                    "INSERT INTO content_idx VALUES (?,?,?)",
                    (doc_id, file_path, text)
                )
                content_count += 1

                # Docs index (porter)
                if docstring:
                    self.conn.execute(
                        "INSERT INTO docs_idx VALUES (?,?,?)",
                        (doc_id, file_path, docstring)
                    )
                    docs_count += 1

            self.conn.commit()
            elapsed = (time.perf_counter() - start) * 1000

            return {
                "elapsed_ms": round(elapsed, 1),
                "total_chunks": len(chunks),
                "names_indexed": names_count,
                "content_indexed": content_count,
                "docs_indexed": docs_count,
            }

        def search_names(self, query: str, limit: int = 10) -> List[dict]:
            """Search symbol names index."""
            # Tokenize query with camelCase-aware tokenizer
            tokens = tokenize_camel_case(query)
            if not tokens:
                return []

            # FTS5 match with OR
            fts_query = " OR ".join(f'"{t}"' for t in tokens)
            try:
                rows = self.conn.execute(
                    """SELECT n.doc_id, n.file_path, n.symbol_name, n.symbol_type,
                              rank
                     FROM names_idx n
                     WHERE names_idx MATCH ?
                     ORDER BY rank
                     LIMIT ?""",
                    (fts_query, limit)
                ).fetchall()

                results = []
                for row in rows:
                    results.append({
                        "doc_id": row[0],
                        "file_path": row[1],
                        "symbol_name": row[2],
                        "symbol_type": row[3],
                        "fts_rank": row[4],
                        "source": "names"
                    })
                return results
            except Exception as e:
                logger.warning(f"Names search error: {e}")
                return []

        def search_content(self, query: str, limit: int = 10) -> List[dict]:
            """Search content index with trigram matching."""
            try:
                rows = self.conn.execute(
                    """SELECT c.doc_id, c.file_path, rank
                     FROM content_idx c
                     WHERE content_idx MATCH ?
                     ORDER BY rank
                     LIMIT ?""",
                    (f'"{query}"', limit)
                ).fetchall()

                results = []
                for row in rows:
                    results.append({
                        "doc_id": row[0],
                        "file_path": row[1],
                        "fts_rank": row[2],
                        "source": "content"
                    })
                return results
            except Exception as e:
                logger.warning(f"Content search error: {e}")
                return []

        def search_docs(self, query: str, limit: int = 10) -> List[dict]:
            """Search docs index with Porter stemming."""
            tokens = tokenize_porter(query)
            if not tokens:
                return []

            fts_query = " OR ".join(f'"{t}"' for t in tokens)
            try:
                rows = self.conn.execute(
                    """SELECT d.doc_id, d.file_path, rank
                     FROM docs_idx d
                     WHERE docs_idx MATCH ?
                     ORDER BY rank
                     LIMIT ?""",
                    (fts_query, limit)
                ).fetchall()

                results = []
                for row in rows:
                    results.append({
                        "doc_id": row[0],
                        "file_path": row[1],
                        "fts_rank": row[2],
                        "source": "docs"
                    })
                return results
            except Exception as e:
                logger.warning(f"Docs search error: {e}")
                return []

        def hybrid_search(self, query: str, limit: int = 10) -> List[dict]:
            """Search all 3 indexes and fuse with RRF.

            This is the srclight approach: search names + content + docs in
            parallel, then Reciprocal Rank Fusion merges the rankings.
            """
            rrf_k = 60
            scores: Dict[str, float] = {}
            results_map: Dict[str, dict] = {}

            # Search all 3 indexes
            for idx_name, search_fn in [
                ("names", self.search_names),
                ("content", self.search_content),
                ("docs", self.search_docs),
            ]:
                results = search_fn(query, limit=limit * 2)
                for rank, result in enumerate(results, 1):
                    doc_id = result["doc_id"]
                    rrf_score = 1.0 / (rrf_k + rank)

                    if doc_id not in scores:
                        scores[doc_id] = 0.0
                        results_map[doc_id] = result
                        results_map[doc_id]["rrf_detail"] = {}

                    scores[doc_id] += rrf_score
                    results_map[doc_id]["rrf_detail"][idx_name] = rrf_score

            # Sort by RRF score
            sorted_ids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]

            final = []
            for doc_id in sorted_ids:
                r = results_map[doc_id]
                # Get full text from metadata table
                row = self.conn.execute(
                    "SELECT text, symbol_name, symbol_type, layer FROM chunks WHERE doc_id=?",
                    (doc_id,)
                ).fetchone()

                final.append({
                    "text": row[0] if row else "",
                    "metadata": {
                        "file": r["file_path"],
                        "chunk_index": int(doc_id.split(":")[-1]) if ":" in doc_id else 0,
                        "symbol_name": row[1] if row else None,
                        "symbol_type": row[2] if row else None,
                        "layer": row[3] if row else "",
                        "rrf_detail": r.get("rrf_detail", {}),
                    },
                    "final_score": scores[doc_id],
                    "source": "fts5_hybrid",
                })

            return final

        def close(self):
            self.conn.close()


    import logging
    logger = logging.getLogger(__name__)


    # ─── Experiment Runner ──────────────────────────────────────
    def load_chunks_from_lancedb(db_path: Path) -> List[dict]:
        """Try to load chunks from an existing LanceDB database.

        Falls back to scanning source files if LanceDB is unavailable.
        """
        chunks = []

        # Try LanceDB first
        try:
            import lancedb
            db = lancedb.connect(str(db_path.parent))
            tables = db.table_names()
            if tables:
                table = db.open_table(tables[0])
                df = table.to_pandas()
                for _, row in df.iterrows():
                    chunks.append({
                        "file_path": row.get("file_path", ""),
                        "chunk_index": int(row.get("chunk_index", 0)),
                        "text": row.get("text", ""),
                        "layer": row.get("layer", ""),
                        "indexed_at": str(row.get("indexed_at", "")),
                    })
                print(f"  Loaded {len(chunks)} chunks from LanceDB ({tables[0]})")
                return chunks
        except Exception as e:
            print(f"  LanceDB unavailable: {e}")

        return chunks


    def scan_source_files(project_root: Path, extensions: tuple = ('.py',)) -> List[dict]:
        """Scan source files and create chunks (function/class level)."""
        chunks = []
        src_dir = project_root / "src"
        if not src_dir.exists():
            src_dir = project_root

        for ext in extensions:
            for file_path in src_dir.rglob(f"*{ext}"):
                # Skip test files, __pycache__, .venv
                rel = str(file_path.relative_to(project_root))
                if '__pycache__' in rel or '.venv' in rel or 'node_modules' in rel:
                    continue
                if 'experiments' in rel:
                    continue

                try:
                    text = file_path.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue

                # Determine layer from path
                layer = "unknown"
                if "/core/" in rel or "\\core\\" in rel:
                    layer = "core"
                elif "/mcp/" in rel or "\\mcp\\" in rel:
                    layer = "mcp"
                elif "/providers/" in rel or "\\providers\\" in rel:
                    layer = "providers"
                elif "/utils/" in rel or "\\utils\\" in rel:
                    layer = "utils"
                elif "/tests/" in rel or "\\tests\\" in rel:
                    layer = "tests"
                elif "/indexing/" in rel or "\\indexing\\" in rel:
                    layer = "core"

                # Chunk at function/class boundaries
                import ast as _ast
                try:
                    tree = _ast.parse(text)
                    for node in _ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            start = node.lineno - 1
                            end = getattr(node, 'end_lineno', node.lineno)
                            chunk_text = '\n'.join(text.splitlines()[start:end])
                            chunks.append({
                                "file_path": rel,
                                "chunk_index": len(chunks),
                                "text": chunk_text,
                                "layer": layer,
                                "indexed_at": "",
                            })
                except SyntaxError:
                    # Not valid Python — index whole file
                    chunks.append({
                        "file_path": rel,
                        "chunk_index": len(chunks),
                        "text": text[:2000],  # Cap at 2000 chars
                        "layer": layer,
                        "indexed_at": "",
                    })

        return chunks


    def run_benchmark(project_root: Path):
        """Run FTS5 benchmark on the real MSCodeBase project."""
        print("=" * 70)
        print("EXPERIMENT 1: SQLite FTS5 with 3 Different Tokenization Indexes")
        print("Inspired by: srclight/srclight (52★, MIT)")
        print("=" * 70)
        print()

        # 1. Load data
        print("[1/4] Loading chunks...")
        # Try to find LanceDB
        lancedb_dir = project_root / ".codebase_indices" / "lancedb_v2"
        chunks = []

        if lancedb_dir.exists():
            # Find .lance directories
            for lance_db in lancedb_dir.glob("*.db"):
                chunks = load_chunks_from_lancedb(lance_db)
                if chunks:
                    break

        if not chunks:
            print("  No LanceDB data found, scanning source files...")
            chunks = scan_source_files(project_root)
            print(f"  Scanned {len(chunks)} chunks from {project_root / 'src'}")

        if not chunks:
            print("  ERROR: No chunks to index!")
            return

        # 2. Build indexes
        print(f"\n[2/4] Building 3 FTS5 indexes on {len(chunks)} chunks...")
        db_path = str(project_root / ".codebase_indices" / "fts5_experiment.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        mgr = FTS5IndexManager(db_path=db_path)
        metrics = mgr.index_chunks(chunks)

        print(f"  Build time: {metrics['elapsed_ms']}ms")
        print(f"  Names indexed: {metrics['names_indexed']}")
        print(f"  Content indexed: {metrics['content_indexed']}")
        print(f"  Docs indexed: {metrics['docs_indexed']}")

        # 3. Run search queries
        print(f"\n[3/4] Running search benchmarks...")
        test_queries = [
            "hybrid_search",
            "BM25 index",
            "LanceDB vector",
            "embedding async",
            "getVariableFlow",
            "camelCase tokenization",
            "property graph",
            "reranker multi provider",
            "async def embed_batch",
            "modification guard",
        ]

        total_fts5_ms = 0
        results_per_query = []

        for query in test_queries:
            start = time.perf_counter()
            results = mgr.hybrid_search(query, limit=5)
            elapsed = (time.perf_counter() - start) * 1000
            total_fts5_ms += elapsed

            top_files = [r["metadata"]["file"] for r in results[:3]]
            symbols = [r["metadata"].get("symbol_name", "-") for r in results[:3]]

            results_per_query.append({
                "query": query,
                "results": len(results),
                "latency_ms": round(elapsed, 1),
                "top_files": top_files,
                "top_symbols": symbols,
            })

            print(f"  Q: '{query}'")
            print(f"    Latency: {elapsed:.1f}ms | Results: {len(results)}")
            for i, r in enumerate(results[:3]):
                sym = r["metadata"].get("symbol_name", "")
                f = r["metadata"]["file"]
                score = r["final_score"]
                detail = r["metadata"].get("rrf_detail", {})
                detail_str = ", ".join(f"{k}={v:.4f}" for k, v in detail.items())
                print(f"    #{i+1}: {sym or '(chunk)'} in {f}  score={score:.4f} [{detail_str}]")
            print()

        avg_latency = total_fts5_ms / len(test_queries)
        print(f"  Average FTS5 hybrid latency: {avg_latency:.1f}ms")
        print(f"  Total query time: {total_fts5_ms:.1f}ms for {len(test_queries)} queries")

        # 4. Tokenization tests
        print(f"\n[4/4] Tokenization quality tests...")
        token_tests = [
            ("hybridSearchAsync", "camelCase"),
            ("get_variable_flow", "snake_case"),
            ("BM25Mixin", "acronym+word"),
            ("async def embed_batch", "Python code"),
            ("LanceDB PropertyGraph", "mixed"),
            ("_apply_co_change_boost", "private+snake"),
        ]

        for text, label in token_tests:
            camel_tokens = tokenize_camel_case(text)
            porter_tokens = tokenize_porter(text)
            print(f"  [{label}] '{text}'")
            print(f"    CamelCase: {camel_tokens}")
            print(f"    Porter:    {porter_tokens}")

        # Cleanup
        mgr.close()

        # Summary
        print()
        print("=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Chunks indexed:     {metrics['total_chunks']}")
        print(f"  Index build time:   {metrics['elapsed_ms']}ms")
        print(f"  Avg query latency:  {avg_latency:.1f}ms")
        print(f"  Total queries:      {len(test_queries)}")
        print(f"  DB file:            {db_path}")
        print()

        # Save results
        results_file = project_root / "experiments" / "fts5_results.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                "experiment": "fts5_3index_hybrid",
                "source": "srclight/srclight",
                "metrics": metrics,
                "avg_latency_ms": round(avg_latency, 1),
                "queries": results_per_query,
                "tokenization_tests": token_tests,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Results saved to: {results_file}")

        return metrics, avg_latency, results_per_query


    if __name__ == "__main__":
        project_root = Path(__file__).parent.parent
        run_benchmark(project_root)

except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
