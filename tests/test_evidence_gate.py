"""Guards for the deterministic evidence gate (`src/core/search/evidence.py`).

Every test builds a real file on disk and a real SQLiteChunkStore row: the gate
claims facts, so its tests must not mock the facts away. One test breaks the
declaration check and expects the verdict to drop - a gate that cannot say "not
verified" is decoration.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.core.indexing.chunk_store import SQLiteChunkStore
from src.core.search import evidence
from src.core.search.evidence import (
    ANSWER_DEFINITION,
    WEIGHTS,
    assess,
    declaration_of,
)

# ── declaration shapes ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line, ident, expected",
    [
        ("def render():", "render", "function"),
        ("    async def build_call_graph(self):", "build_call_graph", "function"),
        ("class WriteTool(MCPTool):", "WriteTool", "class"),
        ("export function loadConfig() {", "loadConfig", "function"),
        ("export class Registry {", "Registry", "class"),
        ("const DEFAULT_LINE_LENGTH = 88", "DEFAULT_LINE_LENGTH", "variable"),
        ("interface Payload {", "Payload", "interface"),
        ("func (r *Repo) Save() error {", "Save", "function"),
        ("pub async fn run() {", "run", "function"),
        ("MAX_SIZE = 10", "MAX_SIZE", "assignment"),
        ("    name: str = 'x'", "name", "assignment"),
    ],
)
def test_declaration_of_recognises_real_shapes(line, ident, expected):
    assert declaration_of(line, ident) == expected


@pytest.mark.parametrize(
    "line, ident",
    [
        ("# def render():", "render"),
        ("// class WriteTool {}", "WriteTool"),
        ("    self.name = value", "name"),
        ("    other.render()", "render"),
        ('result = "def render"', "render"),
        ("", "render"),
    ],
)
def test_declaration_of_rejects_uses_and_comments(line, ident):
    assert declaration_of(line, ident) == ""


@pytest.mark.parametrize(
    "line, ident, expected",
    [
        ("ALLOWLIST = ('search_code',)", "allowlist", "assignment"),
        ("class Indexer:", "indexer", "class"),
        ("Indexer = None", "Indexer", "assignment"),
        ("indexer = None", "Indexer", ""),  # a code-shaped name is case-sensitive
    ],
)
def test_lowercase_prose_term_matches_an_upper_case_declaration(line, ident, expected):
    assert declaration_of(line, ident) == expected


# ── fixtures ────────────────────────────────────────────────────────────────


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _store_with(tmp_path: Path, rows: list[dict]) -> SQLiteChunkStore:
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records(rows)
    return store


def _indexed_row(root: Path, rel: str, *, text: str = "x", mtime_ns=None, size=None):
    stat = (root / rel).stat()
    return {
        "file_path": rel,
        "chunk_index": 0,
        "chunk_id": f"{rel}:0",
        "text": text,
        "text_full": text,
        "start_line": 1,
        "end_line": 1,
        "indexed_at": datetime.now().isoformat(),
        "file_hash": "h",
        "file_mtime_ns": stat.st_mtime_ns if mtime_ns is None else mtime_ns,
        "file_size": stat.st_size if size is None else size,
    }


# ── verdicts ────────────────────────────────────────────────────────────────


def test_declaration_inside_a_docstring_is_not_a_definition(tmp_path: Path):
    """A declaration-shaped line in a docstring must not verify anything."""
    _write(tmp_path, "mod.py", '"""\ndef render():\n"""\nvalue = 1\n')
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 2, "text": "def render():",
          "channels": {"grep"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.signals["exact"] == "occurrence"
    assert "definition" not in candidate.signals
    assert report.verdict == "caveat"


def test_neighbour_rows_do_not_parse_files(tmp_path: Path, monkeypatch):
    """Parsing is a confirmation step, not a per-row cost."""
    calls: list[str] = []
    _write(tmp_path, "mod.py", "value = 1\n")

    def counting(self, rel):
        calls.append(rel)
        return None

    monkeypatch.setattr(evidence._Snapshot, "tree", counting)

    assess(
        [{"file": "mod.py", "line": 1, "text": "value", "channels": {"search"}}],
        root=tmp_path,
        identifiers=["render"],
        store=None,
    )

    assert calls == []


def test_verified_line_is_the_declaration_line_not_the_chunk_line(tmp_path: Path):
    """A chunk can start above a `def`; ✓def must point at the declaration."""
    from types import SimpleNamespace

    _write(
        tmp_path,
        "mod.py",
        "class Box:\n    def __init__(self):\n        self.x = 1\n\n"
        "def render(\n    value,\n):\n    return value\n",
    )
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    class _Index:
        def find_definitions(self, name):
            return [SimpleNamespace(file_path=str(tmp_path / "mod.py"), line=5)]

    report = assess(
        [{"file": "mod.py", "line": 4, "text": "render — function",
          "channels": {"name"}, "symbol": "render"}],
        root=tmp_path,
        identifiers=["render"],
        symbol_index=_Index(),
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.line == 4
    assert candidate.decl_line == 5
    assert "✓def:function@5" in candidate.marker()
    assert "mod.py:5" in report.reason
    assert "mod.py:5" in report.dossier[0]


def test_local_assignment_is_not_a_definition(tmp_path: Path):
    """`impact = si.get_impact_analysis(...)` is a local, not the impact token.

    The line does contain the word, so it is exact evidence; it must still not
    become a definition or be promoted.
    """
    _write(
        tmp_path,
        "mod.py",
        "def compute(symbol):\n    impact = run(symbol)\n    return impact\n",
    )
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 2, "text": "impact impact: risk=low",
          "channels": {"impact"}, "symbol": "impact"}],
        root=tmp_path,
        identifiers=["impact"],
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.signals["exact"] == "occurrence"
    assert "definition" not in candidate.signals
    assert "graph" not in candidate.signals  # impact is a risk summary
    assert report.verdict == "caveat"


def test_module_level_assignment_is_a_definition(tmp_path: Path):
    _write(tmp_path, "mod.py", "ALLOWLIST = ('search_code',)\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "ALLOWLIST",
          "channels": {"name"}, "symbol": "ALLOWLIST"}],
        root=tmp_path,
        identifiers=["allowlist"],
        store=store,
    )

    assert report.candidates[0].signals["definition"] == "assignment"
    assert report.verdict == "answer"


def test_a_path_outside_the_project_is_not_read(tmp_path: Path, monkeypatch):
    """Path traversal guard: the gate never reads outside the project root."""
    outside = tmp_path.parent / f"{tmp_path.name}_outside.py"
    outside.write_text("def render():\n    return 1\n", encoding="utf-8")
    read: list[str] = []

    def counting(self, path):
        read.append(str(path))
        return None

    monkeypatch.setattr(evidence._Snapshot, "lines", counting)

    report = assess(
        [{"file": str(outside), "line": 1, "text": "render",
          "channels": {"grep"}}],
        root=tmp_path,
        identifiers=["render"],
    )

    assert report.candidates[0].note == "outside project"
    assert report.candidates[0].confidence == 0.0
    assert read == []


def test_a_member_row_does_not_inherit_the_class_declaration(tmp_path: Path):
    """`def __init__` at :2 must not be stamped with the class declared at :1."""
    from types import SimpleNamespace

    _write(
        tmp_path,
        "mod.py",
        "class BadSignature(Exception):\n    def __init__(self):\n        pass\n",
    )
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    class _Index:
        def find_definitions(self, name):
            return [SimpleNamespace(file_path=str(tmp_path / "mod.py"), line=1)]

    report = assess(
        [{"file": "mod.py", "line": 2, "text": "BadSignature.__init__ — function",
          "channels": {"symbol"}, "symbol": "BadSignature"}],
        root=tmp_path,
        identifiers=["BadSignature"],
        symbol_index=_Index(),
        store=store,
    )

    assert "definition" not in report.candidates[0].signals
    assert report.verdict == "abstain"


def test_non_python_definition_clears_the_floor(tmp_path: Path):
    """The index covers TS/Go; a verified declaration must answer there too."""
    _write(tmp_path, "mod.ts", "export function render() {\n  return 1;\n}\n")

    report = assess(
        [{"file": "mod.ts", "line": 1, "text": "render — function",
          "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
    )

    candidate = report.candidates[0]
    assert candidate.signals["definition"] == "function"
    assert "ast" not in candidate.signals
    assert report.verdict == "answer"


def test_assess_is_deterministic_on_fixed_rows(tmp_path: Path):
    """The gate must give one answer for one input.

    Retrieval ordering is not deterministic (grep has a budget; ties exist), so
    this test fixes the rows: the gate may not add its own nondeterminism.
    """
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])
    rows = [
        {"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}},
        {"file": "mod.py", "line": 1, "text": "render", "channels": {"grep"}},
    ]

    reports = [
        assess(rows, root=tmp_path, identifiers=["render"], store=store)
        for _ in range(10)
    ]

    seen = {
        (
            report.verdict,
            round(report.confidence, 6),
            tuple((c.file, c.line, tuple(sorted(c.signals))) for c in report.candidates),
            tuple(report.promote),
            tuple(report.dossier),
        )
        for report in reports
    }
    assert len(seen) == 1


def test_index_line_on_a_decorator_does_not_become_the_verified_line(tmp_path: Path):
    """The verified line is where the declaration is, not the index's guess."""
    from types import SimpleNamespace

    _write(tmp_path, "mod.py", "@cache\ndef render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    class _Index:
        def find_definitions(self, name):
            return [SimpleNamespace(file_path=str(tmp_path / "mod.py"), line=1)]

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render — function",
          "channels": {"name"}, "symbol": "render"}],
        root=tmp_path,
        identifiers=["render"],
        symbol_index=_Index(),
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.decl_line == 2
    assert "mod.py:2" in report.reason
    assert "definition: def render()" in report.dossier[0]


def test_exact_is_a_line_claim_not_a_channel_claim(tmp_path: Path):
    """A name-channel row whose line does not contain the name is not exact.

    The review found the opposite: a `name` hit (the variant occurs somewhere
    in the chunk) printed `✓exact` for a row whose line is unrelated (P05).
    """
    _write(tmp_path, "mod.py", "value = 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render — name match",
          "symbol": "render", "channels": {"name"}}],
        root=tmp_path,
        identifiers=["default", "render"],
        store=store,
    )

    assert "exact" not in report.candidates[0].signals


def test_local_variable_line_is_exact_but_not_a_definition(tmp_path: Path):
    """P08's shape: the gold line is a local `degraded: List[str] = []`."""
    _write(
        tmp_path,
        "mod.py",
        "def run():\n    degraded: List[str] = []\n    return degraded\n",
    )
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 2, "text": "degraded",
          "channels": {"search"}}],
        root=tmp_path,
        identifiers=["degraded"],
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.signals["exact"] == "occurrence"
    assert "definition" not in candidate.signals
    assert report.verdict == "caveat"  # evidence, but not a declaration


def test_python_definition_is_verified_by_ast(tmp_path: Path):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render — function",
          "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    assert report.verdict == "answer", report.reason
    candidate = report.candidates[0]
    assert candidate.signals["definition"] == "function"
    assert "ast" in candidate.signals
    assert candidate.signals["fresh"] == "stat match"
    assert candidate.confidence >= ANSWER_DEFINITION
    assert report.dossier and report.dossier[0].startswith("definition: def render")


def test_index_line_is_used_when_the_row_points_at_a_decorator(tmp_path: Path):
    # Symbol rows can point at the chunk start (a decorator line). The index
    # reports the real declaration line, and that line is what must verify.
    from types import SimpleNamespace

    _write(tmp_path, "mod.py", "@decorator\ndef render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    class _Index:
        def find_definitions(self, name):
            return [SimpleNamespace(file_path=str(tmp_path / "mod.py"), line=2)]

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        symbol_index=_Index(),
        store=store,
    )

    assert report.verdict == "answer"
    assert report.candidates[0].signals["definition"] == "function"


def test_search_only_row_is_not_an_answer(tmp_path: Path):
    _write(tmp_path, "mod.py", "value = 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "value", "channels": {"search"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    # The file is fresh, but a neighbour row is not parsed and names nothing.
    assert report.verdict == "abstain"
    assert report.confidence == WEIGHTS["fresh"]


def test_exact_occurrence_without_definition_is_a_caveat(tmp_path: Path):
    _write(tmp_path, "mod.py", "print('render')\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"grep"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    assert report.verdict == "caveat"
    assert report.candidates[0].signals["exact"] == "occurrence"


def test_references_intent_accepts_an_exact_occurrence(tmp_path: Path):
    _write(tmp_path, "caller.py", "render()\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "caller.py")])

    report = assess(
        [{"file": "caller.py", "line": 1, "text": "render()", "channels": {"grep"}}],
        root=tmp_path,
        identifiers=["render"],
        intent="references",
        store=store,
    )

    assert report.verdict == "answer"
    assert report.confidence >= ANSWER_DEFINITION - 0.2


def test_references_intent_accepts_a_call_graph_edge(tmp_path: Path):
    _write(tmp_path, "caller.py", "render()\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "caller.py")])

    report = assess(
        [{"file": "caller.py", "line": 1, "text": "caller of render",
          "channels": {"graph"}}],
        root=tmp_path,
        identifiers=["render"],
        intent="references",
        store=store,
    )

    assert report.verdict == "answer"
    assert "graph" in report.candidates[0].signals
    assert "exact" in report.candidates[0].signals


def test_missing_path_is_marked_not_dropped(tmp_path: Path):
    """A stale index must be visible, not silently deleted from the answer.

    Dropping the row would also punish a path-normalisation miss (an absolute
    path `_relpath` could not relativise), which is not evidence of absence.
    """
    report = assess(
        [{"file": "gone.py", "line": 3, "text": "ghost", "channels": {"search"}},
         {"file": "(memory)", "line": 0, "text": "ADR-1", "channels": {"memory"}}],
        root=tmp_path,
        identifiers=["ghost"],
    )

    assert report.missing == 1
    assert report.kept_indices == [0, 1]
    assert report.candidates[0].note == "missing"
    assert "⚠missing" in report.candidates[0].marker()
    assert report.candidates[0].confidence == 0.0


def test_memory_rows_need_no_file(tmp_path: Path):
    report = assess(
        [{"file": "(memory)", "line": 0, "text": "ADR-1: rerank", "channels": {"memory"}}],
        root=tmp_path,
        identifiers=["rerank"],
    )

    assert report.verdict == "abstain"  # a memory note alone is not an answer
    assert report.candidates[0].signals == {"memory": "project memory"}


def test_stale_file_is_marked_but_a_live_declaration_still_verifies(tmp_path: Path):
    """The gate reads the live line, so an old index cannot fake a declaration.

    Staleness is still surfaced (the agent must know the index is behind), but
    it does not downgrade a definition that was verified on disk right now.
    """
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    store = _store_with(
        tmp_path, [_indexed_row(tmp_path, "mod.py", size=999_999)]
    )

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    candidate = report.candidates[0]
    assert "fresh" not in candidate.signals
    assert candidate.note == "stale"
    assert "⚠stale" in candidate.marker()
    assert report.verdict == "answer"
    assert "exact" in candidate.signals
    assert candidate.confidence == pytest.approx(
        WEIGHTS["definition"] + WEIGHTS["ast"] + WEIGHTS["exact"]
    )


def test_a_grep_row_is_live_evidence(tmp_path: Path):
    """grep scans the tree, not the index: an old index cannot make it stale."""
    _write(tmp_path, "mod.py", "print('render')\n")
    store = _store_with(
        tmp_path, [_indexed_row(tmp_path, "mod.py", size=999_999)]
    )

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"grep"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    candidate = report.candidates[0]
    assert candidate.signals["fresh"] == "live scan"
    assert candidate.note == ""
    assert report.verdict == "caveat"


def test_a_stale_index_row_is_downgraded(tmp_path: Path):
    _write(tmp_path, "mod.py", "value = 1\n")
    store = _store_with(
        tmp_path, [_indexed_row(tmp_path, "mod.py", size=999_999)]
    )

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "value", "channels": {"search"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    assert report.candidates[0].note == "stale"
    assert report.candidates[0].confidence == 0.0
    assert report.verdict == "abstain"


def test_unknown_freshness_fails_open(tmp_path: Path):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        store=None,
    )

    assert report.candidates[0].note == ""
    assert report.verdict == "answer"  # def 0.60 + ast 0.05


def test_abstain_hint_is_carried_through(tmp_path: Path):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        abstain_hint=True,
    )

    assert report.verdict == "abstain"
    assert "does not occur" in report.reason


def test_dossier_collects_definition_callers_tests_risk(tmp_path: Path):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    _write(tmp_path, "caller.py", "render()\n")
    _write(tmp_path, "tests/test_mod.py", "def test_render():\n    assert render()\n")
    store = _store_with(
        tmp_path,
        [
            _indexed_row(tmp_path, "mod.py"),
            _indexed_row(tmp_path, "caller.py"),
            _indexed_row(tmp_path, "tests/test_mod.py"),
        ],
    )

    report = assess(
        [
            {"file": "mod.py", "line": 1, "text": "render — function",
             "channels": {"definition"}},
            {"file": "caller.py", "line": 1, "text": "caller of render",
             "channels": {"graph"}},
            {"file": "tests/test_mod.py", "line": 0, "text": "covers mod.py",
             "channels": {"tests"}},
            {"file": "mod.py", "line": 1, "text": "impact render: risk=low, affected=1",
             "channels": {"impact"}},
        ],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    dossier = "\n".join(report.dossier)
    assert "definition: def render()" in dossier
    assert "callers: 1" in dossier
    assert "tests: 1 predicted" in dossier
    assert "risk: impact render" in dossier
    assert "predict_change" in dossier


# ── the gate can fail (mutation) ────────────────────────────────────────────


def test_gate_can_say_not_verified(tmp_path, monkeypatch):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    monkeypatch.setattr(evidence, "declaration_of", lambda line, ident: "")
    monkeypatch.setattr(
        evidence, "_python_declaration", lambda tree, ident, line: ("", 0)
    )

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["render"],
        store=store,
    )

    assert report.verdict != "answer", "a broken verifier must not still say answer"
    assert "definition" not in report.candidates[0].signals
    assert report.confidence == WEIGHTS["exact"] + WEIGHTS["fresh"]


def test_fuzzy_symbol_is_not_the_subject(tmp_path: Path):
    """A declaration of `build_graph` must not confirm `build_call_graph`."""
    _write(tmp_path, "graph.py", "def build_graph():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "graph.py")])

    report = assess(
        [{"file": "graph.py", "line": 1, "text": "build_graph — function",
          "symbol": "build_graph", "channels": {"symbol"}}],
        root=tmp_path,
        identifiers=["build_call_graph"],
        store=store,
    )

    assert "definition" not in report.candidates[0].signals
    assert report.verdict == "abstain"


def test_a_derived_name_variant_is_the_subject_for_prose(tmp_path: Path):
    """`DEFAULT_LINE_LENGTH` from the name channel is what the row means."""
    _write(tmp_path, "const.py", "DEFAULT_LINE_LENGTH = 88\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "const.py")])

    report = assess(
        [{"file": "const.py", "line": 1, "text": "DEFAULT_LINE_LENGTH — name match",
          "symbol": "DEFAULT_LINE_LENGTH", "channels": {"name"}}],
        root=tmp_path,
        identifiers=["default", "line", "length"],
        store=store,
    )

    assert report.candidates[0].signals["definition"] == "assignment"
    assert report.verdict == "answer"


def test_a_derived_variant_is_ignored_when_the_query_names_a_symbol(tmp_path: Path):
    """`build_graph` derived from `build_call_graph` is not the subject."""
    _write(tmp_path, "graph.py", "def build_graph():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "graph.py")])

    report = assess(
        [{"file": "graph.py", "line": 1, "text": "build_graph — name match",
          "symbol": "build_graph", "channels": {"name"}}],
        root=tmp_path,
        identifiers=["build_call_graph"],
        store=store,
    )

    assert "definition" not in report.candidates[0].signals
    assert "exact" not in report.candidates[0].signals
    assert report.verdict == "abstain"  # the line does not contain the subject


def test_a_verified_definition_is_promoted_over_name_rows(tmp_path: Path):
    _write(tmp_path, "const.py", "DEFAULT_LINE_LENGTH = 88\n")
    _write(tmp_path, "other.py", "value = 1\n")
    store = _store_with(
        tmp_path,
        [_indexed_row(tmp_path, "const.py"), _indexed_row(tmp_path, "other.py")],
    )

    report = assess(
        [
            {"file": "other.py", "line": 1, "text": "DEFAULT_LINE_LENGTH",
             "symbol": "DEFAULT_LINE_LENGTH", "channels": {"name"}},
            {"file": "const.py", "line": 1, "text": "DEFAULT_LINE_LENGTH — name match",
             "symbol": "DEFAULT_LINE_LENGTH", "channels": {"name"}},
        ],
        root=tmp_path,
        identifiers=["default", "line", "length"],
        store=store,
    )

    assert report.verdict == "answer"
    assert report.promote == [("const.py", 1)]
    assert "(row 2 → promoted)" in report.reason


def test_unknown_identifier_does_not_get_a_definition(tmp_path: Path):
    _write(tmp_path, "mod.py", "def render():\n    return 1\n")
    store = _store_with(tmp_path, [_indexed_row(tmp_path, "mod.py")])

    report = assess(
        [{"file": "mod.py", "line": 1, "text": "render", "channels": {"definition"}}],
        root=tmp_path,
        identifiers=["totally_absent"],
        store=store,
    )

    assert report.verdict == "abstain"


# ── chunk store API used by the gate ────────────────────────────────────────


def test_get_file_stats_batches_and_ignores_missing(tmp_path: Path):
    _write(tmp_path, "a.py", "value = 1\n")
    _write(tmp_path, "b.py", "value = 2\n")
    store = _store_with(
        tmp_path,
        [_indexed_row(tmp_path, "a.py"), _indexed_row(tmp_path, "b.py")],
    )

    stats = store.get_file_stats(["a.py", "b.py", "absent.py"])

    assert set(stats) == {"a.py", "b.py"}
    assert stats["a.py"]["size"] == (tmp_path / "a.py").stat().st_size
    assert store.get_file_stats([]) == {}
    assert store.get_file_stat("a.py") == stats["a.py"]


def test_get_file_stat_returns_what_was_written(tmp_path: Path):
    _write(tmp_path, "mod.py", "value = 1\n")
    row = _indexed_row(tmp_path, "mod.py")
    store = _store_with(tmp_path, [row])

    stat = store.get_file_stat("mod.py")

    assert stat is not None
    assert stat["mtime_ns"] == row["file_mtime_ns"]
    assert stat["size"] == row["file_size"]
    assert store.get_file_stat("absent.py") is None


# ── rendering ───────────────────────────────────────────────────────────────


def test_format_renders_verdict_marker_and_dossier(tmp_path: Path):
    from src.mcp.tools.investigate_tool import InvestigateTool

    tool = object.__new__(InvestigateTool)
    report = evidence.EvidenceReport(
        verdict="answer",
        confidence=0.8,
        reason="function at mod.py:1",
        candidates=[
            evidence.Candidate(
                file="mod.py", line=1, text="render", channels=("definition",),
                signals={"definition": "function"}, confidence=0.8,
            )
        ],
        kept_indices=[0],
        dossier=["definition: def render() — mod.py:1"],
    )

    text = InvestigateTool._format(
        tool,
        query="where is render defined",
        identifiers=["render"],
        merged=[{"file": "mod.py", "line": 1, "text": "render",
                 "channels": {"definition"}}],
        symbol_lines=[],
        degraded=[],
        exact={"per": {"render": 1}},
        evidence=report,
    )

    assert "verdict: answer (0.80)" in text
    assert "✓def:function" in text
    assert "📎 dossier:" in text
    assert "definition: def render()" in text


def test_evidence_gate_control_switch(monkeypatch):
    from src.mcp.tools.investigate_tool import _evidence_gate_enabled

    monkeypatch.delenv("MSCODEBASE_EVIDENCE_GATE", raising=False)
    assert _evidence_gate_enabled() is True
    for value in ("0", "false", "off", "no"):
        monkeypatch.setenv("MSCODEBASE_EVIDENCE_GATE", value)
        assert _evidence_gate_enabled() is False
    monkeypatch.setenv("MSCODEBASE_EVIDENCE_GATE", "1")
    assert _evidence_gate_enabled() is True


def test_format_names_neighbours_when_the_verdict_is_abstain():
    from src.mcp.tools.investigate_tool import InvestigateTool

    tool = object.__new__(InvestigateTool)
    report = evidence.EvidenceReport(
        verdict="abstain", confidence=0.15, reason="no verified candidate",
        candidates=[], kept_indices=[0],
    )
    text = InvestigateTool._format(
        tool,
        query="where is ghost_symbol",
        identifiers=["ghost_symbol"],
        merged=[{"file": "a.py", "line": 1, "text": "x", "channels": {"search"}}],
        symbol_lines=[],
        degraded=[],
        exact={"per": {"ghost_symbol": 0}},
        evidence=report,
    )

    assert "verdict: abstain" in text
    assert "the rows below are neighbours" in text


def test_format_without_evidence_stays_quiet(tmp_path: Path):
    from src.mcp.tools.investigate_tool import InvestigateTool

    tool = object.__new__(InvestigateTool)
    text = InvestigateTool._format(
        tool,
        query="where is render defined",
        identifiers=["render"],
        merged=[{"file": "mod.py", "line": 1, "text": "render",
                 "channels": {"definition"}}],
        symbol_lines=[],
        degraded=[],
        exact={"per": {"render": 1}},
    )

    assert "verdict:" not in text
    assert "dossier" not in text
