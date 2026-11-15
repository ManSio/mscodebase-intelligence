"""Tests for the docs->code reference gate (G7, mechanical form).

Every test feeds a crafted unified diff (`--diff-file`) or a throwaway git repo,
so the gate is exercised exactly as CI runs it without depending on this
repository's history.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_docs_refs.py"


def _diff(path: str, added: list[str], start: int = 1) -> str:
    body = "".join(f"+{line}\n" for line in added)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +{start},{len(added)} @@\n"
        f"{body}"
    )


def _run(tmp: Path, diff_text: str, *extra: str) -> tuple[int, str]:
    diff_file = tmp / "change.diff"
    diff_file.write_text(diff_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp), "--diff-file", str(diff_file), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def _make_repo(tmp: Path) -> None:
    (tmp / "src" / "core" / "search").mkdir(parents=True)
    (tmp / "src" / "core" / "search" / "engine.py").write_text(
        "class Searcher:\n"
        "    # old Searcher notes\n"
        "    def search(self):\n"
        "        return 1\n", encoding="utf-8"
    )
    (tmp / "src" / "core" / "embedder.py").write_text(
        "import os\n\n\ndef width():\n"
        '    return int(os.getenv("ONNX_FIXED_PADDING", "0") or 0)\n', encoding="utf-8"
    )
    (tmp / "src" / "core" / "settings.py").write_text(
        "import os\n\n"
        'DOCS_MARGIN = float(os.getenv("MSCODEBASE_DOCS_MARGIN", "4.0"))\n', encoding="utf-8"
    )
    (tmp / "install.py").write_text(
        'def _clean_cli(argv):\n    return 0\n\n\nFLAG = "--clean"\nFLAG2 = "--with-models"\n',
        encoding="utf-8",
    )
    (tmp / ".env.example").write_text("MSCODEBASE_DOCS_MARGIN=4.0\n", encoding="utf-8")
    (tmp / "docs" / "en").mkdir(parents=True)
    (tmp / "docs" / "archive").mkdir(parents=True)
    (tmp / "experiments" / "e1").mkdir(parents=True)


def _git_repo(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "g"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, env=env)

    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    return repo


def _run_in(repo: Path, diff_text: str) -> tuple[int, str]:
    diff_file = repo / "change.diff"
    diff_file.write_text(diff_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--diff-file", str(diff_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


# ─── basic acceptance / rejection ────────────────────────────────────────


def test_no_markdown_changes_is_reported_not_silent(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, "")
    assert code == 0
    assert "no markdown additions" in out


def test_real_path_is_accepted(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py`."]))
    assert code == 0, out
    assert "ok: docs/en/x.md -> path src/core/search/engine.py" in out


def test_declared_symbol_is_accepted(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Entry: `src/core/search/engine.py::Searcher`."]))
    assert code == 0, out
    assert "::Searcher" in out


def test_symbol_that_is_only_mentioned_is_rejected(tmp_path):
    """`Searcher` also appears in a comment; only a declaration counts."""
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py::notes`."]))
    assert code == 1, out


def test_keyword_symbol_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py::return`."]))
    assert code == 1, out


def test_real_line_number_is_accepted(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Limit: `src/core/search/engine.py:3`."]))
    assert code == 0, out


def test_line_past_end_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py:999`."]))
    assert code == 1, out


def test_fabricated_path_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/nope.py`."]))
    assert code == 1, out
    assert "no verifiable code reference" in out


def test_fabricated_symbol_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py::make_coffee`."]))
    assert code == 1, out


# ─── installer flags ─────────────────────────────────────────────────────


def test_unknown_installer_flag_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Run `install.py --uninstall`."]))
    assert code == 1, out


def test_known_installer_flag_is_accepted(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Run `install.py --clean`."]))
    assert code == 0, out


def test_unknown_flag_does_not_hide_a_valid_reference(tmp_path):
    """An early unknown flag must not abort the rest of the line."""
    _make_repo(tmp_path)
    code, out = _run(
        tmp_path,
        _diff("docs/en/x.md", ["Run `install.py --uninstall` or see `src/core/search/engine.py`."]),
    )
    assert code == 0, out
    assert "path src/core/search/engine.py" in out


# ─── environment settings ────────────────────────────────────────────────


def test_invented_env_name_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Set `MSCODEBASE_FAKE_FLAG=true`."]))
    assert code == 1, out


def test_env_prefix_of_a_real_name_is_rejected(tmp_path):
    """Substring match would accept this: `MSCODEBASE_DOCS` is a prefix."""
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Set `MSCODEBASE_DOCS=1`."]))
    assert code == 1, out


def test_real_env_name_is_accepted(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Tune `MSCODEBASE_DOCS_MARGIN`."]))
    assert code == 0, out


def test_setting_without_the_project_prefix_is_accepted(tmp_path):
    """`ONNX_FIXED_PADDING` is read by the code but has no MSCODEBASE_ prefix."""
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Set `ONNX_FIXED_PADDING=512`."]))
    assert code == 0, out


# ─── exemptions and paths ───────────────────────────────────────────────


def test_exempt_archive_passes_without_reference(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/archive/old.md", ["Historical note, no reference."]))
    assert code == 0, out
    assert "exempt" in out


def test_experiments_are_exempt(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("experiments/e1/REPORT.md", ["Run log, no reference."]))
    assert code == 0, out


def test_translated_changelog_is_exempt(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/ru/CHANGELOG.md", ["## 3.5.1 — fix"]))
    assert code == 0, out


def test_path_traversal_does_not_count(tmp_path):
    _make_repo(tmp_path)
    outside = tmp_path.parent / "outside_secret.py"
    outside.write_text("SECRET = 1\n", encoding="utf-8")
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/../../outside_secret.py`."]))
    assert code == 1, out


def test_reference_to_a_file_absent_from_the_tree_is_rejected(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["Moved to `src/core/gone.py`."]))
    assert code == 1, out


def test_homoglyph_path_is_rejected(tmp_path):
    """Attack: look-alike Cyrillic letter inside a path."""
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/enginе.py`."]))
    assert code == 1, out


def test_quoted_non_ascii_path_in_diff_is_parsed(tmp_path):
    """git C-quotes non-ASCII paths; the file must still be judged."""
    _make_repo(tmp_path)
    quoted = '"b/docs/en/\\320\\244.md"'
    diff = (
        "diff --git a/docs/en/x.md b/docs/en/x.md\n"
        "--- a/docs/en/x.md\n"
        f"+++ {quoted}\n"
        "@@ -0,0 +1,1 @@\n"
        "+Новый текст без ссылки.\n"
    )
    code, out = _run(tmp_path, diff)
    assert code == 1, out
    assert "no verifiable code reference" in out


def test_junction_to_outside_the_repo_is_rejected(tmp_path):
    if sys.platform != "win32":
        pytest.skip("junction is a Windows primitive")
    _make_repo(tmp_path)
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "src" / "linked"), str(outside)],
                   capture_output=True, text=True)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/linked/secret.py`."]))
    assert code == 1, out


# ─── cosmetic edits ─────────────────────────────────────────────────────


def test_cosmetic_edit_to_a_file_that_already_cites_code_passes(tmp_path):
    repo = _git_repo(
        tmp_path,
        {"docs/en/a.md": "Entry: `src/main.py`.\n", "src/main.py": "def main():\n    return 0\n"},
    )
    code, out = _run_in(repo, _diff("docs/en/a.md", ["Fixed a typo in the prose."]))
    assert code == 0, out
    assert "cosmetic" in out


def test_moved_line_with_existing_numbers_is_not_a_new_claim(tmp_path):
    old = "Counts: missing_widget=0, implemented=5\n"
    repo = _git_repo(
        tmp_path,
        {"docs/en/a.md": "Entry: `src/main.py`.\n\n" + old,
         "src/main.py": "def main():\n    return 0\n"},
    )
    code, out = _run_in(repo, _diff("docs/en/a.md", ["Counts: missing_widget=0, implemented=5"]))
    assert code == 0, out


def test_new_number_in_a_citing_file_still_needs_a_reference(tmp_path):
    repo = _git_repo(
        tmp_path,
        {"docs/en/a.md": "Entry: `src/main.py`.\n", "src/main.py": "def main():\n    return 0\n"},
    )
    code, out = _run_in(repo, _diff("docs/en/a.md", ["Now 2507 tests pass."]))
    assert code == 1, out
    assert "new claim" in out


def test_prose_in_a_file_that_never_cited_code_is_rejected(tmp_path):
    repo = _git_repo(tmp_path, {"docs/en/a.md": "Plain prose.\n"})
    code, out = _run_in(repo, _diff("docs/en/a.md", ["Another plain sentence."]))
    assert code == 1, out
    assert "never cited code" in out


# ─── limits, modes, diagnostics ─────────────────────────────────────────


def test_staged_mode_reads_the_index(tmp_path):
    repo = _git_repo(tmp_path, {"docs/a.md": "start\n", "src/m.py": "def f():\n    return 1\n"})
    (repo / "docs" / "a.md").write_text("start\nSee `src/nope.py`.\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/a.md"], cwd=str(repo), check=True, capture_output=True)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--staged"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "docs/a.md" in proc.stdout


def test_too_many_files_is_refused(tmp_path):
    _make_repo(tmp_path)
    diff = "".join(_diff(f"docs/en/f{i}.md", ["See `src/core/search/engine.py`."]) for i in range(201))
    code, out = _run(tmp_path, diff)
    assert code == 3, out
    assert "refusing to pass" in out


def test_too_many_added_lines_is_refused(tmp_path):
    _make_repo(tmp_path)
    diff = _diff("docs/en/big.md", ["See `src/core/search/engine.py`."] * 20_001)
    code, out = _run(tmp_path, diff)
    assert code == 3, out
    assert "refusing to pass" in out


def test_non_utf8_diff_file_fails_loudly(tmp_path):
    _make_repo(tmp_path)
    diff_file = tmp_path / "utf16.diff"
    diff_file.write_bytes(_diff("docs/en/x.md", ["See `src/core/nope.py`."]).encode("utf-16"))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), "--diff-file", str(diff_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "not UTF-8" in (proc.stdout + proc.stderr)


def test_repo_without_installer_does_not_crash(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `install.py --clean`."]))
    assert code == 1, out


def test_json_output_shape(tmp_path):
    _make_repo(tmp_path)
    code, out = _run(tmp_path, _diff("docs/en/x.md", ["See `src/core/search/engine.py`."]), "--json")
    payload = json.loads(out)
    assert code == 0
    assert payload["files"] == 1 and payload["problems"] == []


def test_gate_flags_a_real_offending_change_in_this_repo(tmp_path):
    """Positive control on the real tree: an invented reference must fail."""
    diff_file = tmp_path / "real.diff"
    diff_file.write_text(
        _diff("docs/en/INSTALL.md", ["Run `install.py --uninstall` to remove everything."]),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(REPO), "--diff-file", str(diff_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
