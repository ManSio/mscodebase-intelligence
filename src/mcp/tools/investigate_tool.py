"""investigate — one query in, parallel fan-out out.

The agent should formulate a question, not choose between 54 tools. This tool
runs every relevant channel concurrently and merges the answers with
provenance:

    search  — ranked FTS5/BM25 over code and docs
    symbols — exact/prefix symbol matches
    grep    — regex over identifiers, AST-scoped (comments/strings skipped)

Each channel has its own timeout: a slow one degrades the answer instead of
failing it (`degraded: [...]`). Duplicates are merged by (file, line) and every
item keeps the set of channels that found it, so the evidence is auditable.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.core.search.evidence import EvidenceReport, assess
from src.mcp.tools.base import MCPTool

# Channel weights, additive on top of each channel's own (rank-based) score.
# `def_first` is the shipped default: an exact name lookup is evidence, a
# semantic neighbour is a guess. `exploratory` is the alternative measured in
# experiments/xerj_2026_11/run_profiles.py - it exists to test whether "let
# retrieval win" is better for vague questions, not because it is believed.
#  `exploratory` (let retrieval win) was measured and removed: on 32 tasks with
#  an identifier it scored top10 0.750 / rank1 0.344 against 0.875 / 0.656 for
#  `def_first`, and on the 4 tasks without an identifier the two were identical
#  (0.250 / 0.000) - so it was never a second profile, only a worse one.
#  Experiment: experiments/xerj_2026_11/run_profiles.py.
_PROFILES = {
    "def_first": {"symbol": 1.8, "definition": 2.5, "impact": 1.3, "graph": 1.0,
                  "grep": 0.3, "search": 0.6},
    # For a reference question the exact matches are the answer, and the
    # definition is context, not the answer.
    "references": {"symbol": 0.6, "definition": 2.5, "impact": 0.7, "graph": 1.6,
                   "grep": 1.7, "search": 0.6},
}

_MAX_IDS = 4
_CHANNEL_TIMEOUT = 12.0
_GREP_TIMEOUT = 15.0
# Hashes are not identifiers: a Gerrit `Change-Id` (40 hex chars) or a commit
# sha can never occur in the source, and counting them made the gate abstain on
# every sqlalchemy commit (E71, external benchmark: 0/40 at hit@5).
_HEX_TOKEN_RE = re.compile(r"^I?[0-9a-fA-F]{32,}$")
_STOPWORDS = {
    "the", "and", "for", "how", "why", "what", "does", "used", "use", "where",
    "when", "which", "with", "from", "into", "that", "this", "files", "file",
    "changed", "change", "checker", "calls", "call", "work", "works", "after",
    "who", "whom", "whose", "defined", "definition", "define", "defines",
    "implemented", "implement", "implements", "located", "sits", "lives",
    "raises", "raise", "returns", "return", "callers", "caller", "usages",
    # Commit trailers (Gerrit/GitHub) are not code names; counting them made the
    # gate abstain on prose (E71). `close` is left out on purpose: it is a real
    # method name.
    "fixed", "fixes", "issue", "issues", "resolves", "closes", "changelog",
}


def _memory_hits(nodes: Iterable[Dict[str, Any]], query: str) -> List[str]:
    """Project-memory nodes whose title/body shares a meaningful token."""
    tokens = {t for t in re.findall(r"[a-zа-я0-9_]{5,}", query.lower())}
    if not tokens:
        return []
    hits: List[str] = []
    for node in nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else node
        title = str(data.get("title") or data.get("name") or node.get("title") or "")
        body = " ".join(
            str(data.get(k) or "") for k in ("description", "content", "text", "summary")
        )
        haystack = (title + " " + body).lower()
        if any(token in haystack for token in tokens):
            label = (title or haystack[:80]).strip()
            if label and label not in hits:
                hits.append(label[:120])
        if len(hits) >= 3:
            break
    return hits


def _identifiers(query: str) -> List[str]:
    """Code-ish tokens from a natural-language question."""
    found: List[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", query):
        token = token.strip(".")
        if not token or token.lower() in _STOPWORDS:
            continue
        if _HEX_TOKEN_RE.match(token):
            continue
        if token not in found:
            found.append(token)

    def _score(token: str) -> tuple:
        code_shape = (
            "_" in token
            or any(c.isupper() for c in token[1:])
            or (token[:1].isupper() and any(c.islower() for c in token[1:]))
        )
        return (1 if code_shape else 0, len(token))

    found.sort(key=_score, reverse=True)
    return found[:_MAX_IDS]


def _relpath(path: Any, root: Any) -> str:
    """Project-relative path for every channel (or "" when there is none).

    Measured 2026-11-08 (external corpus, X07): the symbol/impact/graph channels
    return absolute paths while grep/search return relative ones, so the SAME
    location appeared twice in one answer (`src/x/encoding.py:11` and
    `C:/.../src/x/encoding.py:11`) and `_merge` could not dedupe them. Two of
    eight slots were spent on one line.
    """
    if not path:
        return ""
    text = str(path).replace("\\", "/")
    if not root:
        return text
    base = str(root).replace("\\", "/").rstrip("/")
    if text.lower().startswith(base.lower() + "/"):
        return text[len(base) + 1:]
    return text


def _abstains(per: Dict[str, int], known: bool, include_neighbours: bool) -> bool:
    """True when the answer must be "not found" instead of a neighbour list.

    `per` maps identifier -> exact hit count and exists only when the grep
    channel COMPLETED; a degraded channel means "unknown", so an empty/absent
    `per` never abstains. A symbol the graph knows keeps its neighbours: the
    name is real even if the exact channel missed it.
    """
    if include_neighbours or not per:
        return False
    # "The subject does not occur" means NO counted name occurs. Checking only
    # the first token refused answers where a later name occurred 47/290/785
    # times (E73: 13 of 40 sqlalchemy commits abstained, 8 of them hid the gold).
    # A `None` or negative counter is "unknown", not "absent": unknown must never
    # become a refusal (same fail-open rule as the degraded grep channel).
    counts = []
    for value in per.values():
        if value is None or int(value) < 0:
            return False
        counts.append(int(value))
    return not known and not any(counts)


_CYRILLIC_QUERY_RE = re.compile(r"[А-Яа-яЁё]")
_PRECISE_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")
# "Corpus", "Hub": a Latin word that looks like a proper noun, not an acronym
# (LSP) and not a code token (`progress.json`). It is the only shape the
# rewrite gate is meant for: XERJ N03.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


def _rewrite_gate_mode() -> str:
    """`smart` (default), `on`, or `off`.

    `on` asks for an identifier whenever a Cyrillic question has no code-shaped
    token (XERJ N03), which also hides real questions like P16. `smart` asks
    only when the question additionally names a proper-noun-like Latin word -
    the shape where the subject can be absent while its words look real.
    Measured: smart = off's positives + on's N03 (27 asks, 3 arms;
    experiments/xerj_2026_11/evidence_gate/REPORT_REWRITE.md).
    """
    value = os.getenv("MSCODEBASE_ASK_REWRITE", "smart").strip().lower()
    if value in ("0", "false", "off", "no"):
        return "off"
    if value in ("1", "true", "on", "yes"):
        return "on"
    return "smart"


def _rewrite_gate_enabled() -> bool:
    """Backward-compatible view of the mode: anything but `off` is enabled."""
    return _rewrite_gate_mode() != "off"


def _asks_for_identifier(query: str) -> str | None:
    """The rewrite message when the active rule says this question cannot be
    answered exactly, else None."""
    message = _needs_identifier_rewrite(query, _identifiers(query))
    if not message:
        return None
    mode = _rewrite_gate_mode()
    if mode == "off":
        return None
    if mode == "smart" and not _PROPER_NOUN_RE.search(query or ""):
        return None
    return message


def _needs_identifier_rewrite(query: str, identifiers: List[str]) -> str | None:
    """Deterministic rewrite gate for Russian questions without a code name.

    XERJ N03 ("Где ключ подписи Corpus Hub?") had only proper-noun-like Latin
    words, while the real subject (`corpus_hub_signing_key`) occurs nowhere;
    the tool returned `check_knowledge.py` as if it were the answer. Neighbours
    are not evidence: ask for an identifier instead. A lowercase term
    (`rerank`), a code-shaped token (`DEFAULT_LINE_LENGTH`), a filename
    (`progress.json`) or anything in backticks passes.
    """
    if not _CYRILLIC_QUERY_RE.search(query or ""):
        return None
    if re.search(r"`[^`]*[A-Za-z][^`]*`", query or ""):
        # A backticked code token is an explicit reference. Backticks around
        # plain Cyrillic prose are markdown emphasis, not a code name (review
        # 2026-11-10), so they do not open the gate.
        return None
    for ident in identifiers:
        if not _PRECISE_IDENT_RE.fullmatch(ident or ""):
            continue
        if "_" in ident or "." in ident or re.search(r"[a-z][A-Z]", ident):
            return None
        if ident.islower() and len(ident) >= 3:
            return None
    return (
        f"🧭 investigate: `{query}`\n"
        "   verdict: ask_rewrite\n"
        "   ⚠️ В запросе нет идентификатора кода: латинского имени, "
        "`snake_case` или `CamelCase`.\n"
        "   Соседи не выдаются, чтобы не принять их за ответ. "
        "Переформулируйте: `where is <identifier> defined` "
        'или передайте hints=["<identifier>"] — хост знает язык, сервер нет.'
        + _rewrite_hint(query)
    )


def _retry_hint(query: str, withheld: int, limit: int) -> str:
    """Machine-readable continuation for a withheld answer (option C, E69).

    The verdict stays `abstain`: unverified rows are never presented as an
    answer. But the caller gets the exact call to make instead of a sentence it
    has to parse — measured in E68, a single-shot caller does not act on prose.
    """
    return (
        f"\nNeighbours withheld: {withheld} (unverified).\n"
        f"next: investigate(query={json.dumps(query, ensure_ascii=False)}, "
        f"include_neighbours=true, limit={limit})"
    )


def _rewrite_hint(query: str) -> str:
    """Same shape for the rewrite gate: name the identifiers and the call."""
    return (
        f"\nnext: investigate(query={json.dumps(query, ensure_ascii=False)}, "
        'hints=["<identifier>"])'
    )


def _evidence_gate_enabled() -> bool:
    """Environment switch for the control arm of the gate experiment.

    Default on. The flag exists so the frozen panel can compare gate-on and
    gate-off on the same commit (experiments/xerj_2026_11/evidence_gate/),
    and so a regression can be rolled back without a revert.
    """
    return os.getenv("MSCODEBASE_EVIDENCE_GATE", "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def _asks_for_callers(query: str) -> bool:
    """Does the question ask for references (callers / raises / uses), not the definition?

    The definition is the answer to "where is X defined" and the wrong answer to
    "who uses X". Measured 2026-11-08: on `Who calls want_bytes?` the top hit was
    `def want_bytes`; on `Who raises ParseError?` the call graph has no CALLS
    edge at all (a `raise` is a reference, not a call), so the exact grep hits
    are the evidence there and must outrank semantic neighbours.
    """
    lowered = (query or "").lower()
    return any(
        marker in lowered
        for marker in (
            "who calls", "who uses", "who invokes", "who raises", "who imports",
            "callers", "call sites", "usages", "references to", "used by",
            "кто вызывает", "кто использует", "кто обращается", "где вызывается",
            "кто поднимает", "кто бросает",
        )
    )


_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/"
    r"|(^|/)test_[^/]+$"
    r"|(^|/)conftest\.py$"
)
# A `test_*.py` name alone is not proof: `src/core/test_impact.py` *predicts*
# test impact and was penalised as a test file (E66 red team, A2). Under the
# `content` mode outside `tests/`, the file has to actually define tests or
# import a test framework before it counts.
_TEST_DEF_RE = re.compile(r"^\s*(async\s+)?def\s+test_[A-Za-z0-9_]*", re.M)
_TEST_FRAMEWORK_RE = re.compile(
    r"^\s*(import\s+pytest|from\s+pytest|import\s+unittest|from\s+unittest)",
    re.M,
)
_TEST_BUCKET_MODES = ("path", "content")
_DOC_PATH_RE = re.compile(r"(^|/)docs?/")
_HISTORY_PATH_RE = re.compile(r"(^|/)docs?/(archive|research|blog)/")
_SCRIPT_PATH_RE = re.compile(r"(^|/)(scripts|examples|benches|fuzz)/")
_PROSE_FILE_RE = re.compile(r"\.(md|rst|txt)$", re.I)


def _asks_for_tests(query: str) -> bool:
    return bool(re.search(
        r"\b(tests?|specs?|coverage|pytest|unittest)\b|тест|покрыт", query or "", re.I
    ))


def _test_bucket_mode() -> str:
    """`content` (shipped after E67) or `path` (the previous behaviour).

    Unknown or empty -> `content`: the fix is the default, and `path` exists as
    a rollback, not as the normal state.
    """
    mode = (os.environ.get("MSCODEBASE_TEST_BUCKET") or "").strip().lower()
    return "path" if mode == "path" else "content"


@lru_cache(maxsize=1024)
def _content_says_test(path: str) -> bool:
    """Does this file define test functions or import a test framework?

    Unreadable files answer `True`: an unknown file keeps the old, stricter
    behaviour instead of silently becoming visible.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    return bool(_TEST_DEF_RE.search(text) or _TEST_FRAMEWORK_RE.search(text))


def _test_penalty_applies(file: str, root: Any) -> bool:
    if _test_bucket_mode() != "content":
        return True
    if file.replace("\\", "/").startswith(("tests/", "test/")):
        return True  # a tests/ path is a test; no I/O needed
    base = Path(root) if root else None
    absolute = str((base / file).resolve()) if base else file
    return _content_says_test(absolute)


def _asks_for_docs(query: str) -> bool:
    return bool(re.search(
        r"\b(docs?|documentation|readme|guide|faq|manual)\b"
        r"|докум|инструкц|руководств|справк",
        query or "",
        re.I,
    ))


_NAME_STOPWORDS = _STOPWORDS | {
    "is", "are", "was", "were", "be", "been", "being", "of", "to", "in",
    "on", "at", "by", "it", "its", "a", "an", "do", "did", "does", "can",
    "should", "must", "i", "we", "you", "my", "our", "your", "there", "here",
}


def _name_words(query: str) -> List[str]:
    """Query words in the order the user wrote them (stopwords removed).

    `_identifiers` reorders by score, which destroys compounds: "default line
    length" came back as [default, length, line], so the compound name was
    DEFAULT_LENGTH_LINE and const.py was never looked up (2026-11-09).
    """
    return [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", (query or "").lower())
        if word not in _NAME_STOPWORDS
    ]


def _name_variants(identifiers: Iterable[str], max_variants: int = 12) -> List[str]:
    """Code-shaped names built from adjacent prose words.

    "where is the default line length defined" carries no identifier, so the
    symbol/grep channels can only answer with neighbours. The chunk that holds
    `DEFAULT_LINE_LENGTH = 88` is one FTS query away if the tool tries the
    compound name (measured 2026-11-09: black `const.py` rank 1 for the exact
    string, absent from investigate's top-5 for the prose question).
    """
    words = [
        w for w in identifiers
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,}", w or "")
    ]
    variants: List[str] = []
    # Triples first: `DEFAULT_LINE_LENGTH` must beat the pair `LINE_LENGTH`,
    # which also exists in test fixtures as a lowercase token.
    for size in (3, 2):
        for start in range(0, max(0, len(words) - size + 1)):
            parts = words[start:start + size]
            for variant in (
                "_".join(parts).upper(),
                "_".join(parts),
                "".join(p.capitalize() for p in parts),
            ):
                if variant not in variants:
                    variants.append(variant)
    return variants[:max_variants]


def _bucket_penalty(file: str, query: str, root: Any = None) -> float:
    """Rank penalty for a non-answer bucket (audit 2026-11-09).

    Measured on three corpora: `tests/**`, `tests/data/**` and `docs/archive/**`
    outranked the implementation even when the question named an identifier
    (black 0/4 top-1, httpbin 1/4 top-1, tests took 13/20 and 17/20 slots).
    The penalty is a rank subtraction applied after the merge, like the
    definition demotion above: it moved tests/docs out of the top-5 on all
    three measured corpora (8/30, 13/20, 14/20 -> 0). It is not a hard cap,
    so a test row scoring more than 2.0 above the best code row still leads;
    that did not happen on the panel, and a cap is left for a future change.
    A question ABOUT tests/docs keeps them at full weight.
    """
    value = 0.0
    if not _asks_for_docs(query):
        if _HISTORY_PATH_RE.search(file):
            value -= 2.0
        elif _DOC_PATH_RE.search(file) or _PROSE_FILE_RE.search(file):
            # Root markdown (AGENT_DIARY, EXPERIMENTS_LOG) is as far from an
            # implementation as docs/: an exact-name hit there used to lead
            # ("on-demand rerank resolved" → EXPERIMENTS_LOG, audit follow-up).
            value -= 1.5
    if _TEST_PATH_RE.search(file) and not _asks_for_tests(query):
        if _test_penalty_applies(file, root):
            value -= 2.0
    if (
        _SCRIPT_PATH_RE.search(file)
        and not _asks_for_tests(query)
        and "script" not in (query or "").lower()
    ):
        # Same class as tests/docs: a helper script that happens to mention the
        # name is not the implementation (XERJ P05/P12: scripts/monitor.py and
        # scripts/dataflow_experiment.py led ahead of src/). Behind a switch
        # until the panel measures it.
        if os.getenv("MSCODEBASE_SCRIPTS_DEMOTE", "1").strip().lower() not in (
            "0", "false", "off", "no",
        ):
            value -= 2.0
    return value


def _search_row_to_item(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """One `hybrid_search_async` row -> one merge item.

    Shape measured 2026-11-08 (`probe_search_row.py`): the searcher returns
    `{text, metadata, final_score, source}` and the path/line live inside
    `metadata` (`file`, `start_line`). Reading `file_path`/`file` straight off
    the row gave None for every hit, and `_merge` silently drops items with no
    file — so the semantic channel contributed **nothing** to any `investigate`
    answer (E1: 0 hits from `search` vs 129 from the other channels across 24
    questions). Both shapes are accepted, so a future searcher change that
    flattens the row keeps working.
    """
    meta = row.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    # Scores from different channels are NOT on one scale: the searcher's
    # `final_score` was measured at 10.32 on the external corpus while the
    # symbol channel contributes a fixed 2.5. Summing them let a chunk that
    # merely mentions the symbol outrank its definition by 4x (measured
    # 2026-11-08: 10.92 vs 2.5 -> definition ranked 7th). A rank-based score is
    # bounded by construction: 1.0 for the best hit, then 1/2, 1/3 ... (the RRF
    # shape, minus the constant k, since we only need an ordering).
    rank_score = 1.0 / (idx + 1)
    return {
        "file": row.get("file_path") or row.get("file") or meta.get("file"),
        "line": row.get("line") or row.get("start_line") or meta.get("start_line") or 0,
        "end_line": row.get("end_line") or meta.get("end_line") or 0,
        "text": row.get("text") or row.get("content") or "",
        "score": rank_score,
        "weight": 0.6,  # replaced by the profile weight in `_search`
        "channels": {"search"},
    }


_RRF_K = 60
# The largest weight any channel can carry: `_names` uses 3.0, so a "normalized"
# weight cannot exceed 1.0 and the `name` channel does not get silently halved.
_MAX_WEIGHT = 3.0
_FUSION_MODES = ("weights", "rrf", "norm")


def _fusion_mode() -> str:
    """Merge formula, switchable so the frozen A/B (E65) runs one binary.

    weights — rank = channel score + channel weight (the shipped default);
    rrf     — rank = sum over channels of 1/(60 + rank inside that channel);
    norm    — rank = 0.5 * score + 0.5 * (weight / max_weight).

    Unknown or empty -> `weights`: a typo in an env var must never silently
    change the shipped behaviour. The switch is process-global (the runner
    executes arms sequentially); it is not a per-call option.
    """
    mode = (os.environ.get("MSCODEBASE_FUSION") or "").strip().lower()
    return mode if mode in _FUSION_MODES else "weights"


def _fusion_rank(item: Dict[str, Any], idx: int, mode: str) -> float:
    score = float(item.get("score") or 0.0)
    weight = float(item.get("weight") or 0.0)
    if mode == "rrf":
        return 1.0 / (_RRF_K + idx)
    if mode == "norm":
        return 0.5 * score + 0.5 * (weight / _MAX_WEIGHT)
    return score + weight


_FILE_DEDUP_MODES = ("file",)


def _file_dedup_mode() -> str:
    """Answer with files before repeating a file, switchable for E72.

    The answer ranks chunks, but a "which file" question wants files: on
    sqlalchemy 72 rows covered 51 files (0.71 files per row), so 29% of the
    slots repeated a file already shown. Empty or unknown -> shipped order.
    """
    mode = (os.environ.get("MSCODEBASE_FILE_DEDUP") or "").strip().lower()
    return mode if mode in _FILE_DEDUP_MODES else ""


def _dedup_by_file(
    ranked: List[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """One row per file first, then the leftover rows fill the tail.

    The second pass is what keeps "where is X used" intact: when a question has
    fewer distinct files than `limit`, every row survives as before.
    """
    head: List[Dict[str, Any]] = []
    tail: List[Dict[str, Any]] = []
    seen: set = set()
    for row in ranked:
        file = row.get("file") or ""
        if file in seen:
            tail.append(row)
            continue
        seen.add(file)
        head.append(row)
    if len(head) >= limit:
        return head[:limit]
    return head + tail[: limit - len(head)]


def _merge(
    items: Iterable[Dict[str, Any]],
    limit: int,
    root: Any = None,
    demote_definitions: bool = False,
    query: str = "",
) -> List[Dict[str, Any]]:
    """Dedup by (file, line); keep the best rank and all channels.

    The rank formula is `weights` unless `MSCODEBASE_FUSION` names another arm;
    the policy on top of the merged row (definition demotion, non-answer bucket
    penalty) is expressed on each arm's own scale, so its numbers differ while
    its intent does not.

    `demote_definitions` is for "who calls X" questions: the definition is the
    wrong answer there. A small subtraction (0.4) was measured to change
    nothing — the definition still held 2.1 against a caller's 1.6 — so the
    definition is pinned to the tail instead: it stays in the answer as context,
    it just cannot lead a question that asked for call sites.
    """
    merged: Dict[Tuple[str, int], Dict[str, Any]] = {}
    votes: Dict[Tuple[str, int], set] = {}
    mode = _fusion_mode()
    seen_in_channel: Dict[str, int] = {}
    for item in items:
        file = _relpath(item.get("file") or item.get("file_path"), root)
        if not file:
            continue
        line = int(item.get("line") or 0)
        key = (file, line)
        channels = set(item.get("channels") or [])
        # Position inside its own channel: every channel appends its hits in
        # its own order, so a per-channel counter is that channel's rank, which
        # is what RRF needs instead of the hand weight. Channels write into one
        # list concurrently, hence the counter is per channel (not per position
        # in the list) and a channel can vote for a row only once.
        channel = sorted(channels)[0] if channels else ""
        idx = seen_in_channel.get(channel, 0)
        if channel:
            seen_in_channel[channel] = idx + 1
        rank = _fusion_rank(item, idx, mode)
        defines = bool(item.get("defines"))
        current = merged.get(key)
        if current is None:
            merged[key] = {
                "file": file,
                "line": line,
                "end_line": int(item.get("end_line") or 0),
                "text": str(item.get("text") or item.get("content") or "")[:200],
                "rank": rank,
                "defines": defines,
                "channels": channels,
                "symbol": str(item.get("symbol") or ""),
            }
            votes[key] = {channel} if channel else set()
        else:
            if mode == "rrf":
                # RRF sums one term per ranking that found the row; a second
                # item from the same channel is the same ranking, not a vote.
                if channel and channel not in votes[key]:
                    current["rank"] += rank
                    votes[key].add(channel)
            else:
                current["rank"] = max(current["rank"], rank)
            current["channels"] |= channels
            current["defines"] = current.get("defines") or defines
            if not current["text"] and item.get("text"):
                current["text"] = str(item["text"])[:200]
            if not current.get("symbol") and item.get("symbol"):
                current["symbol"] = str(item["symbol"])
            if not current.get("end_line") and item.get("end_line"):
                current["end_line"] = int(item["end_line"])
    # Demotion happens on the MERGED row, not per item: one row can carry both
    # a demoted definition item and a full-weight search item, and the merge
    # keeps the maximum - which silently undid the demotion.
    if demote_definitions:
        # The measured 0.5 is a weights-scale value. `norm` scores top out near
        # 0.6 and a neighbour on the `references` profile can sit at 0.12, so
        # any cap above that lets the definition lead again (found in review);
        # RRF ranks are ~0.017, where 0.5 is a no-op. Both experimental arms
        # therefore pin the definition to the tail, which is the policy.
        cap = {"weights": 0.5, "norm": 0.0, "rrf": 0.0}[mode]
        for entry in merged.values():
            if entry.get("defines"):
                entry["rank"] = min(entry["rank"], cap)

    # Non-answer buckets (tests / docs / historical docs) stay in the answer
    # as context and lose rank on a code question. The subtraction is measured
    # on the weights scale (-1.5/-2.0); `norm` uses 0.4x of it, and on RRF those
    # numbers would be a hard ban rather than the documented "not a cap", so
    # there the bucket goes to the tail instead.
    for entry in merged.values():
        penalty = _bucket_penalty(entry["file"], query, root)
        if not penalty:
            continue
        if mode == "rrf":
            entry["rank"] = 0.0
        else:
            entry["rank"] += penalty * (1.0 if mode == "weights" else 0.4)

    # Deterministic tie-break: channels append concurrently, so equal ranks used
    # to be ordered by arrival. Path order is stable across runs and identical
    # in every arm (a stable sort keeps it inside each rank group).
    ranked = sorted(merged.values(), key=lambda r: (r["file"], r["line"]))
    ranked.sort(key=lambda r: (r["rank"], len(r["channels"])), reverse=True)
    if _file_dedup_mode():
        return _dedup_by_file(ranked, limit)
    return ranked[:limit]


class InvestigateTool(MCPTool):
    """investigate — one question, all channels, one answer."""

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="investigate")

    @error_boundary("investigate", timeout_ms=30000)
    async def execute(
        self,
        query: str,
        limit: int = 8,
        project_root: str = "",
        include_neighbours: bool = False,
        rerank: Optional[bool] = None,
        hints: Optional[List[str]] = None,
    ) -> str:
        """hints: identifiers/terms the HOST extracted from the question.

        The server is language-agnostic on purpose: an agent that speaks
        Chinese, Russian or English already knows the code-shaped names, so it
        passes them here instead of the server carrying a dictionary per
        language. A hint also lifts the ask-for-identifier gate, because the
        question can now be answered exactly.
        """
        query = (query or "").strip()
        if not query:
            return "❌ investigate: пустой запрос"
        _pr = project_root or None
        await self.require_ready_project(explicit_project_root=_pr)
        limit = max(3, min(int(limit), 20))
        clean_hints = [
            str(hint).strip() for hint in (hints or []) if str(hint).strip()
        ][:_MAX_IDS]
        # Intent decides the order of the same hits (2026-11-08): "who calls X"
        # and "where is X defined" have the same identifiers and opposite
        # answers. The definition used to win both.
        intent_callers = _asks_for_callers(query)
        # Profile names are the measured table; the env var exists so an
        # experiment can compare them without a code edit. Unknown/empty -> the
        # documented default.
        weights = _PROFILES["references" if intent_callers else "def_first"]
        w_symbol = weights["symbol"]
        w_impact = weights["impact"]
        w_graph = weights["graph"]
        w_grep = weights["grep"]
        w_definition = weights["definition"]
        w_search = weights["search"]
        # "who raises X" is a statement-kind question: plain grep returns the
        # subclass lines (`class BadTimeSignature(BadSignature)`) and imports
        # first. Measured 2026-11-08 on itsdangerous: the raise sites were rows
        # 3-5 while a subclass declaration was row 1. The matched line says
        # which is which, so the raise statements get the evidence bonus.
        asks_raises = "raise" in query.lower()
        root = Path(self.resolve_indexer(explicit_project_root=_pr).project_path).resolve()

        # Hints first: the host knows the language, the server does not.
        identifiers = list(
            dict.fromkeys(clean_hints + _identifiers(query))
        )[:_MAX_IDS]
        # Deterministic rewrite gate before any channel runs: a Russian
        # question without a code-shaped name cannot be answered exactly, and
        # neighbours must not be presented as matches (XERJ N03). A hint means
        # the host DID name the subject, so the gate does not apply.
        if not clean_hints:
            rewrite = _asks_for_identifier(query)
            if rewrite:
                return rewrite
        searcher = self.resolve_searcher(explicit_project_root=_pr)
        symbol_index = self.resolve_symbol_index(explicit_project_root=_pr)

        degraded: List[str] = []
        items: List[Dict[str, Any]] = []
        symbol_lines: List[str] = []
        # Exact-string evidence (2026-11-08). The grep channel is the only one
        # that can say "this identifier occurs in this file". The semantic and
        # symbol channels always answer with neighbours, so without this count
        # an unanswerable question ("where is X implemented", X absent) looks
        # the same as a real answer — the class XERJ ships as a defect (#3021).
        exact: Dict[str, Any] = {"per": {}}

        async def _search() -> None:
            raw = await searcher.hybrid_search_async(
                query, limit=limit * 2, rerank=rerank
            ) or []
            for idx, row in enumerate(raw):
                item = _search_row_to_item(row, idx)
                item["weight"] = w_search
                items.append(item)

        def _symbols() -> None:
            # Some indexes (and the test doubles) only implement search_symbols.
            find_defs = getattr(symbol_index, "find_definitions", None)
            for ident in identifiers:
                # Exact name lookup FIRST (2026-11-08). `search_symbols` is a
                # fuzzy search: asked for `Signer` on itsdangerous it returned
                # HMACAlgorithm, and the real `class Signer` never entered the
                # answer. `find_definitions` is the exact index and returned the
                # true definition as hit #1 for all 9 definition tasks of the
                # external corpus — this is the "def-first" ranking that XERJ
                # measures as correct-file@1 (`def.rs:223-237`).
                exact = (find_defs(ident) if callable(find_defs) else None) or []
                for ref in exact[:3]:
                    name = getattr(ref, "symbol", "") or getattr(ref, "name", "")
                    file_path = getattr(ref, "file_path", "") or getattr(ref, "file", "")
                    line = int(getattr(ref, "line", 0) or 0)
                    kind = getattr(ref, "kind", "symbol")
                    if not name or not file_path:
                        continue
                    symbol_lines.append(f"• {name} ({kind}) — {file_path}:{line}")
                    items.append(
                        {
                            "file": file_path,
                            "line": line,
                            "text": f"{name} — {kind}",
                            "score": 0.0,
                            "weight": w_definition,
                            "defines": True,
                            "symbol": name,
                            "channels": {"definition"},
                        }
                    )
                for ref in (symbol_index.search_symbols(ident, top_k=3) or []):
                    name = getattr(ref, "symbol", "") or getattr(ref, "name", "")
                    file_path = getattr(ref, "file_path", "") or getattr(ref, "file", "")
                    line = int(getattr(ref, "line", 0) or 0)
                    kind = getattr(ref, "kind", "symbol")
                    if not name or not file_path:
                        continue
                    symbol_lines.append(f"• {name} ({kind}) — {file_path}:{line}")
                    items.append(
                        {
                            "file": file_path,
                            "line": line,
                            "text": f"{name} — {kind}",
                            "score": 0.0,
                            "weight": w_symbol,
                            "defines": "def" in str(kind).lower(),
                            "symbol": name,
                            "channels": {"symbol"},
                        }
                    )

        # Cooperative cancellation for the one CPU-bound channel: when its
        # timeout fires, the thread is told to stop instead of parsing on.
        grep_cancel = threading.Event()

        async def _grep() -> None:
            from src.mcp.tools.grep_tool import GrepCodeTool

            grep_root = Path(
                self.resolve_indexer(explicit_project_root=_pr).project_path
            ).resolve()
            idents = identifiers[:2]
            if not idents:
                return

            def _scan() -> Dict[str, Any]:
                tool = GrepCodeTool(self._services)
                try:
                    regex = re.compile(re.escape(idents[0]).encode("utf-8"))
                    extras = [
                        re.compile(re.escape(ident).encode("utf-8"))
                        for ident in idents[1:]
                    ]
                except re.error:
                    return {}
                # One walk, one read, one tree-sitter parse for BOTH identifiers.
                # Two separate calls cost ~2.7 s each on this repository and were
                # the biggest term in investigate (audit 2026-11-09); the counts
                # stay exact per identifier.
                return tool._search(  # noqa: SLF001
                    grep_root, None, regex, "code", max(limit * 4, 32), 0,
                    cancel=grep_cancel, extra_patterns=extras,
                )

            res = await asyncio.to_thread(_scan)
            matches = res.get("matches", [])
            # A cancelled scan saw only part of the tree: its count is not
            # "zero occurrences", it is "not finished". Publishing 0 would
            # let the abstention rule hide a real answer (red-team attack
            # 2026-11-08: cancel after one file, symbol lives on disk).
            if res.get("cancelled"):
                return
            for index, ident in enumerate(idents):
                if index == 0:
                    count = res.get("total", 0)
                else:
                    extra = res.get("extra_totals") or []
                    count = extra[index - 1] if index - 1 < len(extra) else 0
                exact["per"][ident] = int(count or 0)
            for match in matches:
                is_raise = asks_raises and bool(
                    re.search(r"\braise\b", str(match.get("text") or ""))
                )
                items.append(
                    {
                        "file": match["file"],
                        "line": match["line"],
                        "text": match["text"],
                        "score": 0.5 if is_raise else 0.0,
                        "weight": w_grep,
                        "symbol": idents[0],
                        "channels": {"grep"},
                    }
                )

        async def _names() -> None:
            """Compound code names built from prose (e.g. DEFAULT_LINE_LENGTH).

            A prose question has no identifier, so exact-name channels cannot
            fire. This channel asks FTS for the code-shaped variants and keeps
            only rows whose text contains the variant verbatim (case-sensitive),
            which is what separates `const.py` from fixtures that merely share
            the lowercase words.
            """
            variants = _name_variants(_name_words(query))
            if not variants:
                return
            searcher = self.resolve_searcher(explicit_project_root=_pr)
            store = getattr(searcher, "_chunk_store", None)
            if store is None:
                return

            def _lookup() -> List[Tuple[str, List[dict]]]:
                found: List[Tuple[str, List[dict]]] = []
                for variant in variants:
                    try:
                        rows = store.search(variant, limit=5) or []
                    except Exception:  # noqa: BLE001 — канал не валит ответ
                        rows = []
                    found.append((variant, rows))
                return found

            for variant, rows in await asyncio.to_thread(_lookup):
                for row in rows:
                    text = str(row.get("text_full") or row.get("text") or "")
                    if variant not in text:
                        continue
                    meta = row.get("metadata") or {}
                    items.append(
                        {
                            "file": meta.get("file", ""),
                            "line": int(meta.get("start_line") or 0),
                            "text": f"{variant} — name match",
                            "score": 0.0,
                            "weight": 3.0,
                            "symbol": variant,
                            "channels": {"name"},
                        }
                    )

        async def _run(
            name: str,
            func,
            is_async: bool,
            timeout: float = _CHANNEL_TIMEOUT,
            cancel_event: "threading.Event | None" = None,
        ) -> None:
            try:
                if is_async:
                    await asyncio.wait_for(func(), timeout=timeout)
                else:
                    await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout)
            except asyncio.TimeoutError:
                # wait_for cannot stop a thread; ask the work to stop itself,
                # otherwise the abandoned parser competes with the next query.
                if cancel_event is not None:
                    cancel_event.set()
                degraded.append(f"{name}:timeout")
            except Exception as exc:  # noqa: BLE001 — канал не валит ответ
                degraded.append(f"{name}:{type(exc).__name__}")

        await asyncio.gather(
            _run("search", _search, True),
            _run("symbols", _symbols, False),
            _run("names", _names, True, 5.0),
            _run("grep", _grep, True, _GREP_TIMEOUT, cancel_event=grep_cancel),
        )

        # ─── Pass 2: channels that need a symbol/file from pass 1 ───
        first_pass = _merge(items, 50, root, intent_callers, query=query)
        top_files = [row["file"] for row in first_pass if row["file"]][:3]
        top_names = identifiers[:2]

        def _impact() -> None:
            for name in top_names:
                res = symbol_index.get_impact_analysis(name, 2) or {}
                cg = res.get("call_graph") or {}
                defs = cg.get("definition") or []
                if isinstance(defs, dict):
                    defs = [defs]
                if not defs:
                    continue
                first = defs[0] if isinstance(defs[0], dict) else {}
                items.append(
                    {
                        "file": first.get("file") or "",
                        "line": first.get("line") or 0,
                        "text": (
                            f"impact {name}: risk={res.get('risk_level', '?')}, "
                            f"affected={len(res.get('affected_files') or [])}"
                        ),
                        "score": 0.0,
                        "weight": w_impact,
                        "symbol": name,
                        "channels": {"impact"},
                    }
                )

        def _graph() -> None:
            for name in top_names:
                for caller in (symbol_index.get_callers(name) or [])[:3]:
                    items.append(
                        {
                            "file": getattr(caller, "file_path", "") or getattr(caller, "file", ""),
                            "line": int(getattr(caller, "line", 0) or 0),
                            "text": f"caller of {name}",
                            "score": 0.0,
                            "weight": w_graph,
                            "symbol": name,
                            "channels": {"graph"},
                        }
                    )

        def _tests() -> None:
            from concurrent.futures import ThreadPoolExecutor

            from src.core.test_impact import predict_affected_tests

            rels = [
                rel for rel in top_files
                if not rel.startswith("tests/") and rel != "(memory)"
            ]
            if not rels:
                return

            def _one(rel_file: str) -> tuple[str, Dict[str, Any]]:
                try:
                    return rel_file, predict_affected_tests([rel_file], str(root)) or {}
                except Exception:  # noqa: BLE001 — канал не валит ответ
                    return rel_file, {}

            # Per-file predictions are independent (~0.6 s each on a 500-file
            # repo). Sequentially three files cost 1.8 s (audit 2026-11-09);
            # together they cost one.
            with ThreadPoolExecutor(max_workers=min(3, len(rels))) as pool:
                for rel_file, pred in pool.map(_one, rels):
                    for test in (pred.get("affected_tests") or [])[:3]:
                        items.append(
                            {
                                "file": test,
                                "line": 0,
                                "text": f"covers {rel_file}",
                                "score": 0.0,
                                "weight": 0.1,
                                "channels": {"tests"},
                            }
                        )

        def _memory() -> None:
            from src.core.intelligence.store import IntelligenceStore

            nodes = IntelligenceStore(root)._load_json("project_memory.json")  # noqa: SLF001
            for node in _memory_hits(nodes, query):
                items.append(
                    {
                        "file": "(memory)",
                        "line": 0,
                        "text": node,
                        "score": 0.0,
                        "weight": 0.4,
                        "channels": {"memory"},
                    }
                )

        await asyncio.gather(
            _run("impact", _impact, False),
            _run("graph", _graph, False),
            _run("tests", _tests, False),
            _run("memory", _memory, False),
        )

        merged = _merge(items, limit, root, intent_callers, query=query)

        # Abstain on insufficient evidence (2026-11-08). The semantic channel
        # always returns neighbours, so an unanswerable question used to produce
        # eight confident-looking `file:line` rows - the "success-shaped failure"
        # class (#3021/#3015). When no identifier occurs in the code AND the
        # symbol is unknown to the graph, the neighbours are not evidence: say
        # "not found" and stop. Two guards against hiding a real answer:
        #   * `per` exists only when the grep channel COMPLETED - a degraded
        #     channel means "unknown", and unknown must never become "absent";
        #   * a symbol known to the graph suppresses nothing: the name is real,
        #     so its neighbours are worth showing.
        withheld = 0
        per = exact.get("per") or {}
        # The SUBJECT is what was asked about. A trailing capitalised word
        # ("Corpus Hub") may occur in prose while the subject does not; counting
        # it as evidence kept the neighbours for a question that has no answer.
        subject = next(iter(per)) if per else ""
        # Fail OPEN: only an explicit "no such symbol" allows abstention. An
        # index that cannot answer (older shim, test double, exception) means
        # "unknown", and unknown must not hide the answer.
        known = True
        if subject and per.get(subject) == 0:
            has_symbol = getattr(symbol_index, "has_symbol", None)
            if callable(has_symbol):
                try:
                    known = bool(has_symbol(subject))
                except Exception:  # noqa: BLE001 — cannot answer means unknown
                    known = True
        if _abstains(per, known, include_neighbours):
            withheld = len(merged)
            merged = []

        # Deterministic evidence gate (2026-11-10). Every row is checked
        # against the file on disk, the symbol index and the call graph before
        # it is presented as a match: a definition must be a declaration at
        # that line, a path must exist, a stale file is named as stale. The
        # gate annotates; it does not invent rows. See src/core/search/evidence.py.
        report = None
        if _evidence_gate_enabled():
            report = assess(
                merged,
                root=root,
                identifiers=identifiers,
                symbol_index=symbol_index,
                store=getattr(searcher, "_chunk_store", None),
                intent="references" if intent_callers else "explore",
                abstain_hint=bool(withheld),
            )
            kept = set(report.kept_indices)
            merged = [row for index, row in enumerate(merged) if index in kept]
            if report.promote:
                keys = set(report.promote)
                merged.sort(
                    key=lambda row: 0 if (row["file"], row["line"]) in keys else 1
                )

        text = self._format(
            query, identifiers, merged, symbol_lines, degraded, exact, report
        )
        if withheld:
            text += _retry_hint(query, withheld, limit)
        return text

    def _format(
        self,
        query: str,
        identifiers: List[str],
        merged: List[Dict[str, Any]],
        symbol_lines: List[str],
        degraded: List[str],
        exact: Optional[Dict[str, Any]] = None,
        evidence: Optional[EvidenceReport] = None,
    ) -> str:
        lines = [f"🧭 investigate: `{query}`"]
        if identifiers:
            lines.append(f"   identifiers: {', '.join(identifiers)}")
        lines.append(
            f"   results: {len(merged)}"
            + (f" | degraded: {', '.join(degraded)}" if degraded else "")
        )
        per = {
            str(k): int(v or 0)
            for k, v in ((exact or {}).get("per") or {}).items()
        }
        if per:
            counts = ", ".join(f"{k}={v}" for k, v in list(per.items())[:3])
            subject = next(iter(per))
            if per[subject] == 0 and merged:
                lines.append(
                    f"   ⚠️ exact: {counts} — the first identifier does not occur "
                    "in the indexed code; the results below are neighbours, not "
                    "matches."
                )
            else:
                lines.append(f"   exact: {counts}")
        if evidence is not None:
            # A deterministic score, not a probability: the number of
            # independent facts that hold for the best row.
            lines.append(
                f"   verdict: {evidence.verdict} "
                f"({evidence.confidence:.2f}) — {evidence.reason}"
            )
            if evidence.missing:
                lines.append(
                    f"   ⚠️ missing: {evidence.missing} path(s) are not on disk "
                    "(the index may be stale — notify_change/reindex)"
                )
            if evidence.verdict == "abstain" and merged:
                # An abstain verdict next to eight rows reads contradictory
                # unless the rows are named for what they are.
                lines.append(
                    "   ⚠️ the rows below are neighbours — no row carries "
                    "evidence for this question"
                )
        lines.append("")

        if not merged:
            lines.append("ℹ️ Ничего не найдено. Запрос не подтверждён ни одним каналом.")
            return "\n".join(lines)

        marks = evidence.by_location() if evidence is not None else {}
        for i, row in enumerate(merged, 1):
            channels = "+".join(sorted(row["channels"]))
            if row["file"] == "(memory)":
                lines.append(f"{i}. [memory] {row['text']}  [{channels}]")
                continue
            marker = marks.get((row["file"], row["line"]))
            suffix = marker.marker() if marker is not None else ""
            shown_line = row["line"]
            if marker is not None:
                # The verified declaration wins over the matched term; both
                # win over the chunk start.
                shown_line = (
                    marker.decl_line or marker.found_line or row["line"]
                )
            lines.append(f"{i}. {row['file']}:{shown_line}  [{channels}]{suffix}")
            if row["text"]:
                lines.append(f"   {row['text'].strip()[:180]}")

        if evidence is not None and evidence.dossier:
            lines.append("")
            lines.append("📎 dossier:")
            lines.extend(f"   {line}" for line in evidence.dossier)

        if symbol_lines:
            lines.append("")
            lines.append("Символы:")
            lines.extend(symbol_lines[:6])

        first = merged[0]
        lines.append("")
        lines.append(
            f"Дальше: get_symbol_info(\"{identifiers[0] if identifiers else ''}\") "
            f"| impact_analysis | read_live_file(\"{first['file']}\")"
        )
        return "\n".join(lines)
