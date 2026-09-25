"""Тесты L1 doc-reference чекера (детерминированный, near-zero FP)."""
from pathlib import Path

from src.core.doc_reference_l1 import check


def _mk(root: Path):
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "mod.py").write_text(
        "def real_func():\n    return 1\n\n\nCONST_X = 1\n", encoding="utf-8"
    )


def test_flags_real_drift_ignores_noise(tmp_path):
    _mk(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.md").write_text(
        "Use `real_func` and `CONST_X`. `ghost_func` is gone. `list` is stdlib, "
        "`some prose` has spaces, `__dunder__` ignored.\n",
        encoding="utf-8",
    )
    refs = {t for _f, _l, t in check(tmp_path)["broken"]}
    assert refs == {"ghost_func"}


def test_excludes_archive_and_venv(tmp_path):
    _mk(tmp_path)
    (tmp_path / "README.md").write_text("`ghost_func`\n", encoding="utf-8")
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "old.md").write_text("`ghost_func`\n", encoding="utf-8")
    (tmp_path / "venv" / "site-packages").mkdir(parents=True)
    (tmp_path / "venv" / "site-packages" / "p.md").write_text("`ghost_func`\n", encoding="utf-8")
    res = check(tmp_path)
    assert res["broken_count"] == 1  # только README (archive/venv исключены)


def test_ledger_docs_not_gated(tmp_path):
    _mk(tmp_path)
    (tmp_path / "KNOWN_ISSUES.md").write_text("`ghost_func`\n", encoding="utf-8")
    assert check(tmp_path)["broken_count"] == 0


def test_env_and_models_and_dotted_ok(tmp_path):
    _mk(tmp_path)
    (tmp_path / "README.md").write_text(
        "`MSCODEBASE_DATA_DIR`, `bge-m3-Q4_K_M`, `Path.rglob`, `self.value`\n",
        encoding="utf-8",
    )
    res = check(tmp_path)
    assert res["broken_count"] == 0, res["broken"]
