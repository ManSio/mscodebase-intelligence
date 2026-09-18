# -*- coding: utf-8 -*-
"""Bootstrap Pipeline Step 3: dynamic trace + TESTS-рёбра в PropertyGraph.

Единая команда ``bootstrap`` (run_bootstrap_pipeline) связывает B1 (детектор
сущностей), A2 (TESTS-рёбра из trace_result.json) и шаг 3 (реальный запуск
pytest с плагином bootstrap_trace_plugin.py).

Оркестрация (все модули read-only/идемпотентны, concurrency-safe):
    1. resolve_src_root()  → корень исходников (без хардкода src/).
    2. detect_entities()   → data structures статистика (B1).
    3. pytest subprocess с ``-p src.core.bootstrap_trace_plugin``,
       env TRACE_SRC_ROOT/TRACE_OUT → trace_result.json в временном каталоге.
    4. build_tests_edges() → TESTS-рёбра в PropertyGraph (A2), target-граф
       по умолчанию = get_graph_db_path(project_root).

Windows: subprocess через Popen(stdout=PIPE, stderr=DEVNULL) + communicate
(timeout) — безопасно из потоков (правило §5.16, без capture_output deadlock).

Ошибки: pytest может вернуть ненулевой код (упавшие тесты) — trace всё равно
пишется в pytest_sessionfinish; ненулевой код не считается провалом pipeline.
Провал = нет trace_result.json или брошенное исключение subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from src.core.bootstrap_entities import (
    EntitiesBootstrapStats,
    detect_entities,
    resolve_src_root,
)
from src.core.bootstrap_tests import TestsBootstrapStats, build_tests_edges

DEFAULT_TRACE_TIMEOUT = float(os.environ.get("MSCODEBASE_BOOTSTRAP_TRACE_TIMEOUT", "600.0"))


@dataclass
class BootstrapPipelineStats:
    """Сводный отчёт прогона `bootstrap`.

    Поля сгруппированы по шагам: сущности (B1), trace (шаг 3), граф (A2).
    """

    project_root: str = ""
    src_root: Optional[str] = None
    entities: EntitiesBootstrapStats = field(default_factory=EntitiesBootstrapStats)
    tests_total: int = 0
    tests_linked: int = 0
    linked_pct: float = 0.0
    unique_src_functions: int = 0
    trace_file: Optional[str] = None
    pytest_exit_code: Optional[int] = None
    trace_seconds: float = 0.0
    graph: TestsBootstrapStats = field(default_factory=TestsBootstrapStats)

    def as_dict(self) -> Dict:
        return {
            "project_root": self.project_root,
            "src_root": self.src_root,
            "entities": self.entities.as_dict(),
            "trace": {
                "tests_total": self.tests_total,
                "tests_linked": self.tests_linked,
                "linked_pct": round(self.linked_pct, 1),
                "unique_src_functions": self.unique_src_functions,
                "trace_file": self.trace_file,
                "pytest_exit_code": self.pytest_exit_code,
                "trace_seconds": round(self.trace_seconds, 1),
            },
            "graph": self.graph.as_dict(),
        }


def _build_trace_command(
    project_root: Path,
    src_root: Path,
    trace_out: Path,
    extra_pytest_args: Optional[List[str]],
) -> List[str]:
    """Команда pytest с плагином (пишет trace) — без env, чтобы не тянуть PYTHONPATH."""

    python = os.environ.get("MSCODEBASE_BOOTSTRAP_PYTHON", sys.executable)
    cmd = [python, "-m", "pytest", str(project_root), "-p", "src.core.bootstrap_trace_plugin"]
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)
    return cmd


def _plugin_importable(python: str, repo_root: Path, cwd: Path) -> bool:
    """Может ли subprocess-интерпретатор импортировать плагин из cwd проекта.

    Критично: pytest стартует с cwd=project_root, а не репо. Проверка импорта
    обязана происходить с тем же cwd — иначе ложно-положительный True (из репо
    src/ всегда виден) и pytest упадёт на невидимом плагине.
    """
    import subprocess as _sp

    try:
        res = _sp.run(
            [python, "-c", "import src.core.bootstrap_trace_plugin"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(cwd),
            creationflags=_sp.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception:  # noqa: BLE001 — нет интерпретатора/таймаут → считаем не-импортируемым
        return False
    return res.returncode == 0


def _run_trace(
    project_root: Path,
    src_root: Path,
    trace_out: Path,
    extra_pytest_args: Optional[List[str]],
    timeout: float,
) -> tuple[int, float]:
    """Запускает pytest-трассу; возвращает (exit_code, seconds).

    Возвращает всегда (exit, secs) — даже при ненулевом exit (упавшие тесты)
    или по таймауту: caller проверяет наличие trace_result.json.
    """
    cmd = _build_trace_command(project_root, src_root, trace_out, extra_pytest_args)

    env = dict(os.environ)
    env["TRACE_SRC_ROOT"] = str(src_root)
    env["TRACE_OUT"] = str(trace_out)

    # Плагин живёт в установленном пакете mscodebase (venv расширения). PYTHONPATH
    # с корнем репо нужен ТОЛЬКО в dev когда пакет не установлен (-e). Добавлять
    # его вслепую НЕЛЬЗЯ: корень содержит src/ и перебивает src/ трассируемого
    # проекта (классический namespace shadowing). Проверяем импорт заранее.
    repo_root = Path(__file__).resolve().parents[2]
    if not _plugin_importable(cmd[0], repo_root, cwd=project_root):
        imports = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = imports + (";" if imports else "") + str(repo_root)

    creationflags = 0
    if os.name == "nt":
        creationflags |= subprocess.CREATE_NO_WINDOW

    start = __import__("time").monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Bootstrap trace: interpreter not found: {cmd[0]!r}. "
            f"Set MSCODEBASE_BOOTSTRAP_PYTHON to a python with pytest."
        ) from exc

    try:
        proc.communicate(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — таймаут/прочее: обернуть, не ронять pipeline
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"Bootstrap trace: pytest failed/stopped: {exc}") from exc
    finally:
        elapsed = __import__("time").monotonic() - start

    return proc.returncode, elapsed


def run_bootstrap_pipeline(
    project_root: Path,
    src_dir: Optional[Path] = None,
    graph_path: Optional[Path] = None,
    extra_pytest_args: Optional[List[str]] = None,
    trace_timeout: Optional[float] = None,
) -> BootstrapPipelineStats:
    """Полный Step 3: detect_entities + trace + TESTS-рёбра в PropertyGraph.

    Args:
        project_root: корень проекта.
        src_dir: явный корень исходников (иначе resolve_src_root авто-определяет).
        graph_path: целевой PropertyGraph (default get_graph_db_path(project_root)).
        extra_pytest_args: дополнительные аргументы pytest (например
            ['-k', 'smoke', '-x']); передаются ПОСЛЕ пути и -p.
        trace_timeout: таймаут на прогон pytest в секундах (default 600).

    Returns:
        BootstrapPipelineStats (JSON-сериализуемый через as_dict()).
    """
    root = Path(project_root).resolve()

    stats = BootstrapPipelineStats()
    stats.project_root = str(root)

    src_root = resolve_src_root(root, src_dir)
    stats.src_root = str(src_root) if src_root else None
    if src_root is None:
        return stats

    stats.entities = detect_entities(root, src_dir=src_root)


    trace_out = Path(
        tempfile.gettempdir()
    ) / f"bootstrap_trace_{root.name}_{os.getpid()}.json"

    exit_code, seconds = _run_trace(
        root,
        src_root,
        trace_out,
        extra_pytest_args,
        float(trace_timeout if trace_timeout is not None else DEFAULT_TRACE_TIMEOUT),
    )
    stats.pytest_exit_code = exit_code
    stats.trace_seconds = seconds

    if not trace_out.exists():
        return stats

    stats.trace_file = str(trace_out)

    import json as _json

    trace = _json.loads(trace_out.read_text(encoding="utf-8"))
    stats.tests_total = len(trace)
    stats.tests_linked = sum(1 for funcs in trace.values() if funcs)
    stats.linked_pct = (
        100.0 * stats.tests_linked / max(1, stats.tests_total)
        if stats.tests_total
        else 0.0
    )
    stats.unique_src_functions = len({f for funcs in trace.values() for f in funcs})

    if graph_path is None:
        from src.core.artifact_paths import get_graph_db_path

        graph_path = get_graph_db_path(root)
    from src.core.graph import PropertyGraph

    graph_db = PropertyGraph(graph_path)
    # На чистом графе Function/METHOD узлов нет — build_tests_edges матчит
    # trace по ним. Поднимаем статические узлы до матчинга.
    from src.core.bootstrap_tests import index_src_functions

    index_src_functions(src_root, graph_db)
    stats.graph = build_tests_edges(trace, root, graph_db, src_dir=src_root)

    return stats
