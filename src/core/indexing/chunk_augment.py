"""E26 file-level chunk augmentation (Phase 1 of the approved stack migration).

Prepends FILE/SYMBOLS/DOC context to chunk texts so sparse retrieval
(BM25/FTS5) sees file-level symbols — measured E26: +2 hit@1, 0 regressions
(experiments/e26_ast, frozen AUG_TEMPLATE).

The flag is OFF by default: existing indexes are byte-identical until the
owner flips MSCODEBASE_AUGMENT_CHUNKS=true AND reindexes texts. Flipping
changes every chunk text, hence every chunk_hash (sha256 of text), so vectors
recompute instead of going stale.

Pure module (only stdlib `re`/`os`) — no project imports, trivially testable.
"""

from __future__ import annotations

import os
import re

DEF_RE = re.compile(r"^(def|class)\s+(\w+)", re.M)


def augment_enabled() -> bool:
    """E26 augmentation flag. Default OFF (no behavior change)."""
    return os.getenv("MSCODEBASE_AUGMENT_CHUNKS", "").lower() in ("1", "true", "yes")


def module_doc(body: str) -> str:
    """First module docstring, whitespace-folded, capped at 500 chars (or '')."""
    m = re.match(r'\s*"""(.*?)"""', body, re.S) or re.match(r"\s*'''(.*?)'''", body, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1))[:500]


def top_level_defs(body: str) -> list[str]:
    """Top-level `def`/`class` names in file order, deduplicated."""
    seen: set[str] = set()
    ordered: list[str] = []
    for _, name in DEF_RE.findall(body):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def build_file_prefix(rel_path: str, body: str) -> str:
    """Frozen E26 AUG_TEMPLATE header for one file (no trailing chunk text)."""
    rel = rel_path.replace("\\", "/")
    return f"FILE: {rel}\nSYMBOLS: {' '.join(top_level_defs(body))}\nDOC: {module_doc(body)}\n"
