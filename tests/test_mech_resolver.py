"""E4.2 — unit tests for the mechanical concept→symbol resolver + Option V fact text.

Pure (no service stack): resolver.py imports only pathlib.
Proves the two E4.1 verify_change misses are fixed at the resolution layer, and
that graph_fact_text gathers enough def+docstring text to cover required_facts.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "mech_orch"))
import resolver  # noqa: E402

T9_PROMPT = "Я изменил engine.py — какой инструмент вызвать для обновления индекса и как?"
T29_PROMPT = "Изменил паттерны извлечения — что проверить?"


# ── concept resolution (Option A) ──────────────────────────────────────────

def test_t9_concept_maps_to_notify_change():
    assert resolver.concept_symbol(T9_PROMPT, "verify_change") == "notify_change"


def test_t9_klass_gating_fails_open_for_other_klass():
    # same phrase, wrong klass -> fail-open (no wrong mapping)
    assert resolver.concept_symbol(T9_PROMPT, "find_impact") == ""


def test_t29_concept_maps_to_extract_symbol_name():
    assert resolver.concept_symbol(T29_PROMPT, "verify_change") == "_extract_symbol_name"


def test_t29_works_in_any_word_order():
    assert resolver.concept_symbol("паттерн извлечения изменил", "verify_change") == "_extract_symbol_name"


def test_no_recipe_returns_empty():
    assert resolver.concept_symbol("Почему падает write_records при сбое add?", "find_bug_cause") == ""


def test_empty_prompt_fails_open():
    assert resolver.concept_symbol("", "verify_change") == ""
    assert resolver.concept_symbol(None, "verify_change") == ""


def test_case_and_whitespace_insensitive():
    assert resolver.concept_symbol("   ОБНОВИТЬ  ИНДЕКС   после правки ", "verify_change") == "notify_change"


# ── Option V: graph rows carry facts ───────────────────────────────────────

def test_read_snippet_returns_window_around_line(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("line1\nline2\ndef notify_change(file_path: str, kwargs=None):\n    \"\"\"Обновляет индекс файла.\"\"\"\nline5\n", encoding="utf-8")
    snip = resolver.read_snippet(str(f), 3)
    assert "notify_change(file_path" in snip
    assert "Обновляет индекс файла" in snip  # docstring captured


def test_read_snippet_absent_file_returns_empty(tmp_path):
    assert resolver.read_snippet(str(tmp_path / "missing.py"), 3) == ""


def test_graph_fact_text_covers_required_facts(tmp_path):
    # realistic notify_change def in server_tools.py-like snippet
    mod = tmp_path / "server_tools.py"
    mod.write_text(
        "\n".join([
            "line1", "line2",
            "@mcp.tool('notify_change')",
            "async def notify_change(file_path: str, kwargs=None) -> str:",
            "    \"\"\"Обновляет индекс одного файла через LSP VFS или диск. P0:",
            "    замыкает workflow edit -> notify -> reindex.\"\"\"",
            "line7", "line8",
        ]),
        encoding="utf-8",
    )
    adapter = SimpleNamespace(
        find_definitions=lambda sym: [SimpleNamespace(file_path=str(mod), line=4, symbol=sym)]
    )
    blob = resolver.graph_fact_text(adapter, "notify_change")
    assert "server_tools.py" in blob  # F4
    assert "notify_change(file_path" in blob  # F1 signature + F2 file_path
    assert "индекс" in blob  # F3
