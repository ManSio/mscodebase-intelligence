"""E1 — Инвентаризация циклических импортов src/mcp (эксперимент 2026-08-17).

Измеряет:
  1. Полный статический граф импортов src/mcp/* (как ARCLUX): рёбра (from → to).
  2. SCC (сильно связные компоненты) — циклы; каждый цикл классифицируется:
     - «lazy»: хотя бы одно ребро цикла — импорт ВНУТРИ функции (не исполняется
       при импорте модуля) → рантайм-безопасен;
     - «load»: все рёбра цикла исполняются при импорте (module-level или class-body)
       → риск AttributeError/ImportError при холодном старте.
  3. Fresh-interpreter import-test: каждый модуль src/mcp/* импортируется в
     ОТДЕЛЬНОМ процессе `python -c "import <mod>"` — эмпирическая проверка
     отсутствия дедлоков/частичной инициализации (H3).

Запуск:  python experiments/arclux_cycles_inventory.py
Вывод:   1) статистика графа; 2) список SCC с классификацией; 3) результат
         import-тестов; 4) сводка load-циклов (главный риск).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ENCODING SAFETY (Windows, §5.9): вывод содержит кириллицу/юникод — cp1251 падает.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
MCP = SRC / "mcp"


def module_dotted(p: Path) -> str:
    rel = p.relative_to(REPO)
    return str(rel.with_suffix("")).replace("\\", "/").replace("/", ".")


class ImportScanner(ast.NodeVisitor):
    def __init__(self, own_mod: str):
        self.own_mod = own_mod
        self.pkg = own_mod.rsplit(".", 1)[0] if "." in own_mod else ""
        self.imports: List[Tuple[int, str, str]] = []  # (lineno, resolved, scope)
        self._scope_stack: List[str] = ["module"]

    def _scope(self) -> str:
        # 'lazy' только внутри функции/async-функции; class-body исполняется при импорте.
        for s in reversed(self._scope_stack):
            if s == "function":
                return "lazy"
            if s == "class":
                return "class"
        return "module"

    def _resolve(self, node: ast.ImportFrom) -> Optional[str]:
        if node.level:  # relative
            parts = self.pkg.split(".") if self.pkg else []
            up = node.level - 1
            if up > 0:
                parts = parts[:-up] if up <= len(parts) else []
            base = ".".join(parts)
            if node.module:
                return f"{base}.{node.module}" if base else node.module
            return base
        return node.module

    def visit_Import(self, node: ast.Import):
        scope = self._scope()
        for alias in node.names:
            self.imports.append((node.lineno, alias.name, scope))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        resolved = self._resolve(node)
        if resolved:
            self.imports.append((node.lineno, resolved, self._scope()))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._scope_stack.append("function")
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._scope_stack.append("function")
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef):
        self._scope_stack.append("class")
        self.generic_visit(node)
        self._scope_stack.pop()


def scan_dir(root: Path) -> Tuple[Dict[str, Path], Dict[str, List[Tuple[int, str, str]]]]:
    """Возвращает {модуль: путь} и {модуль: [(lineno, target, scope)]}."""
    paths: Dict[str, Path] = {}
    imports: Dict[str, List[Tuple[int, str, str]]] = {}
    for p in sorted(root.rglob("*.py")):
        if p.name.startswith("__"):
            continue
        mod = module_dotted(p)
        paths[mod] = p
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            imports[mod] = []
            continue
        sc = ImportScanner(mod)
        sc.visit(tree)
        imports[mod] = sc.imports
    return paths, imports


def tarjan_scc(edges: List[Tuple[str, str]], nodes: Set[str]) -> List[List[str]]:
    """Итеративный Tarjan для SCC."""
    adj: Dict[str, List[str]] = {n: [] for n in nodes}
    for a, b in edges:
        adj.setdefault(a, [])
        if b in nodes:
            adj[a].append(b)
    index = 0
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    low: Dict[str, int] = {}
    sccs: List[List[str]] = []

    sys.setrecursionlimit(10000)

    def strongconnect(v: str):
        nonlocal index
        indices[v] = low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj[v]:
            if w not in indices:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    for v in sorted(nodes):
        if v not in indices:
            strongconnect(v)
    return sccs


def classify_cycles(
    imports: Dict[str, List[Tuple[int, str, str]]],
) -> Tuple[List[List[str]], List[Tuple[str, str, int, str]], List[Tuple[str, str, int, str]]]:
    """Возвращает (sccs>1 + selfloops, все рёбра циклов с классификацией, load-рёбра)."""
    all_edges: List[Tuple[str, str]] = []
    edge_info: List[Tuple[str, str, int, str]] = []
    for mod, lst in imports.items():
        for lineno, target, scope in lst:
            all_edges.append((mod, target))
            edge_info.append((mod, target, lineno, scope))
    nodes = set(imports.keys())
    sccs = [c for c in tarjan_scc(all_edges, nodes) if len(c) > 1]
    # self-loop: import самого себя
    for mod, lst in imports.items():
        for lineno, target, scope in lst:
            if target == mod:
                sccs.append([mod])
    # рёбра, участвующие в циклах
    in_cycle: Set[Tuple[str, str]] = set()
    for comp in sccs:
        members = set(comp)
        for a, b in all_edges:
            if a in members and b in members:
                in_cycle.add((a, b))
    cycle_edges = [(a, b, ln, sc) for (a, b, ln, sc) in edge_info if (a, b) in in_cycle]
    load_edges = [e for e in cycle_edges if e[3] != "lazy"]
    return sccs, cycle_edges, load_edges


def import_test(mods: List[str], timeout_s: int = 40) -> List[Tuple[str, str]]:
    """Fresh-interpreter import test для каждого модуля (H3)."""
    results = []
    py = sys.executable
    for mod in mods:
        try:
            r = subprocess.run(
                [py, "-c", f"import {mod}"],
                capture_output=True,
                timeout=timeout_s,
                text=True,
            )
            if r.returncode == 0:
                results.append((mod, "OK"))
            else:
                tail = (r.stderr or "").strip().splitlines()
                results.append((mod, f"FAIL: {(tail[-1][:140] if tail else '?')}"))
        except subprocess.TimeoutExpired:
            results.append((mod, "TIMEOUT (>%ss)" % timeout_s))
        except Exception as e:  # noqa: BLE001
            results.append((mod, f"ERROR: {e}"))
    return results


def main() -> int:
    paths, imports = scan_dir(MCP)
    sccs, cycle_edges, load_edges = classify_cycles(imports)

    all_edges: List[Tuple[str, str]] = []
    for mod, lst in imports.items():
        for _, target, _ in lst:
            all_edges.append((mod, target))

    print(f"=== E1: инвентаризация циклов {MCP} ===")
    print(f"Модулей: {len(paths)} | рёбер импортов: {len(all_edges)}")
    print(f"Циклов (SCC>1 + self-loop): {len(sccs)} | рёбер в циклах: {len(cycle_edges)}")
    load_only = [e for e in load_edges if e[3] == "module"]
    print(f"  из них load-рёбер (исполняются при импорте): {len(load_edges)} "
          f"(module/class scope); module-scope load-рёбер: {len(load_only)}")

    for i, comp in enumerate(sccs, 1):
        members = set(comp)
        edges_in = [e for e in cycle_edges if e[0] in members and e[1] in members]
        lazy_n = sum(1 for e in edges_in if e[3] == "lazy")
        load_n = len(edges_in) - lazy_n
        kind = "LOAD-CYCLE ⚠️" if load_n > 0 else "lazy-cycle"
        print(f"\n  [{i}] {kind}: {sorted(comp)}")
        for a, b, ln, sc in sorted(edges_in):
            print(f"      {a}:{ln} -> {b}  ({sc})")

    print("\n=== Fresh-interpreter import test (H3) ===")
    mods = sorted(paths.keys())
    res = import_test(mods)
    bad = [r for r in res if r[1] != "OK"]
    ok_n = sum(1 for r in res if r[1] == "OK")
    for m, st in res:
        print(f"  {m}: {st}")
    if bad:
        print(f"FAILURES: {len(bad)}")
        return 1
    print(f"Все {ok_n} модулей импортируются с чистого листа без ошибок.")
    print("\nВЕРДИКТ H3: отсутствие load-циклов = импорт не падает (runtime-safe).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)