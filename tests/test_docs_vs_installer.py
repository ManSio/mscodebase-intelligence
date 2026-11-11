"""Red-first tests for the docs=code guard (G7).

The guard exists because documentation drifted from `install.py` and nobody
noticed: `docs/*/INSTALL.md` shipped `install.py --uninstall`, a flag that never
existed. These tests pin both directions: a stale flag must be reported, and the
real tree must pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_docs_vs_installer as guard  # noqa: E402


def test_real_tree_passes_and_checks_something():
    problems, checked = guard.check(REPO)
    assert checked > 0, "guard found no flag references — it would pass vacuously"
    assert problems == [], problems


def test_installed_flag_vocabulary_is_complete():
    flags = guard.install_flags(REPO)
    for expected in ("--print-config", "--doctor", "--clean", "--dry-run", "--json",
                     "--with-models", "--no-zed", "--sync-only", "--client", "--python"):
        assert expected in flags, f"{expected} missing from install.py"


def test_unknown_flag_in_docs_is_reported(tmp_path):
    (tmp_path / "install.py").write_text('KNOWN = "--doctor"\n', encoding="utf-8")
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "README.md").write_text("run `install.py --uninstall`\n", encoding="utf-8")
    (tmp_path / "docs" / "en" / "INSTALL.md").write_text("`install.py --doctor`\n", encoding="utf-8")
    (tmp_path / "docs" / "en" / "CLIENTS.md").write_text(
        "\n".join(f"--client {c}" for c in guard.CLIENTS), encoding="utf-8"
    )

    problems, checked = guard.check(tmp_path)
    assert checked == 2
    assert any("--uninstall" in p for p in problems), problems


def test_unknown_client_in_docs_is_reported(tmp_path):
    (tmp_path / "install.py").write_text('KNOWN = "--print-config"\n', encoding="utf-8")
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "docs" / "en" / "CLIENTS.md").write_text(
        "\n".join(f"--client {c}" for c in guard.CLIENTS) + "\n--client emacs\n",
        encoding="utf-8",
    )
    problems, _checked = guard.check(tmp_path)
    assert any("emacs" in p for p in problems), problems


def test_empty_docs_corpus_is_not_a_pass(tmp_path):
    (tmp_path / "install.py").write_text("", encoding="utf-8")
    problems, checked = guard.check(tmp_path)
    assert checked == 0
    assert problems == ["no documentation found to check"]
