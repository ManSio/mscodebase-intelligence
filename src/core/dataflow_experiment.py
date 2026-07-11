"""
DataFlow Experiment v3 — мульти-проектный замер.

Запускает 4 сценария на нескольких проектах и сводит результаты
в единую таблицу. Позволяет увидеть, как плотность DATA_FLOW edges
меняется в зависимости от типа проекта.

Сценарии:
  A — ASSIGNED_FROM (интра-процедурный, все присваивания с отслеживанием)
  B — RETURNS_TO (межпроцедурный, возвращаемые значения)
  C — Data Provenance (цепочки: a → b → c)
  D — Taint source→sink

Использование:
    python -m src.core.dataflow_experiment                    # свой проект
    python -m src.core.dataflow_experiment --paths dir1 dir2  # чужие проекты
"""

from __future__ import annotations

import ast
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.parser import CodeParser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("dataflow_exp")


# ── Источники (Source) — откуда данные приходят ─────────

_SOURCE_PATTERNS: Set[str] = {
    # HTTP / API
    "request", "request.json", "request.form", "request.args",
    "request.headers", "request.cookies", "request.files",
    "request.data", "request.values", "request.get_json",
    "flask.request", "fastapi.Request", "starlette.requests",
    "django.http.request",
    # Ввод
    "input(", "sys.stdin", "sys.argv", "os.environ",
    "environ.get", "os.getenv", "getenv",
    "argparse.", "click.argument", "click.option",
    # Файлы
    "open(", "read(", "readlines(", "read_text", "read_bytes",
    "Path.read", "load(",  # json.load, yaml.load
    # Параметры
    "query_params", "path_params", "kwargs.get",
    "kwargs[", "args[",
}

# ── Стоки (Sink) ────────────────────────────────────────

_SINK_PATTERNS: Set[str] = {
    "execute(", "executemany(", "executescript(",
    "cursor.execute", "connection.execute",
    "db.execute", "session.execute", "raw_sql",
    "os.system(", "os.popen(", "subprocess.call(",
    "subprocess.run(", "subprocess.Popen(",
    "write(", "writelines(", "write_text", "write_bytes",
    "dump(",
    "eval(", "exec(", "compile(",
    "yaml.load(", "pickle.loads(", "pickle.load(",
    "render_template_string",
    "requests.post", "requests.get", "httpx.post",
    "httpx.get",
}


# ── Анализаторы ─────────────────────────────────────────

class Analyzer:
    """Статистический анализатор Python проекта."""

    def __init__(self, root: Path):
        self.root = root
        self.files: List[Path] = []
        self._discover()
        self.lines = 0
        self._count_lines()

    def _discover(self):
        exclude = {"venv", ".venv", "__pycache__", ".git", "node_modules",
                   "dist", "build", ".mypy_cache", ".tox", "htmlcov",
                   ".pytest_cache", ".ruff_cache", "site-packages"}
        for f in self.root.rglob("*.py"):
            parts = set(f.relative_to(self.root).parts)
            if not exclude & parts and not any(
                p.startswith(".") for p in f.relative_to(self.root).parts
                if p != self.root.name
            ):
                self.files.append(f)

    def _count_lines(self):
        for f in self.files:
            try:
                self.lines += len(f.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                pass

    def name(self) -> str:
        return self.root.name

    # ── Сценарий A: ASSIGNED_FROM ───────────────────────

    def scenario_a(self) -> Dict:
        """ASSIGNED_FROM edges — интра-процедурные.

        Использует Tree-sitter CodeParser (production-версия).
        """
        parser = CodeParser()
        total_edges = 0
        total_time = 0.0
        files_with = 0
        max_edges_file = ""
        max_edges = 0

        for f in self.files:
            if f.suffix != ".py":
                continue
            t0 = time.monotonic()
            edges = parser.extract_assignments(f)
            elapsed = (time.monotonic() - t0) * 1000
            total_time += elapsed
            total_edges += len(edges)
            if edges:
                files_with += 1
                if len(edges) > max_edges:
                    max_edges = len(edges)
                    max_edges_file = f.name

        edges_per_kloc = (total_edges / self.lines * 1000) if self.lines else 0
        return {
            "label": "A ASSIGNED_FROM (ts)",
            "edges": total_edges,
            "/KLOC": round(edges_per_kloc, 1),
            "ms": round(total_time, 1),
            "ms/file": round(total_time / max(len(self.files), 1), 2),
            "%files": round(files_with / len(self.files) * 100, 1) if self.files else 0,
            "max_file": f"{max_edges_file}({max_edges})",
            "verdict": "🟢" if edges_per_kloc > 20 else "🟡" if edges_per_kloc > 5 else "🔴",
        }

    # ── Сценарий D: Taint source→sink ───────────────────

    def scenario_d(self) -> Dict:
        """Taint source → sink."""
        total_src = 0
        total_snk = 0
        total_edges = 0
        total_time = 0.0
        files_with = 0

        for f in self.files:
            t0 = time.monotonic()
            src, snk, edges = self._taint(f)
            elapsed = (time.monotonic() - t0) * 1000
            total_time += elapsed
            total_src += len(src)
            total_snk += len(snk)
            total_edges += len(edges)
            if edges:
                files_with += 1

        edges_per_kloc = (total_edges / self.lines * 1000) if self.lines else 0
        return {
            "label": "D Taint S→S",
            "edges": total_edges,
            "/KLOC": round(edges_per_kloc, 1),
            "ms": round(total_time, 1),
            "ms/file": round(total_time / max(len(self.files), 1), 2),
            "%files": round(files_with / len(self.files) * 100, 1) if self.files else 0,
            "sources": total_src,
            "sinks": total_snk,
            "verdict": "🟢" if edges_per_kloc > 20 else "🟡" if edges_per_kloc > 2 else "🔴",
        }

    # ── Сценарий C: Data Provenance ─────────────────────

    def scenario_c(self) -> Dict:
        """Цепочки: a = f(b); c = g(a) —> a→b, c→a.

        Измеряет среднюю глубину цепочек и их количество.
        """
        total_chains = 0
        total_depth = 0
        total_time = 0.0
        files_with = 0

        for f in self.files:
            t0 = time.monotonic()
            chains = self._provenance_chains(f)
            elapsed = (time.monotonic() - t0) * 1000
            total_time += elapsed
            if chains:
                files_with += 1
                for depth, count in chains.items():
                    total_chains += count
                    total_depth += depth * count

        avg_depth = total_depth / total_chains if total_chains else 0
        chains_per_kloc = (total_chains / self.lines * 1000) if self.lines else 0
        return {
            "label": "C Provenance",
            "chains": total_chains,
            "/KLOC": round(chains_per_kloc, 1),
            "avg_depth": round(avg_depth, 1),
            "ms": round(total_time, 1),
            "ms/file": round(total_time / max(len(self.files), 1), 2),
            "%files": round(files_with / len(self.files) * 100, 1) if self.files else 0,
            "verdict": "🟢" if chains_per_kloc > 20 else "🟡" if chains_per_kloc > 3 else "🔴",
        }

    # ── Сценарий B: RETURNS_TO ─────────────────────────

    def scenario_b(self) -> Dict:
        """RETURNS_TO. Простой замер: функции с return."""
        funcs_with_return = 0
        total_funcs = 0
        total_time = 0.0

        for f in self.files:
            t0 = time.monotonic()
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    total_funcs += 1
                    for child in ast.walk(node):
                        if isinstance(child, ast.Return) and child.value is not None:
                            funcs_with_return += 1
                            break

            elapsed = (time.monotonic() - t0) * 1000
            total_time += elapsed

        pct = funcs_with_return / total_funcs * 100 if total_funcs else 0
        ret_per_kloc = (funcs_with_return / self.lines * 1000) if self.lines else 0
        return {
            "label": "B RETURNS_TO",
            "funcs_return": funcs_with_return,
            "total_funcs": total_funcs,
            "%funcs": round(pct, 1),
            "/KLOC": round(ret_per_kloc, 1),
            "ms": round(total_time, 1),
            "ms/file": round(total_time / max(len(self.files), 1), 2),
            "verdict": "🟢" if ret_per_kloc > 3 else "🟡" if ret_per_kloc > 0.5 else "🔴",
        }

    # ── Внутренние анализаторы ─────────────────────────

    def _intra_assign(self, file_path: Path) -> List[Tuple[str, str, str]]:
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []
        edges = []
        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assigned: Set[str] = set()
            for stmt in func_node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            if isinstance(stmt.value, ast.Name):
                                if stmt.value.id in assigned:
                                    edges.append((stmt.value.id, target.id, "ASSIGNED_FROM"))
                                assigned.add(target.id)
                            elif isinstance(stmt.value, ast.Call):
                                for arg in stmt.value.args:
                                    if isinstance(arg, ast.Name) and arg.id in assigned:
                                        edges.append((arg.id, target.id, "ASSIGNED_FROM"))
                                        break
                                assigned.add(target.id)
                            elif not isinstance(stmt.value, ast.Constant):
                                refs = self._get_name_refs(stmt.value)
                                if refs:
                                    for ref in refs:
                                        if ref in assigned:
                                            edges.append((ref, target.id, "ASSIGNED_FROM"))
                                    assigned.add(target.id)
                elif isinstance(stmt, ast.AugAssign):
                    if isinstance(stmt.target, ast.Name):
                        if isinstance(stmt.value, ast.Name) and stmt.value.id in assigned:
                            edges.append((stmt.value.id, stmt.target.id, "ASSIGNED_FROM"))
                        assigned.add(stmt.target.id)
        return edges

    def _taint(self, file_path: Path) -> Tuple[List[str], List[str], List[Tuple[str, str, str]]]:
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except Exception:
            return [], [], []
        sources: List[str] = []
        sinks: List[str] = []
        edges: List[Tuple[str, str, str]] = []
        tainted: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        val = ast.unparse(node.value)
                        if self._is_source(val):
                            sources.append(f"{file_path.name}:{node.lineno}")
                            tainted.add(target.id)
                        elif isinstance(node.value, ast.Name) and node.value.id in tainted:
                            edges.append((node.value.id, target.id, "DATA_FLOW"))
                            tainted.add(target.id)
                        elif isinstance(node.value, ast.Call):
                            for arg in node.value.args:
                                if isinstance(arg, ast.Name) and arg.id in tainted:
                                    edges.append((arg.id, target.id, "DATA_FLOW"))
                                    tainted.add(target.id)
                                    break
            if isinstance(node, ast.Call):
                func_str = ast.unparse(node.func)
                sink_type = self._is_sink(func_str)
                if sink_type:
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id in tainted:
                            sinks.append(f"{file_path.name}:{node.lineno}:{func_str}")
                            edges.append((arg.id, func_str, f"SINK_{sink_type}"))
        return sources, sinks, edges

    def _provenance_chains(self, file_path: Path) -> Dict[int, int]:
        """Строит цепочки присваиваний и замеряет их глубину.

        Returns:
            {глубина: количество_цепочек}
        """
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
        depths: Dict[int, int] = defaultdict(int)

        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Строим граф зависимостей переменных
            var_deps: Dict[str, Set[str]] = defaultdict(set)  # var -> {depends_on}

            for stmt in func_node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            deps = set()
                            for child in ast.walk(stmt.value):
                                if isinstance(child, ast.Name):
                                    deps.add(child.id)
                            var_deps[target.id] = deps - {target.id}

            # Для каждой переменной считаем глубину цепочки
            def _depth(var: str, seen: Set[str]) -> int:
                if var in seen:
                    return 0
                deps = var_deps.get(var, set())
                if not deps:
                    return 0
                seen = seen | {var}
                max_d = 0
                for dep in deps:
                    d = _depth(dep, seen)
                    if d > max_d:
                        max_d = d
                return max_d + 1

            for var in var_deps:
                d = _depth(var, set())
                if d > 0:
                    depths[d] += 1

        return dict(depths)

    @staticmethod
    def _get_name_refs(node: ast.AST) -> List[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        return [c.id for c in ast.walk(node) if isinstance(c, ast.Name)]

    @staticmethod
    def _is_source(code_str: str) -> bool:
        cl = code_str.lower().strip()
        return any(p in cl for p in _SOURCE_PATTERNS)

    @staticmethod
    def _is_sink(func_str: str) -> Optional[str]:
        fl = func_str.lower()
        for pat, label in [
            ({"execute", "executemany", "executescript"}, "SQL"),
            ({"os.system", "os.popen", "subprocess.call", "subprocess.run", "subprocess.Popen"}, "SHELL"),
            ({"eval", "exec", "compile", "yaml.load", "pickle.loads"}, "CODE"),
        ]:
            if any(p in fl for p in pat):
                return label
        if fl == "open" or fl.endswith(".open"):
            return "FILE"
        return None


# ── Мульти-проектный замер ─────────────────────────────

class MultiProjectExperiment:
    """Запускает все сценарии на нескольких проектах."""

    def __init__(self, roots: List[Path]):
        self.analyzers = [Analyzer(r) for r in roots if r.exists()]

    def run(self):
        logger.info("=" * 80)
        logger.info("DATAFLOW EXPERIMENT v3 — Мульти-проектный замер")
        logger.info(f"{'=' * 80}\n")

        scenarios = [
            ("A — ASSIGNED_FROM", lambda a: a.scenario_a()),
            ("B — RETURNS_TO", lambda a: a.scenario_b()),
            ("C — Data Provenance", lambda a: a.scenario_c()),
            ("D — Taint S→S", lambda a: a.scenario_d()),
        ]

        for sc_name, sc_fn in scenarios:
            logger.info(f"\n{'─' * 80}")
            logger.info(f"📊 {sc_name}")
            logger.info(f"{'─' * 80}")

            rows = []
            for a in self.analyzers:
                r = sc_fn(a)
                r["project"] = a.name()
                r["files"] = len(a.files)
                r["lines"] = a.lines
                rows.append(r)

            # Таблица
            keys = rows[0].keys() if rows else {}
            # Печатаем только ключевые колонки
            hdr = f"{'Проект':<22} {'Файлы':>6} {'Строки':>7} {'Edges':>7} {'/KLOC':>7} {'ms':>7} {'%ф':>5}  Вердикт"
            logger.info(f"\n{hdr}")
            logger.info("-" * 80)
            for r in sorted(rows, key=lambda x: -x.get("/KLOC", 0)):
                logger.info(
                    f"{r['project']:<22} {r.get('files', 0):>6} "
                    f"{r.get('lines', 0):>7} {r.get('edges', r.get('chains', 0)):>7} "
                    f"{r.get('/KLOC', 0):>7} {r.get('ms', 0):>7.0f} "
                    f"{r.get('%files', 0):>5}  {r.get('verdict', '?')}"
                )
                # extra info
                if "sources" in r or "sinks" in r:
                    logger.info(
                        f"{'':22}       sources={r.get('sources', 0)} "
                        f"sinks={r.get('sinks', 0)}"
                    )
                if "avg_depth" in r:
                    logger.info(
                        f"{'':22}       avg_depth={r['avg_depth']} "
                        f"max_depth={max(r.get('chains', 0), 1)}"
                    )


# ── Точка входа ─────────────────────────────────────────

if __name__ == "__main__":
    # Собираем пути для анализа
    paths = []

    # 1. Свой проект
    our_root = Path(__file__).resolve().parent.parent.parent
    paths.append(our_root)

    # 2. Если указаны --paths, добавляем их
    if "--paths" in sys.argv:
        idx = sys.argv.index("--paths")
        for p in sys.argv[idx + 1:]:
            paths.append(Path(p))

    # 3. Ищем другие Python проекты в HOME
    home = Path.home()
    for candidate in [
        home / ".local" / "bin",
        home / "AppData" / "Local" / "Programs",
        home / "projects",
        home / "code",
    ]:
        if candidate.exists():
            for sub in candidate.iterdir():
                if sub.is_dir() and (sub / "setup.py").exists() or (sub / "pyproject.toml").exists():
                    if sub not in paths:
                        paths.append(sub)

    logger.info(f"Целевые проекты ({len(paths)}):")
    for p in paths:
        exists = "✅" if p.exists() else "❌"
        logger.info(f"  {exists} {p}")

    # Отфильтровываем существующие
    paths = [p for p in paths if p.exists()]

    if not paths:
        logger.error("Нет доступных проектов для анализа")
        sys.exit(1)

    exp = MultiProjectExperiment(paths)
    exp.run()
