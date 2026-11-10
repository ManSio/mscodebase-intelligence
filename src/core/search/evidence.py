"""Deterministic evidence gate for `investigate` candidates.

No model is called here. Every signal below is a fact that can be recomputed
from the index, the call graph, or the file on disk:

    definition  the candidate line declares the requested identifier
                (Python: confirmed by `ast` node name + lineno; other
                languages: a declaration regex on the line)
    exact       the identifier occurs verbatim on the row's line (a channel
                match alone is not enough; a line-less row keeps the channel
                claim and the verdict still says it is not a declaration)
    fresh       the file's live stat matches the stat recorded at index time
    ast         the parser confirmed the declaration line (Python); the file
                is parsed only when a definition is possible there
    graph       the call graph has an edge for the identifier
    test        the row is a test predicted to cover a top file
    memory      project memory (ADR / incident) mentions the subject

Verdicts:
    answer      a verified declaration (definition question), or an exact
                occurrence / call-graph edge (references question), above the
                floor: ANSWER_DEFINITION 0.60, ANSWER_REFERENCE 0.35
    caveat      confidence >= CAVEAT (0.25): neighbours with partial evidence
    abstain     no row carries evidence; the caller also forces it when the
                subject does not occur and the graph does not know it
    ask_rewrite decided before retrieval (see investigate_tool)

Confidence is a deterministic score, not a probability. Weights are fixed here
and capped at 1.0; a verified declaration scores 0.60 on its own (0.75 with a
fresh stat and a parser confirmation). Control/treatment on the frozen XERJ +
mcp_audit panels: experiments/xerj_2026_11/evidence_gate/REPORT.md.
"""

from __future__ import annotations

import ast
import logging
import re
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "Candidate",
    "EvidenceReport",
    "WEIGHTS",
    "assess",
    "declaration_of",
]

# The score is additive over independent facts. `definition` alone clears the
# answer floor because it is verified against the LIVE file: it is the
# strongest fact available for "where is X", and index staleness cannot
# invalidate a declaration that is sitting on disk right now. A references
# question is the opposite: an exact occurrence or a call-graph edge is the
# answer, the definition is context.
WEIGHTS: Dict[str, float] = {
    "definition": 0.60,
    "exact": 0.25,
    "fresh": 0.10,
    "ast": 0.05,
    "graph": 0.05,
    "test": 0.05,
    "memory": 0.05,
}

REFERENCE_WEIGHTS: Dict[str, float] = {
    "exact": 0.45,
    "graph": 0.25,
    "definition": 0.20,
    "fresh": 0.10,
    "ast": 0.05,
    "test": 0.05,
    "memory": 0.05,
}

ANSWER_DEFINITION = 0.60
ANSWER_REFERENCE = 0.35
CAVEAT = 0.25


def _weights_for(intent: str) -> Dict[str, float]:
    return REFERENCE_WEIGHTS if intent == "references" else WEIGHTS

# Declaration shapes for languages the index covers. The first group must
# match the *whole* captured name; a qualified assignment (`self.name = ...`)
# is not a declaration of `name`. Each rule is (kind, compiled pattern).
_DECL_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")),
    ("class", re.compile(r"^\s*class\s+([A-Za-z_]\w*)")),
    ("function", re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)"
    )),
    ("class", re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$]\w*)"
    )),
    ("interface", re.compile(
        r"^\s*(?:export\s+)?(?:type|interface|enum|record|namespace)\s+([A-Za-z_$]\w*)"
    )),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),
    ("struct", re.compile(
        r"^\s*(?:pub\s+)?(?:struct|enum|trait|type|union)\s+([A-Za-z_]\w*)"
    )),
    ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")),
    ("variable", re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var|static|final)\s+([A-Za-z_$]\w*)"
    )),
)

_ASSIGN_RULE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(?::[^=]+)?=\s*[^=]")
_COMMENT_PREFIXES = ("#", "//", "--", "/*", "*", ";")


def _code_shaped(token: str) -> bool:
    """Does the token look like a code identifier rather than an English word?

    Used to decide whether a name-channel variant is the subject: for
    `where is the default line length defined` the derived `DEFAULT_LINE_LENGTH`
    is the subject, but for `who calls build_call_graph` the derived
    `build_graph` (stopwords removed `call`) is a neighbour.
    """
    token = token or ""
    if not token:
        return False
    if "_" in token or "." in token:
        return True
    if any(ch.isupper() for ch in token[1:]):
        return True
    return token[:1].isupper() and any(ch.islower() for ch in token[1:])


def declaration_of(line_text: str, identifier: str) -> str:
    """Kind of declaration of `identifier` on this source line, or "".

    Deterministic and language-agnostic: the line must start with a
    declaration keyword and the captured name must equal the identifier.
    A comment line never declares anything.
    """
    text = (line_text or "").strip()
    if not text or text.startswith(_COMMENT_PREFIXES):
        return ""
    name = (identifier or "").rsplit(".", 1)[-1]
    if not name:
        return ""
    # A lowercase prose term ("allowlist") may name an upper-case constant
    # (`ALLOWLIST`); a code-shaped name stays case-sensitive.
    fold = name.islower()

    def _same(found: str) -> bool:
        return bool(found) and (found == name or (fold and found.lower() == name))

    for kind, rule in _DECL_RULES:
        match = rule.match(text)
        if match and _same((match.group(1) or "").rsplit(".", 1)[-1]):
            return kind
    match = _ASSIGN_RULE.match(text)
    if match:
        target = match.group(1) or ""
        # `self.name =` / `obj.name =` are uses, not declarations.
        if "." not in target and _same(target):
            return "assignment"
    return ""


def _python_declaration(
    tree: ast.AST, identifier: str, line: int
) -> Tuple[str, int]:
    """Parser-confirmed declaration of `identifier` near `line`.

    Returns (kind, declaration line). Assignments count only at module or class
    level: a local variable that happens to share the query word is not a
    definition (measured 2026-11-10: `impact = si.get_impact_analysis(...)`
    became the answer to "impact token").
    """
    name = (identifier or "").rsplit(".", 1)[-1]
    if not name:
        return "", 0
    fold = name.islower()

    def _same(found: str) -> bool:
        return found == name or (fold and found.lower() == name)

    def _near(node_line: int) -> bool:
        # The declaration is the row line, or the line below it when the row
        # sits on a decorator. A line *above* the row is a different construct
        # (a member right under its class must not inherit it).
        return bool(line) and node_line in (line, line + 1)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_line = int(node.lineno or 0)
            if _same(str(node.name or "")) and _near(node_line):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                return kind, node_line

    scopes: List[List[ast.stmt]] = []
    if hasattr(tree, "body"):
        scopes.append(list(tree.body))  # type: ignore[arg-type]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scopes.append(list(node.body))
    for body in scopes:
        for node in body:
            node_line = int(getattr(node, "lineno", 0) or 0)
            if not _near(node_line):
                continue
            targets: List[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and _same(target.id):
                    return "assignment", node_line
    return "", 0


class _Snapshot:
    """Live view of the files named in one answer (bounded, cached, locked)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._lines: Dict[str, Optional[List[str]]] = {}
        self._trees: Dict[str, Optional[ast.AST]] = {}

    def lines(self, path: Path) -> Optional[List[str]]:
        key = str(path)
        with self._lock:
            if key in self._lines:
                return self._lines[key]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            value: Optional[List[str]] = text.splitlines()
        except OSError:
            value = None
        with self._lock:
            self._lines[key] = value
        return value

    def tree(self, path: Path) -> Optional[ast.AST]:
        key = str(path)
        with self._lock:
            if key in self._trees:
                return self._trees[key]
        value: Optional[ast.AST] = None
        if path.suffix == ".py":
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                with warnings.catch_warnings():
                    # Parsing user code can emit SyntaxWarning (invalid escape
                    # sequences); the tool's logs must stay clean.
                    warnings.simplefilter("ignore")
                    value = ast.parse(source)
            except (OSError, SyntaxError, ValueError):
                value = None
        with self._lock:
            self._trees[key] = value
        return value


def _index_definition(
    symbol_index: Any, identifier: str, rel: str, line: int
) -> int:
    """Line the symbol index reports for this file, or 0 when unknown."""
    find_defs = getattr(symbol_index, "find_definitions", None)
    if not callable(find_defs) or not identifier:
        return 0
    try:
        refs = find_defs(identifier) or []
    except Exception:  # noqa: BLE001 - an index that cannot answer is "unknown"
        return 0
    for ref in refs:
        ref_file = str(getattr(ref, "file_path", "") or "").replace("\\", "/")
        ref_line = int(getattr(ref, "line", 0) or 0)
        # Suffix on a path boundary: `config.py` must not match `src/config.py`.
        if not (ref_file == rel or ref_file.endswith("/" + rel)):
            continue
        if line and ref_line and abs(ref_line - line) > 3:
            continue
        return ref_line
    return 0


def _project_file(root: Path, rel: str) -> Tuple[Optional[Path], str]:
    """Resolve a row path inside the project, or explain why it is not read.

    `_relpath` passes through absolute paths it cannot relativise, so a row can
    carry a path outside the project. Reading it would let a stale index make
    the gate read (and quote in the dossier) any readable file - the path
    traversal guard from AGENTS.md §9 therefore applies here too.
    """
    try:
        candidate = (root / rel).resolve()
    except (OSError, ValueError):
        return None, "outside project"
    try:
        inside = candidate.is_relative_to(root)
    except (ValueError, OSError):
        return None, "outside project"
    if not inside:
        return None, "outside project"
    if not candidate.is_file():
        return None, "missing"
    return candidate, ""


def _freshness(
    path: Path, indexed: Optional[Dict[str, Any]]
) -> Tuple[Optional[bool], str]:
    """Compare the live stat with the stat recorded at index time.

    Returns (True, detail) when they match, (False, detail) when the file is
    demonstrably newer, and (None, detail) when the check cannot answer - an
    unknown must never be printed as stale.
    """
    try:
        live = path.stat()
    except OSError:
        return None, "stat failed"
    if not indexed:
        return None, "not in index"
    indexed_ns = int(indexed.get("mtime_ns") or 0)
    indexed_size = int(indexed.get("size") or 0)
    if indexed_ns and indexed_size:
        if live.st_mtime_ns == indexed_ns and live.st_size == indexed_size:
            return True, "stat match"
        if live.st_size != indexed_size:
            return False, "changed after index"
        # A touch (git checkout) keeps the size: cannot tell content apart
        # without hashing, so this is "unknown", not "stale".
        return None, "mtime differs, size same"
    indexed_at = str(indexed.get("indexed_at") or "")
    if indexed_at:
        try:
            from datetime import datetime

            indexed_dt = datetime.fromisoformat(indexed_at)
            if live.st_mtime <= indexed_dt.timestamp() + 2.0:
                return True, "indexed_at"
            return False, "changed after index"
        except (ValueError, OSError):
            pass
    return None, "no indexed stat"


@dataclass
class Candidate:
    """One verified answer row."""

    file: str
    line: int
    text: str
    channels: Tuple[str, ...]
    signals: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    note: str = ""
    snippet: str = ""
    # The line where the declaration was actually verified. A chunk row can
    # start a few lines above a `def` (decorator, comment, closing paren), and
    # printing "✓def" on the row's line without this would be a small lie
    # (independent review, 2026-11-10).
    decl_line: int = 0

    def marker(self) -> str:
        """Short, factual suffix for the rendered row."""
        marks: List[str] = []
        if "definition" in self.signals:
            where = (
                f"@{self.decl_line}"
                if self.decl_line and self.decl_line != self.line
                else ""
            )
            marks.append(f"✓def:{self.signals['definition']}{where}")
        if "exact" in self.signals:
            marks.append("✓exact")
        if "fresh" not in self.signals and self.note:
            marks.append(f"⚠{self.note}")
        return "  " + " ".join(marks) if marks else ""


@dataclass
class EvidenceReport:
    verdict: str
    confidence: float
    reason: str
    candidates: List[Candidate] = field(default_factory=list)
    kept_indices: List[int] = field(default_factory=list)
    missing: int = 0
    promote: List[Tuple[str, int]] = field(default_factory=list)
    dossier: List[str] = field(default_factory=list)

    def by_location(self) -> Dict[Tuple[str, int], Candidate]:
        return {(c.file, c.line): c for c in self.candidates}


def _dossier(rows: Iterable[Dict[str, Any]], candidates: List[Candidate]) -> List[str]:
    """Facts worth attaching to a good answer, all from the rows in hand."""
    lines: List[str] = []
    definition = next((c for c in candidates if "definition" in c.signals), None)
    if definition is not None:
        snippet = (definition.snippet or definition.text).strip().splitlines()
        snippet = snippet[0][:120] if snippet else definition.signals["definition"]
        where = definition.decl_line or definition.line
        lines.append(f"definition: {snippet} — {definition.file}:{where}")

    rows_list = list(rows)
    callers = [
        row for row in rows_list
        if set(row.get("channels") or []) & {"graph"} and row.get("file") != "(memory)"
    ]
    if callers:
        places = ", ".join(
            f"{row['file']}:{row['line']}" for row in callers[:3] if row.get("file")
        )
        lines.append(f"callers: {len(callers)}" + (f" → {places}" if places else ""))

    tests = [
        str(row.get("file")) for row in rows_list
        if "tests" in (row.get("channels") or set()) and row.get("file")
    ]
    if tests:
        shown = ", ".join(dict.fromkeys(tests))[:160]
        lines.append(f"tests: {len(tests)} predicted → {shown}")

    memory = [
        str(row.get("text")) for row in rows_list
        if "memory" in (row.get("channels") or set())
    ]
    if memory:
        lines.append(f"memory: {memory[0][:120]}")

    impact = [
        row for row in rows_list if "impact" in (row.get("channels") or set())
    ]
    if impact:
        lines.append(f"risk: {str(impact[0].get('text') or '')[:120]}")

    if lines:
        lines.append('before editing: predict_change(mode="static") + write preview/ack')
    return lines


def assess(
    rows: Iterable[Dict[str, Any]],
    *,
    root: Path | str,
    identifiers: List[str],
    symbol_index: Any = None,
    store: Any = None,
    intent: str = "explore",
    abstain_hint: bool = False,
) -> EvidenceReport:
    """Verify merged rows and return a verdict with per-row evidence.

    `rows` are `_merge` dicts: file (project-relative), line, text, channels.
    `intent` is "references" for "who calls X" questions, where an exact
    occurrence is the answer and a definition is only context.
    """
    root_path = Path(root).resolve()
    snapshot = _Snapshot(root_path)
    weights = _weights_for(intent)
    subject = identifiers[0] if identifiers else ""
    rows = list(rows)
    candidates: List[Candidate] = []
    kept: List[int] = []
    missing = 0

    # Path guard + one batch stat read for every file in the answer. The batch
    # is a read-only connection: per-row lookups on the shared read-write
    # connection waited on the indexer's write lock (measured 2026-11-10).
    resolved: Dict[str, Optional[Path]] = {}
    index_key: Dict[str, str] = {}
    notes: Dict[str, str] = {}
    wanted: List[str] = []
    for row in rows:
        rel = str(row.get("file") or "")
        if not rel or rel == "(memory)" or rel in resolved:
            continue
        path, why = _project_file(root_path, rel)
        resolved[rel] = path
        notes[rel] = why
        if path is not None:
            try:
                index_key[rel] = path.relative_to(root_path).as_posix()
            except ValueError:
                index_key[rel] = rel
            wanted.append(index_key[rel])
    indexed_stats: Dict[str, Dict[str, Any]] = {}
    if wanted:
        batch = getattr(store, "get_file_stats", None)
        if callable(batch):
            try:
                indexed_stats = batch(wanted) or {}
            except Exception:  # noqa: BLE001 - unknown freshness must not fail
                indexed_stats = {}
        else:
            single = getattr(store, "get_file_stat", None)
            if callable(single):
                for key in wanted:
                    try:
                        value = single(key)
                    except Exception:  # noqa: BLE001
                        value = None
                    if value:
                        indexed_stats[key] = value

    for index, row in enumerate(rows):
        rel = str(row.get("file") or "")
        if not rel:
            continue
        line = int(row.get("line") or 0)
        channels = tuple(sorted(row.get("channels") or set()))

        if rel == "(memory)":
            candidate = Candidate(
                file=rel, line=0, text=str(row.get("text") or ""),
                channels=channels, signals={"memory": "project memory"},
                confidence=weights["memory"],
            )
            candidates.append(candidate)
            kept.append(index)
            continue

        path = resolved.get(rel)
        if path is None:
            # Keep the row but say so: a path the index remembers and the disk
            # does not have is a stale-index symptom, not proof the symbol is
            # gone. A path outside the project is never read (§9).
            candidates.append(
                Candidate(
                    file=rel, line=line, text=str(row.get("text") or ""),
                    channels=channels, signals={}, confidence=0.0,
                    note=notes.get(rel) or "missing",
                )
            )
            kept.append(index)
            missing += 1
            continue

        signals: Dict[str, str] = {}
        # `exact` is a claim about the ROW'S LINE, not about the channel that
        # found the row: a name-channel hit can be a mention elsewhere in the
        # chunk (review 2026-11-10, P05). It is decided after the line is read.
        exact_channels = bool(set(channels) & {"grep", "name"})

        decl = ""
        snippet = ""
        decl_line = line
        line_text = ""
        lines: Optional[List[str]] = None
        # Only two names may be verified for this row: the subject itself, or
        # a compound variant the name channel derived from the query. A fuzzy
        # symbol hit is a neighbour: "build_call_graph" must not be confirmed
        # by a declaration of "build_graph" (live check 2026-11-10).
        row_symbol = ""
        if "name" in channels and row.get("symbol") and not _code_shaped(subject):
            row_symbol = str(row["symbol"])
        row_symbol = row_symbol or subject
        indexed_line = 0
        if row_symbol:
            indexed_line = _index_definition(
                symbol_index, row_symbol, index_key.get(rel, rel), line
            )
            if line == 0 and indexed_line:
                # A line-less row: the index is the only line we have.
                decl_line = indexed_line
            # The row's own line is the contract: the row must declare the
            # subject (or sit on a decorator, which the parser sees ±1). The
            # index line is used only for a row with no line at all - a member
            # row (`BadSignature.__init__` at :25) must not inherit the class
            # declaration at :22 (review 2026-11-10).
            probes = [line] if line > 0 else (
                [indexed_line] if indexed_line else []
            )
            if probes:
                lines = snapshot.lines(path)
                if lines:
                    for probe in probes:
                        if 0 < probe <= len(lines):
                            line_text = lines[probe - 1]
                            decl = declaration_of(line_text, row_symbol)
                            if decl:
                                decl_line = probe
                                snippet = line_text.strip()
                                break
                # Parsing a 100 KB module costs ~25 ms and most rows are
                # neighbours of a symbol defined elsewhere, so a file is parsed
                # only when the line or the index says a definition can be
                # there (measured: gate latency 2.21 -> 2.49 s mean without it).
                if decl or indexed_line:
                    tree = snapshot.tree(path)
                    if tree is not None:
                        # For Python the parser is authoritative: a declaration-
                        # shaped line inside a docstring is not a declaration.
                        kind, node_line = _python_declaration(
                            tree, row_symbol, decl_line
                        )
                        decl = kind
                        if kind:
                            decl_line = node_line or decl_line
                            signals["ast"] = "parser confirmed"
                            if (
                                not snippet
                                and lines
                                and 0 < decl_line <= len(lines)
                            ):
                                snippet = lines[decl_line - 1].strip()
                        else:
                            snippet = ""
                    elif path.suffix == ".py" and decl:
                        # A Python file that does not parse (a half-written
                        # edit) cannot confirm anything.
                        decl = ""
                        snippet = ""
        if decl:
            signals["definition"] = decl

        if row_symbol and line_text:
            if row_symbol in line_text:
                signals["exact"] = "occurrence"
        elif exact_channels and line <= 0:
            # No line to check (a line-less row): the channel itself guarantees
            # the match, so the weaker claim stands, and the verdict still says
            # it is not a declaration.
            signals["exact"] = "occurrence"

        if "graph" in channels:
            # `impact` is a risk summary for the symbol, not a call edge: it
            # must not be counted as one (review 2026-11-10).
            signals["graph"] = "call graph edge"
        if "tests" in channels:
            signals["test"] = "covers a top file"

        if "grep" in channels:
            # The grep channel scans the live tree, not the index: its rows
            # cannot be stale in the index sense.
            signals["fresh"] = "live scan"
            fresh, note = True, ""
        else:
            fresh, _detail = _freshness(path, indexed_stats.get(index_key.get(rel, rel)))
            note = ""
            if fresh is True:
                signals["fresh"] = _detail
            elif fresh is False:
                note = "stale"

        confidence = min(1.0, sum(weights[name] for name in signals))
        if fresh is False and "definition" not in signals:
            # A verified live declaration is not weakened by an old index; an
            # occurrence that may have moved is.
            confidence = max(0.0, confidence - weights["fresh"])

        candidates.append(
            Candidate(
                file=rel, line=line, text=str(row.get("text") or ""),
                channels=channels, signals=signals, confidence=confidence,
                note=note, snippet=snippet, decl_line=decl_line if decl else 0,
            )
        )
        kept.append(index)

    report = EvidenceReport(
        verdict="abstain",
        confidence=0.0,
        reason="no verified candidate",
        candidates=candidates,
        kept_indices=kept,
        missing=missing,
    )
    if abstain_hint:
        report.reason = "subject does not occur and the graph does not know it"
        return report
    if not candidates:
        report.reason = "no candidates"
        return report

    best = max(candidates, key=lambda c: c.confidence)
    rank = candidates.index(best) + 1
    report.confidence = best.confidence
    answer_floor = ANSWER_REFERENCE if intent == "references" else ANSWER_DEFINITION
    # A references question is answered by an occurrence OR by a call-graph
    # edge; a definition question only by a verified declaration.
    answer_signals = ("exact", "graph") if intent == "references" else ("definition",)
    signal_present = next((name for name in answer_signals if name in best.signals), "")
    if best.confidence >= answer_floor and signal_present:
        report.verdict = "answer"
        promoted = " → promoted" if rank > 1 and intent != "references" else ""
        where = best.decl_line or best.line
        report.reason = (
            f"{best.signals.get(signal_present, signal_present)} at "
            f"{best.file}:{where} (row {rank}{promoted})"
        )
    elif best.confidence >= CAVEAT:
        report.verdict = "caveat"
        report.reason = "partial evidence: no verified declaration"
    else:
        report.verdict = "abstain"
        report.reason = "no verified candidate"

    if report.verdict == "answer" and intent != "references":
        # A verified declaration is the answer to a definition question: it
        # must not sit at rank 5 behind name matches (live 2026-11-10:
        # "default line length" had the real assignment at row 5). Promotion
        # is stable, so ties keep the ranking they were given.
        report.promote = [
            (c.file, c.line) for c in candidates if "definition" in c.signals
        ]

    if report.verdict != "abstain":
        report.dossier = _dossier(rows, candidates)
    return report
