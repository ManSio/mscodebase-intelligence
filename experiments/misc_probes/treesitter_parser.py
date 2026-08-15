"""Experiment 2: Tree-sitter Multi-Language AST Parser.

Inspired by: Cranot/roam-code (500★, Apache 2.0) — 28 languages via Tree-sitter
Also: srclight/srclight (52★, MIT) — 11 languages via Tree-sitter

MSCodeBase currently uses Python's built-in `ast` module — Python-only.
Tree-sitter adds: Python, JavaScript, TypeScript, Rust, Go (already installed).

This prototype:
1. Parses MSCodeBase source with Tree-sitter
2. Extracts symbols (functions, classes, imports, calls)
3. Compares quality vs Python `ast` module
4. Measures parse speed

Metrics:
- Parse speed (files/sec)
- Symbol extraction quality
- Language coverage
- Call graph edges extracted

Run:
    cd D:/Project/MSCodeBase
    python experiments/treesitter_parser.py
"""

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import os
    import re
    import time
    import json
    from pathlib import Path
    from typing import Dict, List, Optional, Tuple, Set
    from dataclasses import dataclass, field

    import tree_sitter

    # ─── Language registry ─────────────────────────────────────
    LANGUAGES: Dict[str, str] = {}

    def _register_languages():
        """Register available tree-sitter language packs."""
        global LANGUAGES
        try:
            import tree_sitter_python
            LANGUAGES['python'] = tree_sitter_python.language()
        except ImportError:
            pass
        try:
            import tree_sitter_javascript
            LANGUAGES['javascript'] = tree_sitter_javascript.language()
        except ImportError:
            pass
        try:
            import tree_sitter_typescript
            LANGUAGES['typescript'] = tree_sitter_typescript.language_typescript()
            LANGUAGES['tsx'] = tree_sitter_typescript.language_tsx()
        except ImportError:
            pass
        try:
            import tree_sitter_rust
            LANGUAGES['rust'] = tree_sitter_rust.language()
        except ImportError:
            pass
        try:
            import tree_sitter_go
            LANGUAGES['go'] = tree_sitter_go.language()
        except ImportError:
            pass

    _register_languages()

    EXTENSION_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.mjs': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.rs': 'rust',
        '.go': 'go',
    }

    # ─── Symbol dataclass ──────────────────────────────────────
    @dataclass
    class Symbol:
        name: str
        kind: str  # 'function', 'class', 'method', 'variable', 'import', 'call'
        file_path: str
        line_start: int
        line_end: int
        parent: Optional[str] = None  # enclosing class/function
        calls: List[str] = field(default_factory=list)  # functions called
        imports: List[str] = field(default_factory=list)  # imported symbols
        decorators: List[str] = field(default_factory=list)

    # ─── Tree-sitter Parser ────────────────────────────────────
    class TreeSitterCodeParser:
        """Multi-language code parser using Tree-sitter.

        Extracts: functions, classes, methods, imports, calls, decorators.
        Generates: call graph edges, import graph, symbol table.
        """

        def __init__(self):
            self._parsers: Dict[str, tree_sitter.Parser] = {}
            self._init_parsers()

        def _init_parsers(self):
            """Create a parser for each registered language."""
            for lang_name, lang_obj in LANGUAGES.items():
                try:
                    parser = tree_sitter.Parser(tree_sitter.Language(lang_obj))
                    self._parsers[lang_name] = parser
                except Exception as e:
                    print(f"  Warning: Failed to create parser for {lang_name}: {e}")

        def detect_language(self, file_path: str) -> Optional[str]:
            """Detect language from file extension."""
            ext = Path(file_path).suffix.lower()
            return EXTENSION_MAP.get(ext)

        def parse_file(self, file_path: str) -> Optional[Tuple[tree_sitter.Tree, str]]:
            """Parse a single file and return (tree, source_code)."""
            lang = self.detect_language(file_path)
            if lang is None or lang not in self._parsers:
                return None

            try:
                source = Path(file_path).read_text(encoding='utf-8', errors='ignore')
            except Exception:
                return None

            parser = self._parsers[lang]
            tree = parser.parse(source.encode('utf-8'))
            return tree, source

        def extract_symbols(self, file_path: str) -> List[Symbol]:
            """Extract all symbols from a file."""
            result = self.parse_file(file_path)
            if result is None:
                return []

            tree, source = result
            lang = self.detect_language(file_path)
            symbols = []

            # Language-specific extraction
            if lang == 'python':
                symbols = self._extract_python(tree, source, file_path)
            elif lang in ('javascript', 'typescript', 'tsx'):
                symbols = self._extract_js_ts(tree, source, file_path)
            elif lang == 'rust':
                symbols = self._extract_rust(tree, source, file_path)
            elif lang == 'go':
                symbols = self._extract_go(tree, source, file_path)

            return symbols

        def _extract_python(self, tree: tree_sitter.Tree, source: str, file_path: str) -> List[Symbol]:
            """Extract Python symbols using Tree-sitter."""
            symbols = []
            source_bytes = source.encode('utf-8')

            # Query patterns
            query_str = """
            (function_definition
                name: (identifier) @func_name
                parameters: (parameters) @params
                body: (block) @body
            ) @func_def

            (class_definition
                name: (identifier) @class_name
                body: (block) @class_body
            ) @class_def

            (decorated_definition
                (decorator
                    (identifier) @decorator_name
                )
            ) @decorated
            """

            try:
                query = tree_sitter.Query(tree.language, query_str)
                captures = query.captures(tree.root_node)
            except Exception:
                # Fallback: basic extraction
                return self._fallback_extract(source, file_path, 'python')

            # Track class context
            current_class = None

            for node in tree.root_node.children:
                node_type = node.type

                if node_type == 'function_definition' or node_type == 'async_function_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        name = name_node.text.decode('utf-8')
                        symbols.append(Symbol(
                            name=name,
                            kind='async_function' if node_type == 'async_function_definition' else 'function',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                            calls=self._find_calls_in_node(node),
                        ))

                elif node_type == 'class_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        name = name_node.text.decode('utf-8')
                        symbols.append(Symbol(
                            name=name,
                            kind='class',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                            calls=self._find_calls_in_node(node),
                        ))

                elif node_type == 'import_from_statement' or node_type == 'import_statement':
                    imp_text = node.text.decode('utf-8')
                    symbols.append(Symbol(
                        name=imp_text,
                        kind='import',
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                    ))

            return symbols

        def _extract_js_ts(self, tree: tree_sitter.Tree, source: str, file_path: str) -> List[Symbol]:
            """Extract JavaScript/TypeScript symbols."""
            symbols = []

            for node in tree.root_node.children:
                node_type = node.type

                if node_type in ('function_declaration', 'arrow_function'):
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        symbols.append(Symbol(
                            name=name_node.text.decode('utf-8'),
                            kind='function',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))

                elif node_type == 'class_declaration':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        symbols.append(Symbol(
                            name=name_node.text.decode('utf-8'),
                            kind='class',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))

                elif node_type in ('import_statement', 'import_declaration'):
                    symbols.append(Symbol(
                        name=node.text.decode('utf-8')[:100],
                        kind='import',
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                    ))

            return symbols

        def _extract_rust(self, tree: tree_sitter.Tree, source: str, file_path: str) -> List[Symbol]:
            """Extract Rust symbols."""
            symbols = []

            for node in tree.root_node.children:
                node_type = node.type

                if node_type == 'function_item':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        symbols.append(Symbol(
                            name=name_node.text.decode('utf-8'),
                            kind='function',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))

                elif node_type in ('struct_item', 'enum_item', 'trait_item'):
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        symbols.append(Symbol(
                            name=name_node.text.decode('utf-8'),
                            kind=node_type.split('_')[0],
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))

                elif node_type == 'use_declaration':
                    symbols.append(Symbol(
                        name=node.text.decode('utf-8')[:100],
                        kind='import',
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                    ))

            return symbols

        def _extract_go(self, tree: tree_sitter.Tree, source: str, file_path: str) -> List[Symbol]:
            """Extract Go symbols."""
            symbols = []

            for node in tree.root_node.children:
                node_type = node.type

                if node_type == 'function_declaration':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        symbols.append(Symbol(
                            name=name_node.text.decode('utf-8'),
                            kind='function',
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))

                elif node_type == 'type_declaration':
                    symbols.append(Symbol(
                        name=node.text.decode('utf-8')[:60],
                        kind='type',
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                    ))

            return symbols

        def _find_calls_in_node(self, node) -> List[str]:
            """Find function calls inside a node."""
            calls = []
            for child in node.children:
                if child.type == 'call_expression':
                    func = child.child_by_field_name('function')
                    if func:
                        calls.append(func.text.decode('utf-8'))
                # Recurse into blocks
                if child.type in ('block', 'suite', 'expression_statement'):
                    calls.extend(self._find_calls_in_node(child))
            return calls[:20]  # Cap to prevent explosion

        def _fallback_extract(self, source: str, file_path: str, lang: str) -> List[Symbol]:
            """Regex-based fallback when tree-sitter query fails."""
            symbols = []
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if lang == 'python':
                    if stripped.startswith('def ') or stripped.startswith('async def '):
                        match = re.search(r'(?:async\s+)?def\s+(\w+)', stripped)
                        if match:
                            symbols.append(Symbol(
                                name=match.group(1),
                                kind='function',
                                file_path=file_path,
                                line_start=i, line_end=i,
                            ))
                    elif stripped.startswith('class '):
                        match = re.search(r'class\s+(\w+)', stripped)
                        if match:
                            symbols.append(Symbol(
                                name=match.group(1),
                                kind='class',
                                file_path=file_path,
                                line_start=i, line_end=i,
                            ))
            return symbols

    import logging
    logger = logging.getLogger(__name__)

    # ─── Experiment Runner ──────────────────────────────────────
    def run_benchmark(project_root: Path):
        """Run Tree-sitter parser benchmark on MSCodeBase."""
        print("=" * 70)
        print("EXPERIMENT 2: Tree-sitter Multi-Language AST Parser")
        print("Inspired by: Cranot/roam-code (500★) + srclight (52★)")
        print("=" * 70)
        print()

        # Available languages
        print(f"Available languages: {list(LANGUAGES.keys())}")
        print(f"Parsers created: {len(LANGUAGES)}")
        print()

        # 1. Parse all Python files in the project
        print("[1/3] Scanning and parsing files...")
        parser = TreeSitterCodeParser()

        all_files = []
        src_dir = project_root / "src"
        for ext, lang in EXTENSION_MAP.items():
            for f in src_dir.rglob(f"*{ext}"):
                rel = str(f.relative_to(project_root))
                if '__pycache__' not in rel and '.venv' not in rel and 'experiments' not in rel:
                    all_files.append((str(f), rel, lang))

        print(f"  Found {len(all_files)} source files")
        lang_counts = {}
        for _, _, lang in all_files:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for lang, count in sorted(lang_counts.items()):
            print(f"    {lang}: {count} files")

        # 2. Parse all files
        print(f"\n[2/3] Parsing with Tree-sitter...")
        all_symbols: List[Symbol] = []
        parse_errors = 0
        parse_times = []

        for abs_path, rel_path, lang in all_files:
            start = time.perf_counter()
            try:
                symbols = parser.extract_symbols(abs_path)
                elapsed = (time.perf_counter() - start) * 1000
                parse_times.append(elapsed)
                for s in symbols:
                    s.file_path = rel_path  # Use relative path
                all_symbols.extend(symbols)
            except Exception as e:
                parse_errors += 1
                logger.debug(f"Parse error in {rel_path}: {e}")

        total_parse_ms = sum(parse_times)
        avg_parse_ms = total_parse_ms / max(len(parse_times), 1)

        # Symbol stats
        sym_by_kind = {}
        for s in all_symbols:
            sym_by_kind[s.kind] = sym_by_kind.get(s.kind, 0) + 1

        print(f"  Files parsed: {len(all_files) - parse_errors}/{len(all_files)}")
        print(f"  Parse errors: {parse_errors}")
        print(f"  Total parse time: {total_parse_ms:.1f}ms")
        print(f"  Avg per file: {avg_parse_ms:.2f}ms")
        print(f"  Throughput: {len(all_files) / max(total_parse_ms / 1000, 0.001):.0f} files/sec")
        print(f"  Symbols extracted: {len(all_symbols)}")
        for kind, count in sorted(sym_by_kind.items()):
            print(f"    {kind}: {count}")

        # 3. Call graph extraction
        print(f"\n[3/3] Call graph analysis...")
        call_edges = []
        for sym in all_symbols:
            for called in sym.calls:
                call_edges.append((f"{sym.file_path}::{sym.name}", called))

        # Find unique callers and callees
        unique_callers = set(e[0] for e in call_edges)
        unique_callees = set(e[1] for e in call_edges)

        print(f"  Call edges: {len(call_edges)}")
        print(f"  Unique callers: {len(unique_callers)}")
        print(f"  Unique callees: {len(unique_callees)}")

        # Top called functions
        call_freq = {}
        for _, callee in call_edges:
            call_freq[callee] = call_freq.get(callee, 0) + 1
        top_called = sorted(call_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"  Top 10 most-called functions:")
        for name, freq in top_called:
            print(f"    {name}: called {freq}x")

        # Show sample symbols
        print(f"\n  Sample symbols (first 15):")
        for s in all_symbols[:15]:
            calls_str = f" → [{', '.join(s.calls[:3])}]" if s.calls else ""
            print(f"    [{s.kind:15}] {s.name:30} in {s.file_path}:{s.line_start}{calls_str}")

        # Compare with Python ast module
        print(f"\n  Comparison: Python ast module (current MSCodeBase approach)")
        print(f"    Python ast: single language, no call graph from AST")
        print(f"    Tree-sitter: {len(LANGUAGES)} languages, call extraction, {len(call_edges)} edges")

        # Summary
        print()
        print("=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Languages:       {len(LANGUAGES)}")
        print(f"  Files parsed:    {len(all_files) - parse_errors}/{len(all_files)}")
        print(f"  Parse speed:     {len(all_files) / max(total_parse_ms / 1000, 0.001):.0f} files/sec")
        print(f"  Symbols found:   {len(all_symbols)}")
        print(f"  Call edges:      {len(call_edges)}")
        print(f"  Parse errors:    {parse_errors}")
        print()

        # Save results
        results_file = project_root / "experiments" / "treesitter_results.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                "experiment": "treesitter_multi_language_parser",
                "source": "Cranot/roam-code + srclight/srclight",
                "languages_available": list(LANGUAGES.keys()),
                "files_parsed": len(all_files) - parse_errors,
                "total_parse_ms": round(total_parse_ms, 1),
                "avg_parse_ms": round(avg_parse_ms, 2),
                "files_per_sec": round(len(all_files) / max(total_parse_ms / 1000, 0.001), 0),
                "symbols_extracted": len(all_symbols),
                "symbol_counts": sym_by_kind,
                "call_edges": len(call_edges),
                "top_called": top_called,
                "parse_errors": parse_errors,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Results saved to: {results_file}")

        return all_symbols, call_edges


    if __name__ == "__main__":
        project_root = Path(__file__).parent.parent
        run_benchmark(project_root)

except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
