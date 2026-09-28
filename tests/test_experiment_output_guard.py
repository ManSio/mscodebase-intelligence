"""Guard: выводы экспериментов не индексируются (experiments/**/results|work).

Замер 2026-09-28: 3127/15426 чанков (20.3%) — мусор (ctx-дампы, judged_raw).
Git-трекинг не трогаем (§17) — только индекс.
"""
from __future__ import annotations

from pathlib import Path

from src.core.indexing.file_guard import FileGuard
from src.core.system_artifacts import SystemArtifacts


def test_results_and_work_excluded():
    assert SystemArtifacts.is_experiment_output(
        Path("experiments/4A_unit_of_return/results/f5judged/judged_raw.json")
    )
    assert SystemArtifacts.is_experiment_output(
        Path("experiments/4A_unit_of_return/results/f5judged/work/ctx_F5S-01_A.txt")
    )
    assert SystemArtifacts.is_experiment_output(
        Path("D:/Project/MSCodeBase/experiments/noderag/results/r.json")
    )


def test_sources_and_frozen_kept():
    assert not SystemArtifacts.is_experiment_output(
        Path("experiments/4A_unit_of_return/run_experiment.py")
    )
    assert not SystemArtifacts.is_experiment_output(
        Path("experiments/4A_unit_of_return/frozen/f5/queries.jsonl")
    )
    assert not SystemArtifacts.is_experiment_output(Path("src/core/search/engine.py"))
    assert not SystemArtifacts.is_experiment_output(Path("docs/en/SEARCH_PIPELINE.md"))


def test_fileguard_skips_experiment_output(tmp_path):
    guard = FileGuard(tmp_path)
    out = tmp_path / "experiments" / "x" / "results" / "r.json"
    out.parent.mkdir(parents=True)
    out.write_text('{"a": 1}', encoding="utf-8")
    assert guard.is_safe_to_index(out) is False

    src = tmp_path / "experiments" / "x" / "run.py"
    src.write_text("x = 1\n", encoding="utf-8")
    assert guard.is_safe_to_index(src) is True
