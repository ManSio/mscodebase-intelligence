"""REAL Experiment: FTS5 3-Index vs Keyword Search on MSCodeBase source code.

NO LanceDB dependency — works on raw .py files.
Tests the srclight approach with REAL project data.

Metrics:
- Index build time
- Query latency per search type
- Result quality (manual relevance judgment)
- Memory usage
"""

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import sqlite3
    import re
    import time
    import ast
    import json
    import os
    from pathlib import Path
    from collections import defaultdict

    PROJECT = Path(__file__).resolve().parent.parent

    # ════════════════════════════════════════════════════════════════
    #  STEP 1: Scan source files → chunks (function/class level)
    # ════════════════════════════════════════════════════════════════

    def scan_project(src_dir: Path):
        """Scan Python files and extract function/class chunks."""
        chunks = []
        files_scanned = 0

        for py_file in src_dir.rglob("*.py"):
            rel = str(py_file.relative_to(PROJECT))
            if '__pycache__' in rel or 'experiments' in rel or '.venv' in rel:
                continue

            try:
                source = py_file.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            files_scanned += 1

            # Determine layer
            layer = "unknown"
            for name in ['core', 'mcp', 'providers', 'utils', 'tests', 'config', 'indexing']:
                if f'\\{name}\\' in rel or f'/{name}/' in rel:
                    layer = name
                    break

            # Parse with Python ast
            try:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        start = node.lineno - 1
                        end = getattr(node, 'end_lineno', node.lineno)
                        chunk_lines = source.splitlines()[start:end]
                        chunk_text = '\n'.join(chunk_lines)

                        # Extract docstring
                        docstring = ast.get_docstring(node) or ""

                        # Extract decorators
                        decorators = []
                        for dec in node.decorator_list:
                            if isinstance(dec, ast.Name):
                                decorators.append(dec.id)
                            elif isinstance(dec, ast.Attribute):
                                decorators.append(dec.attr)

                        kind = 'class' if isinstance(node, ast.ClassDef) else 'function'
                        if isinstance(node, ast.AsyncFunctionDef):
                            kind = 'async_function'

                        chunks.append({
                            'file_path': rel,
                            'chunk_index': len(chunks),
                            'text': chunk_text,
                            'symbol_name': node.name,
                            'symbol_kind': kind,
                            'docstring': docstring,
                            'decorators': decorators,
                            'line_start': node.lineno,
                            'line_end': end,
                            'layer': layer,
                        })
            except SyntaxError:
                chunks.append({
                    'file_path': rel,
                    'chunk_index': len(chunks),
                    'text': source[:3000],
                    'symbol_name': Path(rel).stem,
                    'symbol_kind': 'file',
                    'docstring': '',
                    'decorators': [],
                    'line_start': 1,
                    'line_end': len(source.splitlines()),
                    'layer': layer,
                })

        return chunks, files_scanned

    # ════════════════════════════════════════════════════════════════
    #  STEP 2: srclight's split_identifier() — exact copy
    # ════════════════════════════════════════════════════════════════

    def split_identifier(name: str) -> str:
        """Exact copy of srclight's split_identifier() from db.py"""
        if not name:
            return ""
        parts = re.split(r"::|->|\.", name)
        tokens = []
        for part in parts:
            sub_parts = part.split("_")
            for sp in sub_parts:
                if not sp:
                    continue
                s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", sp)
                s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
                camel_parts = s.split()
                tokens.extend(p for p in camel_parts if p)
        result_parts = []
        for t in tokens:
            result_parts.append(t)
        lower_parts = [t.lower() for t in tokens if t.lower() != t]
        result_parts.extend(lower_parts)
        return " ".join(result_parts)

    # ════════════════════════════════════════════════════════════════
    #  STEP 3: FTS5 3-Index Manager
    # ════════════════════════════════════════════════════════════════

    class FTS5Experiment:
        """srclight-style 3 FTS5 indexes on MSCodeBase data."""

        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.execute("PRAGMA journal_mode=OFF")
            self._create_indexes()

        def _create_indexes(self):
            # Tier 1: Names (porter — preprocess with split_identifier)
            self.conn.execute("""
                CREATE VIRTUAL TABLE names_fts USING fts5(
                    symbol_name, name_tokens, symbol_kind, file_path,
                    tokenize='porter'
                )
            """)
            # Tier 2: Content (trigram — substring matching)
            self.conn.execute("""
                CREATE VIRTUAL TABLE content_fts USING fts5(
                    chunk_text, file_path, symbol_name,
                    tokenize='trigram'
                )
            """)
            # Tier 3: Docs (porter unicode61 — natural language)
            self.conn.execute("""
                CREATE VIRTUAL TABLE docs_fts USING fts5(
                    docstring, file_path, symbol_name,
                    tokenize='porter unicode61'
                )
            """)
            # Metadata table
            self.conn.execute("""
                CREATE TABLE chunks (
                    chunk_id INTEGER PRIMARY KEY,
                    file_path TEXT, chunk_index INTEGER, text TEXT,
                    symbol_name TEXT, symbol_kind TEXT, docstring TEXT,
                    layer TEXT, line_start INTEGER, line_end INTEGER
                )
            """)
            self.conn.commit()

        def index(self, chunks):
            """Index all chunks into 3 FTS5 tables."""
            t0 = time.perf_counter()
            n_names = n_content = n_docs = 0

            for ch in chunks:
                cid = ch['chunk_index']
                # Metadata
                self.conn.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (cid, ch['file_path'], ch['chunk_index'], ch['text'],
                     ch['symbol_name'], ch['symbol_kind'], ch['docstring'],
                     ch['layer'], ch['line_start'], ch['line_end'])
                )

                # Tier 1: Names
                name_tokens = split_identifier(ch['symbol_name'])
                if name_tokens.strip():
                    self.conn.execute(
                        "INSERT INTO names_fts VALUES (?,?,?,?)",
                        (ch['symbol_name'], name_tokens, ch['symbol_kind'], ch['file_path'])
                    )
                    n_names += 1

                # Tier 2: Content (trigram)
                self.conn.execute(
                    "INSERT INTO content_fts VALUES (?,?,?)",
                    (ch['text'], ch['file_path'], ch['symbol_name'])
                )
                n_content += 1

                # Tier 3: Docs
                if ch['docstring'].strip():
                    self.conn.execute(
                        "INSERT INTO docs_fts VALUES (?,?,?)",
                        (ch['docstring'], ch['file_path'], ch['symbol_name'])
                    )
                    n_docs += 1

            self.conn.commit()
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                'build_ms': round(elapsed, 1),
                'names': n_names,
                'content': n_content,
                'docs': n_docs,
                'total_chunks': len(chunks),
            }

        def search_tier1_names(self, query, limit=10):
            """Tier 1: Search symbol names with srclight tokenization."""
            tokens = split_identifier(query)
            if not tokens.strip():
                return []
            # FTS5 OR query
            terms = tokens.split()
            fts_q = " OR ".join(f'"{t}"' for t in terms)
            try:
                rows = self.conn.execute(
                    """SELECT symbol_name, file_path, rank FROM names_fts
                       WHERE names_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (fts_q, limit)
                ).fetchall()
                return [{'name': r[0], 'file': r[1], 'rank': r[2], 'tier': 'names'} for r in rows]
            except Exception:
                return []

        def search_tier2_content(self, query, limit=10):
            """Tier 2: Trigram substring search."""
            try:
                rows = self.conn.execute(
                    """SELECT symbol_name, file_path, rank FROM content_fts
                       WHERE content_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (f'"{query}"', limit)
                ).fetchall()
                return [{'name': r[0], 'file': r[1], 'rank': r[2], 'tier': 'content'} for r in rows]
            except Exception:
                return []

        def search_tier3_docs(self, query, limit=10):
            """Tier 3: Porter stemmed docstring search."""
            try:
                rows = self.conn.execute(
                    """SELECT symbol_name, file_path, rank FROM docs_fts
                       WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (f'"{query}"', limit)
                ).fetchall()
                return [{'name': r[0], 'file': r[1], 'rank': r[2], 'tier': 'docs'} for r in rows]
            except Exception:
                return []

        def hybrid_search(self, query, limit=5):
            """4-tier srclight hybrid: names + LIKE + content + docs → RRF merge."""
            rrf_k = 60
            scores = {}
            data = {}

            # Tier 1: Names (FTS5 porter)
            for rank, r in enumerate(self.search_tier1_names(query, limit=20)):
                sid = f"{r['name']}:{r['file']}"
                scores[sid] = scores.get(sid, 0.0) + 1.0 / (rrf_k + rank + 1)
                data[sid] = r

            # Tier 2: Content (trigram)
            for rank, r in enumerate(self.search_tier2_content(query, limit=20)):
                sid = f"{r['name']}:{r['file']}"
                scores[sid] = scores.get(sid, 0.0) + 1.0 / (rrf_k + rank + 1)
                if sid not in data:
                    data[sid] = r

            # Tier 3: Docs (porter)
            for rank, r in enumerate(self.search_tier3_docs(query, limit=20)):
                sid = f"{r['name']}:{r['file']}"
                scores[sid] = scores.get(sid, 0.0) + 1.0 / (rrf_k + rank + 1)
                if sid not in data:
                    data[sid] = r

            # Sort by RRF score
            sorted_ids = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]
            results = []
            for sid in sorted_ids:
                r = data[sid]
                # Get full text from metadata
                row = self.conn.execute(
                    "SELECT text, symbol_kind, docstring, layer, line_start FROM chunks WHERE symbol_name=? AND file_path=?",
                    (r['name'], r['file'])
                ).fetchone()
                results.append({
                    'symbol': r['name'],
                    'file': r['file'],
                    'kind': row[1] if row else '?',
                    'layer': row[3] if row else '?',
                    'line': row[4] if row else 0,
                    'rrf_score': scores[sid],
                    'tier': r['tier'],
                    'text_preview': (row[0][:150] if row else '').replace('\n', ' '),
                })

            return results

        def close(self):
            self.conn.close()

    # ════════════════════════════════════════════════════════════════
    #  STEP 4: Naive keyword search (baseline — what MSCodeBase BM25 does)
    # ════════════════════════════════════════════════════════════════

    def naive_keyword_search(chunks, query, limit=5):
        """Simple keyword search (baseline — equivalent to current BM25 approach)."""
        query_lower = query.lower()
        query_tokens = re.split(r'\W+', query_lower)
        query_tokens = [t for t in query_tokens if len(t) >= 2]

        scored = []
        for ch in chunks:
            text_lower = ch['text'].lower()
            score = 0
            for token in query_tokens:
                # Simple TF counting
                score += text_lower.count(token)
            if score > 0:
                scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                'symbol': ch['symbol_name'],
                'file': ch['file_path'],
                'kind': ch['symbol_kind'],
                'layer': ch['layer'],
                'line': ch['line_start'],
                'score': sc,
                'tier': 'keyword_baseline',
                'text_preview': ch['text'][:150].replace('\n', ' '),
            }
            for sc, ch in scored[:limit]
        ]

    # ════════════════════════════════════════════════════════════════
    #  STEP 5: Run experiment
    # ════════════════════════════════════════════════════════════════

    def run():
        print("=" * 70)
        print("EXPERIMENT: FTS5 3-Index (srclight) vs Keyword Baseline")
        print("Data: MSCodeBase/src — real project source code")
        print("=" * 70)
        print()

        # 1. Scan
        print("[1/5] Scanning project...")
        chunks, n_files = scan_project(PROJECT / "src")
        print(f"  Files: {n_files}, Chunks: {len(chunks)}")

        layer_stats = defaultdict(int)
        kind_stats = defaultdict(int)
        for ch in chunks:
            layer_stats[ch['layer']] += 1
            kind_stats[ch['symbol_kind']] += 1
        print(f"  Layers: {dict(layer_stats)}")
        print(f"  Kinds:  {dict(kind_stats)}")
        print()

        # 2. Build FTS5
        print("[2/5] Building FTS5 3-index (srclight approach)...")
        fts = FTS5Experiment()
        idx_metrics = fts.index(chunks)
        print(f"  Build time: {idx_metrics['build_ms']}ms")
        print(f"  Names indexed: {idx_metrics['names']}")
        print(f"  Content indexed: {idx_metrics['content']}")
        print(f"  Docs indexed: {idx_metrics['docs']}")
        print()

        # 3. Test queries
        print("[3/5] Running search benchmarks...")
        print()

        # Query categories
        test_queries = {
            "exact_symbol": [
                "hybrid_search",
                "AsyncInferQueue",
                "embed_batch",
                "Searcher",
                "LanceDBManager",
            ],
            "partial_name": [
                "embed",
                "search",
                "index",
                "rerank",
                "graph",
            ],
            "concept": [
                "thread safety caching",
                "error handling async",
                "file watching changes",
                "token counting",
            ],
            "file_location": [
                "where is reranker defined",
                "bm25 implementation",
                "property graph",
            ],
        }

        all_results = []
        total_fts5_ms = 0
        total_keyword_ms = 0

        for category, queries in test_queries.items():
            print(f"  Category: {category}")
            print(f"  {'─' * 66}")

            for query in queries:
                # FTS5 hybrid
                t0 = time.perf_counter()
                fts5_results = fts.hybrid_search(query, limit=5)
                fts5_ms = (time.perf_counter() - t0) * 1000
                total_fts5_ms += fts5_ms

                # Keyword baseline
                t0 = time.perf_counter()
                kw_results = naive_keyword_search(chunks, query, limit=5)
                kw_ms = (time.perf_counter() - t0) * 1000
                total_keyword_ms += kw_ms

                # Compare top-3
                fts5_top3 = [(r['symbol'], r['file']) for r in fts5_results[:3]]
                kw_top3 = [(r['symbol'], r['file']) for r in kw_results[:3]]

                # Overlap
                fts5_set = set(r['symbol'] for r in fts5_results[:5])
                kw_set = set(r['symbol'] for r in kw_results[:5])
                overlap = fts5_set & kw_set
                only_fts5 = fts5_set - kw_set
                only_kw = kw_set - fts5_set

                print(f"    Q: '{query}'")
                print(f"      FTS5 ({fts5_ms:.1f}ms): {', '.join(r['symbol'] for r in fts5_results[:3])}")
                print(f"      KW  ({kw_ms:.1f}ms): {', '.join(r['symbol'] for r in kw_results[:3])}")
                print(f"      Overlap: {len(overlap)} | Only FTS5: {only_fts5 or '-'} | Only KW: {only_kw or '-'}")

                # Tier breakdown for FTS5
                tiers = defaultdict(int)
                for r in fts5_results:
                    tiers[r['tier']] += 1
                print(f"      FTS5 tiers: {dict(tiers)}")
                print()

                all_results.append({
                    'query': query,
                    'category': category,
                    'fts5_ms': round(fts5_ms, 2),
                    'keyword_ms': round(kw_ms, 2),
                    'fts5_results': [r['symbol'] for r in fts5_results],
                    'keyword_results': [r['symbol'] for r in kw_results],
                    'overlap': list(overlap),
                    'fts5_only': list(only_fts5),
                    'keyword_only': list(only_kw),
                })

        # 4. Tokenizer quality test
        print("[4/5] CamelCase tokenizer quality...")
        print()

        tokenizer_tests = [
            ("hybridSearchAsync", "srclight"),
            ("get_variable_flow", "snake_case"),
            ("BM25Mixin", "acronym"),
            ("AsyncInferQueue", "PascalCase"),
            ("_apply_co_change_boost", "private+snake"),
            ("_build_bm25_index", "private+snake"),
            ("reciprocal_rank_fusion", "snake_case"),
            ("LanceDBManager", "PascalCase"),
        ]

        for name, label in tokenizer_tests:
            tokens = split_identifier(name)
            print(f"  [{label}] '{name}' → '{tokens}'")

        print()

        # 5. Summary
        n_queries = sum(len(qs) for qs in test_queries.values())
        avg_fts5 = total_fts5_ms / n_queries
        avg_kw = total_keyword_ms / n_queries

        print("[5/5] SUMMARY")
        print()
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"  Chunks indexed:    {len(chunks)}")
        print(f"  Files scanned:     {n_files}")
        print(f"  FTS5 build time:   {idx_metrics['build_ms']}ms")
        print()
        print(f"  FTS5 hybrid:")
        print(f"    Total latency:   {total_fts5_ms:.1f}ms ({n_queries} queries)")
        print(f"    Avg per query:   {avg_fts5:.1f}ms")
        print()
        print(f"  Keyword baseline:")
        print(f"    Total latency:   {total_keyword_ms:.1f}ms ({n_queries} queries)")
        print(f"    Avg per query:   {avg_kw:.1f}ms")
        print()
        speedup = avg_kw / avg_fts5 if avg_fts5 > 0 else float('inf')
        print(f"  Speedup:           {speedup:.1f}x {'(FTS5 faster)' if speedup > 1 else '(keyword faster)'}")
        print()

        # Quality: overlap analysis
        total_overlap = sum(len(r['overlap']) for r in all_results)
        total_fts5_only = sum(len(r['fts5_only']) for r in all_results)
        total_kw_only = sum(len(r['keyword_only']) for r in all_results)
        total_symbols = total_overlap + total_fts5_only + total_kw_only

        print(f"  Quality (top-5 overlap):")
        print(f"    In both:         {total_overlap} ({100*total_overlap/max(total_symbols,1):.0f}%)")
        print(f"    FTS5 only:       {total_fts5_only} ({100*total_fts5_only/max(total_symbols,1):.0f}%)")
        print(f"    Keyword only:    {total_kw_only} ({100*total_kw_only/max(total_symbols,1):.0f}%)")
        print()

        # Save
        out = PROJECT / "experiments" / "fts5_vs_keyword_results.json"
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({
                'chunks': len(chunks),
                'files': n_files,
                'build_ms': idx_metrics['build_ms'],
                'avg_fts5_ms': round(avg_fts5, 1),
                'avg_keyword_ms': round(avg_kw, 1),
                'speedup': round(speedup, 1),
                'results': all_results,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Saved to: {out}")

        fts.close()

    if __name__ == "__main__":
        run()

except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
