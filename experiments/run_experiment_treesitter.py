"""REAL Experiment: Tree-sitter vs Python ast module.

Tests whether Tree-sitter extracts richer information from the SAME source code.

Metrics:
- Parse speed (files/sec)
- Symbols extracted (count + kinds)
- Call graph edges
- Information richness (decorators, params, return types)
"""

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import ast
    import re
    import time
    import json
    from pathlib import Path
    from collections import defaultdict

    import tree_sitter

    # Import language packs
    import tree_sitter_python
    PY_LANG = tree_sitter.Language(tree_sitter_python.language())

    PROJECT = Path(__file__).resolve().parent.parent

    # ════════════════════════════════════════════════════════════════
    #  Python ast extractor (current MSCodeBase approach)
    # ════════════════════════════════════════════════════════════════

    class PythonAstExtractor:
        """Extract symbols using Python's built-in ast module."""

        def parse_file(self, path):
            try:
                source = path.read_text(encoding='utf-8', errors='ignore')
                tree = ast.parse(source)
                return tree, source
            except Exception:
                return None, None

        def extract(self, path, source, tree):
            symbols = []
            calls = []
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Get args
                    args = []
                    for arg in node.args.args:
                        args.append(arg.arg)
                    # Get return annotation
                    ret = ""
                    if node.returns:
                        try:
                            ret = ast.dump(node.returns)
                        except Exception:
                            ret = "..."

                    # Get decorators
                    decos = []
                    for d in node.decorator_list:
                        if isinstance(d, ast.Name):
                            decos.append(d.id)
                        elif isinstance(d, ast.Attribute):
                            decos.append(d.attr)

                    symbols.append({
                        'name': node.name,
                        'kind': 'async_function' if isinstance(node, ast.AsyncFunctionDef) else 'function',
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno),
                        'args': args,
                        'return_type': ret[:80] if ret else '',
                        'decorators': decos,
                        'docstring': ast.get_docstring(node) or '',
                    })

                    # Extract calls inside this function
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                calls.append((node.name, child.func.id))
                            elif isinstance(child.func, ast.Attribute):
                                calls.append((node.name, child.func.attr))

                elif isinstance(node, ast.ClassDef):
                    methods = []
                    for item in ast.walk(node):
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item != node:
                            methods.append(item.name)

                    symbols.append({
                        'name': node.name,
                        'kind': 'class',
                        'line_start': node.lineno,
                        'line_end': getattr(node, 'end_lineno', node.lineno),
                        'methods': methods,
                        'docstring': ast.get_docstring(node) or '',
                    })

                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            imports.append({
                                'module': node.module or '',
                                'name': alias.name,
                                'asname': alias.asname or '',
                            })
                    else:
                        for alias in node.names:
                            imports.append({
                                'module': '',
                                'name': alias.name,
                                'asname': alias.asname or '',
                            })

            return {
                'symbols': symbols,
                'calls': calls,
                'imports': imports,
            }

    # ════════════════════════════════════════════════════════════════
    #  Tree-sitter extractor
    # ════════════════════════════════════════════════════════════════

    class TreeSitterExtractor:
        """Extract symbols using tree-sitter Python grammar."""

        def __init__(self):
            self.parser = tree_sitter.Parser(PY_LANG)

        def parse_file(self, path):
            try:
                source = path.read_text(encoding='utf-8', errors='ignore')
                tree = self.parser.parse(source.encode('utf-8'))
                return tree, source
            except Exception:
                return None, None

        def extract(self, path, source, tree):
            symbols = []
            calls = []
            imports = []
            source_bytes = source.encode('utf-8')

            for node in tree.root_node.children:
                ntype = node.type

                if ntype in ('function_definition', 'async_function_definition'):
                    name_node = node.child_by_field_name('name')
                    params_node = node.child_by_field_name('parameters')
                    body_node = node.child_by_field_name('body')

                    name = name_node.text.decode() if name_node else '?'
                    params_text = params_node.text.decode() if params_node else '()'

                    # Extract decorators
                    decos = []
                    for prev_idx in range(node.named_children.__len__()):
                        child = node.named_children[prev_idx]
                        if child.type == 'decorator':
                            decos.append(child.text.decode().lstrip('@').split('(')[0])

                    # Extract return type annotation
                    ret_type = ''
                    for child in node.children:
                        if child.type == 'type':
                            ret_type = child.text.decode()
                            break

                    # Extract calls from body
                    func_calls = []
                    if body_node:
                        self._find_calls(body_node, func_calls)

                    symbols.append({
                        'name': name,
                        'kind': 'async_function' if ntype == 'async_function_definition' else 'function',
                        'line_start': node.start_point[0] + 1,
                        'line_end': node.end_point[0] + 1,
                        'params': params_text[:100],
                        'return_type': ret_type[:80],
                        'decorators': decos,
                    })

                    for c in func_calls:
                        calls.append((name, c))

                elif ntype == 'class_definition':
                    name_node = node.child_by_field_name('name')
                    name = name_node.text.decode() if name_node else '?'

                    # Find methods inside class
                    methods = []
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            if child.type in ('function_definition', 'async_function_definition'):
                                mn = child.child_by_field_name('name')
                                if mn:
                                    methods.append(mn.text.decode())

                    symbols.append({
                        'name': name,
                        'kind': 'class',
                        'line_start': node.start_point[0] + 1,
                        'line_end': node.end_point[0] + 1,
                        'methods': methods,
                    })

                elif ntype == 'import_statement':
                    text = node.text.decode()
                    imports.append({'raw': text[:100]})

                elif ntype == 'import_from_statement':
                    text = node.text.decode()
                    imports.append({'raw': text[:100]})

            return {
                'symbols': symbols,
                'calls': calls,
                'imports': imports,
            }

        def _find_calls(self, node, calls, depth=0):
            """Recursively find function calls in a node."""
            if depth > 10:
                return
            if node.type == 'call_expression':
                func = node.child_by_field_name('function')
                if func:
                    calls.append(func.text.decode())
            for child in node.children:
                self._find_calls(child, calls, depth + 1)

    # ════════════════════════════════════════════════════════════════
    #  Run comparison
    # ════════════════════════════════════════════════════════════════

    def run():
        print("=" * 70)
        print("EXPERIMENT: Tree-sitter vs Python ast Module")
        print("Data: MSCodeBase/src — real project source code")
        print("=" * 70)
        print()

        # Collect all .py files
        files = []
        for py_file in (PROJECT / "src").rglob("*.py"):
            rel = str(py_file.relative_to(PROJECT))
            if '__pycache__' not in rel and 'experiments' not in rel:
                files.append(py_file)
        files.sort()

        print(f"Files to parse: {len(files)}")
        print()

        py_ast = PythonAstExtractor()
        ts_parser = TreeSitterExtractor()

        # Statistics
        ast_stats = {'files': 0, 'symbols': 0, 'calls': 0, 'imports': 0,
                     'kinds': defaultdict(int), 'time_ms': 0}
        ts_stats = {'files': 0, 'symbols': 0, 'calls': 0, 'imports': 0,
                    'kinds': defaultdict(int), 'time_ms': 0}

        # Per-file comparison
        comparisons = []

        for i, f in enumerate(files):
            rel = str(f.relative_to(PROJECT))

            # Python ast
            t0 = time.perf_counter()
            ast_tree, source = py_ast.parse_file(f)
            ast_ms = (time.perf_counter() - t0) * 1000
            ast_result = {}
            if ast_tree and source:
                ast_result = py_ast.extract(f, source, ast_tree)

            # Tree-sitter
            t0 = time.perf_counter()
            ts_tree, ts_source = ts_parser.parse_file(f)
            ts_ms = (time.perf_counter() - t0) * 1000
            ts_result = {}
            if ts_tree and ts_source:
                ts_result = ts_parser.extract(f, ts_source, ts_tree)

            ast_stats['time_ms'] += ast_ms
            ts_stats['time_ms'] += ts_ms

            if ast_result:
                ast_stats['files'] += 1
                ast_stats['symbols'] += len(ast_result.get('symbols', []))
                ast_stats['calls'] += len(ast_result.get('calls', []))
                ast_stats['imports'] += len(ast_result.get('imports', []))
                for s in ast_result.get('symbols', []):
                    ast_stats['kinds'][s['kind']] += 1

            if ts_result:
                ts_stats['files'] += 1
                ts_stats['symbols'] += len(ts_result.get('symbols', []))
                ts_stats['calls'] += len(ts_result.get('calls', []))
                ts_stats['imports'] += len(ts_result.get('imports', []))
                for s in ts_result.get('symbols', []):
                    ts_stats['kinds'][s['kind']] += 1

            # Compare
            ast_syms = set(s['name'] for s in ast_result.get('symbols', []))
            ts_syms = set(s['name'] for s in ts_result.get('symbols', []))
            ast_calls = set(c[1] for c in ast_result.get('calls', []))
            ts_calls = set(c[1] for c in ts_result.get('calls', []))

            comparisons.append({
                'file': rel,
                'ast_syms': len(ast_syms),
                'ts_syms': len(ts_syms),
                'ast_calls': len(ast_calls),
                'ts_calls': len(ts_calls),
                'ast_ms': round(ast_ms, 2),
                'ts_ms': round(ts_ms, 2),
            })

        # Summary
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)
        print()

        print(f"{'Metric':<35} {'Python ast':>15} {'Tree-sitter':>15} {'Delta':>10}")
        print(f"{'─' * 75}")

        def fmt_delta(v1, v2):
            if v1 == 0:
                return "—"
            d = (v2 - v1) / v1 * 100
            sign = "+" if d > 0 else ""
            return f"{sign}{d:.0f}%"

        metrics = [
            ("Files parsed", ast_stats['files'], ts_stats['files']),
            ("Total symbols", ast_stats['symbols'], ts_stats['symbols']),
            ("Total call edges", ast_stats['calls'], ts_stats['calls']),
            ("Total imports", ast_stats['imports'], ts_stats['imports']),
            ("Total parse time (ms)", round(ast_stats['time_ms'], 1), round(ts_stats['time_ms'], 1)),
        ]

        for name, v1, v2 in metrics:
            print(f"  {name:<33} {str(v1):>15} {str(v2):>15} {fmt_delta(v1, v2):>10}")

        print()
        print("  Symbol kinds:")
        all_kinds = set(ast_stats['kinds'].keys()) | set(ts_stats['kinds'].keys())
        for kind in sorted(all_kinds):
            av = ast_stats['kinds'].get(kind, 0)
            tv = ts_stats['kinds'].get(kind, 0)
            print(f"    {kind:<20} ast={av:<8} ts={tv:<8} {fmt_delta(av, tv)}")

        # Speed comparison
        ast_files_per_sec = ast_stats['files'] / (ast_stats['time_ms'] / 1000) if ast_stats['time_ms'] > 0 else 0
        ts_files_per_sec = ts_stats['files'] / (ts_stats['time_ms'] / 1000) if ts_stats['time_ms'] > 0 else 0
        print()
        print(f"  Speed:")
        print(f"    Python ast:  {ast_stats['time_ms']:.1f}ms total → {ast_files_per_sec:.0f} files/sec")
        print(f"    Tree-sitter: {ts_stats['time_ms']:.1f}ms total → {ts_files_per_sec:.0f} files/sec")

        # Information richness comparison
        print()
        print("  Richness comparison (sample files):")
        # Show top 5 biggest differences
        diffs = sorted(comparisons, key=lambda c: abs(c['ts_calls'] - c['ast_calls']), reverse=True)
        for d in diffs[:5]:
            call_gain = d['ts_calls'] - d['ast_calls']
            sym_gain = d['ts_syms'] - d['ast_syms']
            print(f"    {d['file']}")
            print(f"      ast: {d['ast_syms']} syms, {d['ast_calls']} calls ({d['ast_ms']}ms)")
            print(f"      ts:  {d['ts_syms']} syms, {d['ts_calls']} calls ({d['ts_ms']}ms)")
            print(f"      Δ:   {'+' if sym_gain > 0 else ''}{sym_gain} syms, {'+' if call_gain > 0 else ''}{call_gain} calls")

        # Unique features
        print()
        print("  Unique features:")
        print("    Python ast: return type annotations, arg names, docstrings (via get_docstring)")
        print("    Tree-sitter: params text, decorators (raw), return type annotation (raw),")
        print("                 call resolution (attribute chains like self.embedder.embed)")
        print()

        # Save
        out = PROJECT / "experiments" / "treesitter_vs_ast_results.json"
        with open(out, 'w', encoding='utf-8') as f:
            json.dump({
                'ast': {
                    'files': ast_stats['files'],
                    'symbols': ast_stats['symbols'],
                    'calls': ast_stats['calls'],
                    'imports': ast_stats['imports'],
                    'time_ms': round(ast_stats['time_ms'], 1),
                    'files_per_sec': round(ast_files_per_sec, 0),
                    'kinds': dict(ast_stats['kinds']),
                },
                'tree_sitter': {
                    'files': ts_stats['files'],
                    'symbols': ts_stats['symbols'],
                    'calls': ts_stats['calls'],
                    'imports': ts_stats['imports'],
                    'time_ms': round(ts_stats['time_ms'], 1),
                    'files_per_sec': round(ts_files_per_sec, 0),
                    'kinds': dict(ts_stats['kinds']),
                },
                'per_file': comparisons,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Saved to: {out}")

    if __name__ == "__main__":
        run()

except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
