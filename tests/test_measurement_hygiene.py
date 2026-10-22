"""Тесты Measurement Hygiene (Layer 5): собственные замеры вне индекса.

Probe/result JSON-дампы содержат дословный текст проб-запросов — попадая
в индекс, они доминируют в BM25 (gate RED по вине измерительного стенда).
Проверяется предикат, которым пользуются все обходы индексатора
(`indexer.py:842`, `index_project_runner.py:335`, `freshness.py:93`,
`index_status.py:157`): `FileGuard.should_skip_file`.
"""

from pathlib import Path

import pytest

from src.core.indexing.file_guard import FileGuard
from src.core.system_artifacts import SystemArtifacts


def _write(path: Path, content: bytes = b'{"query": "hybrid_search_async"}') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    "rel",
    [
        "experiments/reranker_p3/rerank_probe_run1.json",
        "experiments/4A_unit_of_return/f5/results_fresh.json",
        "experiments/token_reduction/results/metrics.json",
        "experiments/4A_unit_of_return/results/f5judged/work/dump.json",
        "experiments/planted_break/results.json",
        "misc_probes/PROBE_out.json",
        "RESULTS_probe.json",
    ],
)
def test_probe_result_json_dumps_are_measurement_artifacts(rel):
    """Probe/result JSON-дампы опознаются в любом месте дерева."""
    assert SystemArtifacts.is_measurement_artifact(Path(rel)) is True


@pytest.mark.parametrize(
    "rel",
    [
        "experiments/noderag/results/summary.md",
        "experiments/closure_walk/results/graph.json",
        "experiments/4A_unit_of_return/results/f5judged/work/trace.py",
        "experiments/x/work/notes.txt",
    ],
)
def test_results_work_subtrees_are_measurement_artifacts(rel):
    """Любой файл под experiments/**/results|work — артефакт замеров."""
    assert SystemArtifacts.is_measurement_artifact(Path(rel)) is True


@pytest.mark.parametrize(
    "rel",
    [
        "src/core/search/engine.py",
        "src/core/system_artifacts.py",
        "experiments/4A_unit_of_return/f5/RESULTS_JUDGED.md",
        "package.json",
        "tsconfig.json",
        "experiments/notes.md",
    ],
)
def test_legit_files_are_not_measurement_artifacts(rel):
    """Обычный код, конфиги и writeup-доки вне results/work не трогаем."""
    assert SystemArtifacts.is_measurement_artifact(Path(rel)) is False


def test_indexer_walk_skips_probe_json_in_tree(tmp_path):
    """Probe-JSON, положенный в дерево, пропускается обходом индексатора."""
    dumped = _write(tmp_path / "experiments" / "reranker_p3" / "probe_run9.json")
    legit = _write(tmp_path / "src" / "engine.py", b"def hybrid_search_async():\n    pass\n")
    guard = FileGuard(tmp_path)
    assert guard.should_skip_file(dumped) is True
    assert guard.should_skip_file(legit) is False


def test_indexer_walk_skips_results_work_files(tmp_path):
    """Файлы под experiments/**/results|work пропускаются (любое расширение)."""
    junk = _write(tmp_path / "experiments" / "noderag" / "results" / "hits.md", b"# hits")
    work = _write(tmp_path / "experiments" / "x" / "work" / "trace.py", b"x = 1\n")
    guard = FileGuard(tmp_path)
    assert guard.should_skip_file(junk) is True
    assert guard.should_skip_file(work) is True


def test_is_system_path_covers_measurement_layer(tmp_path):
    """Единый финальный guard тоже отсекает замеры."""
    assert SystemArtifacts.is_system_path(Path("experiments/a/results/b.json")) is True
    assert SystemArtifacts.is_system_path(Path("src/a.py")) is False
