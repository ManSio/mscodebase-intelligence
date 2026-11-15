"""Тесты гейта AGENTS.md: файл не должен гнить (2026-11-15 — 4 устаревших факта).

Гейт ловит именно то, что сломалось в реальности: неверный путь, исчезнувший
файл, число-дубль из docs/FACTS.md, слишком длинный файл.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_agents_md as gate  # noqa: E402

SCRIPT = REPO / "scripts" / "check_agents_md.py"
HEADER = "# AGENTS\n\nСмотри `docs/FACTS.md`. Гейт — `scripts/check_agents_md.py`.\n"


def problems(text: str) -> list[str]:
    return gate.check(REPO, text)


def test_the_real_file_passes():
    """Положительный контроль на реальном дереве."""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert problems(text) == []


def test_real_file_stays_within_the_budget():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 160


def test_budget_is_pinned():
    """Без литерала тест тавтологичен: MAX_LINES=100000 проходил бы."""
    assert gate.MAX_LINES == 160


def test_backslash_path_is_checked():
    """Ровно тот случай, ради которого гейт написан: `src\\core\\config.py`.

    Проверяем нормализованный путь: мутация «не заменять `\\` на `/`» иначе
    выживала — она ловила огрызок `config.py` и всё равно давала R2.
    """
    text = HEADER + "\nMCP: `src\\core\\config.py`.\n"
    assert any("R2" in p and "src/core/config.py" in p for p in problems(text))


def test_root_file_must_exist():
    text = HEADER + "\nРеестр: `KNOWN_ISSUES_OLD.md`.\n"
    assert any("R2" in p for p in problems(text))


def test_extensionless_path_under_a_known_dir_is_checked():
    text = HEADER + "\nХук: `.githooks/nonexistent-gate`.\n"
    assert any("R2" in p for p in problems(text))


def test_directory_is_accepted():
    text = HEADER + "\nКаталог: `docs/blog/`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_foreign_paths_are_ignored():
    text = HEADER + "\n`~/.config/opencode/AGENTS.md` и `<install-root>/venv/x.py`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_path_case_must_match_the_repository():
    text = HEADER + "\nСм. `src/Main.py`.\n"
    assert any("R2" in p and "регистр" in p for p in problems(text))


def test_too_long_file_is_rejected():
    text = HEADER + "\n".join(f"строка {i}" for i in range(gate.MAX_LINES + 5))
    assert any("R1" in p for p in problems(text))


def test_missing_path_is_rejected():
    text = HEADER + "\nСм. `src/core/config.py`.\n"
    assert any("R2" in p and "src/core/config.py" in p for p in problems(text))


def test_existing_path_is_accepted():
    text = HEADER + "\nСм. `src/main.py`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_generated_path_is_allowlisted():
    text = HEADER + "\nСм. `docs/generated/MODULE_INDEX.md`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_placeholder_path_is_skipped():
    text = HEADER + "\nАрхив: `docs/archive/KNOWN_ISSUES_YYYY_MM.md`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_unknown_installer_flag_is_rejected():
    text = HEADER + "\nЗапустите `install.py --uninstall`.\n"
    assert any("R3" in p for p in problems(text))


def test_known_installer_flag_is_accepted():
    text = HEADER + "\nЗапустите `install.py --doctor`.\n"
    assert not [p for p in problems(text) if "R3" in p]


def test_flag_placeholder_is_not_a_flag():
    text = HEADER + "\nКаждый `install.py --flag` обязан существовать.\n"
    assert not [p for p in problems(text) if "R3" in p]


def test_unknown_env_var_is_rejected():
    text = HEADER + "\nВключите `MSCODEBASE_FAKE_FLAG`.\n"
    assert any("R4" in p for p in problems(text))


def test_known_env_var_is_accepted():
    text = HEADER + "\n`MSCODEBASE_DENSE_OFF=true`.\n"
    assert not [p for p in problems(text) if "R4" in p]


def test_version_mismatch_is_rejected():
    text = HEADER + "\nВерсия `9.9.9`.\n"
    assert any("R5" in p for p in problems(text))


def test_hardcoded_facts_numbers_are_rejected():
    text = HEADER + "\nСнапшот: 498 файлов, 7 375 чанков.\n"
    found = [p for p in problems(text) if "R6" in p]
    assert len(found) == 2, found


def test_small_numbers_are_not_facts_duplicates():
    text = HEADER + "\nБольше 10 файлов — batch-grep.\n"
    assert not [p for p in problems(text) if "R6" in p]


def test_missing_facts_link_is_rejected():
    text = "# AGENTS\n\nГейт — `scripts/check_agents_md.py`.\n"
    assert any("docs/FACTS.md" in p for p in problems(text))


def test_missing_self_reference_is_rejected():
    text = "# AGENTS\n\nСмотри `docs/FACTS.md`.\n"
    assert any("check_agents_md.py" in p for p in problems(text))


def test_cli_passes_on_the_real_file():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(REPO)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "problem(s)" in proc.stdout


def test_cli_refuses_an_empty_file(tmp_path):
    empty = tmp_path / "AGENTS.md"
    empty.write_text("", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--path", "AGENTS.md"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 1
    assert "empty" in (proc.stdout + proc.stderr)

def test_missing_directory_is_rejected():
    text = HEADER + "\nПравила: `src/ghost_dir/`.\n"
    assert any("R2" in p for p in problems(text))


def test_directory_with_wrong_case_is_rejected():
    text = HEADER + "\nПравила: `SRC/core/`.\n"
    assert any("R2" in p for p in problems(text))


def test_paths_outside_the_old_dir_whitelist_are_checked():
    text = HEADER + "\n`deploy/ghost/Dockerfile`, `experiments/exp99/run.csv`.\n"
    found = [p for p in problems(text) if "R2" in p]
    assert len(found) == 2, found


def test_dot_relative_real_path_is_accepted():
    text = HEADER + "\nСм. `./src/main.py`.\n"
    assert not [p for p in problems(text) if "R2" in p]


def test_glob_path_is_not_a_reference():
    text = HEADER + "\nШаблон: `src/*/config.py`.\n"
    assert not [p for p in problems(text) if "R2" in p]
