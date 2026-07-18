"""
Sandbox experiment: file-level vs chunk-level content-addressed cache.

Goal: measure how many chunks get RE-EMBEDDED when 1 function in a large
file changes, under current (file-level md5) vs proposed (chunk-level sha256)
caching.

This does NOT touch production code. It simulates the indexer's chunking
logic locally on real project files.

Run:
    python sandbox/chunk_hash_exp/benchmark_chunk_cache.py
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHUNK_SIZE = 512
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Two modes selected by env CHUNK_MODE.

    'sliding' (default): naive char window — what the first benchmark used.
    'ast'    : simulate tree-sitter-aware chunking where each chunk is a
               stable syntactic unit (function/class). A mid-file edit then
               shifts NOTHING except the edited unit.
    """
    mode = os.getenv("CHUNK_MODE", "sliding")
    if mode == "ast":
        # Split by blank-line-separated blocks as a cheap proxy for
        # tree-sitter function/class boundaries.
        blocks = [b for b in text.split("\n\n") if b.strip()]
        return blocks
    if not text:
        return []
    step = max(1, size - overlap)
    chunks = []
    for i in range(0, len(text), step):
        chunk = text[i : i + size]
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def file_level_cache(old_text: str, new_text: str) -> tuple[int, int]:
    """Current behaviour: whole file re-embedded if md5 differs.

    Returns (chunks_embedded, total_chunks).
    """
    old_chunks = chunk_text(old_text)
    new_chunks = chunk_text(new_text)
    total = len(new_chunks)
    if hashlib.md5(old_text.encode()).hexdigest() == hashlib.md5(new_text.encode()).hexdigest():
        return 0, total
    # file changed -> ALL chunks re-embedded
    return total, total


def chunk_level_cache(old_text: str, new_text: str) -> tuple[int, int]:
    """Proposed: per-chunk sha256, only changed chunks re-embedded.

    Content-addressed (set-based): a new chunk is 'unchanged' if its hash
    exists ANYWHERE in the old chunk set — not just at the same position.
    This survives positional shift from overlap windows (the case that
    hurt the naive position-aligned version).
    """
    old_chunks = chunk_text(old_text)
    new_chunks = chunk_text(new_text)
    total = len(new_chunks)
    old_hashes = {hashlib.sha256(c.encode()).hexdigest() for c in old_chunks}
    new_hashes = [hashlib.sha256(c.encode()).hexdigest() for c in new_chunks]
    re_embed = sum(1 for h in new_hashes if h not in old_hashes)
    return re_embed, total


def simulate_edit(text: str, edit_ratio: float = 0.05) -> str:
    """Perturb ~edit_ratio of the file content (simulates 1 function change)."""
    lines = text.splitlines()
    if len(lines) < 10:
        return text
    n_edit = max(1, int(len(lines) * edit_ratio))
    idx = random.randint(5, len(lines) - n_edit - 5)
    for j in range(idx, idx + n_edit):
        lines[j] = lines[j] + "  # edited"
    return "\n".join(lines)


def main() -> int:
    py_files = list(PROJECT_ROOT.rglob("*.py"))
    # Exclude sandbox + venv-like dirs
    py_files = [
        f for f in py_files
        if "sandbox" not in str(f) and ".venv" not in str(f)
        and "node_modules" not in str(f)
    ]
    # Only files with >20 chunks (large files where the bug hurts most)
    candidates = []
    for f in py_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if len(chunk_text(text)) >= 20:
            candidates.append((f, text))

    if not candidates:
        print("No large .py files found")
        return 1

    random.seed(42)
    total_file_embed = 0
    total_chunk_embed = 0
    total_chunks_all = 0
    n_files = 0

    # Two edit intensities to bracket real usage
    for edit_ratio in (0.01, 0.05):
        print(f"=== edit_ratio={edit_ratio} (fraction of lines changed) ===")
        total_file_embed = 0
        total_chunk_embed = 0
        total_chunks_all = 0
        n_files = 0
        for f, text in candidates[:30]:
            edited = simulate_edit(text, edit_ratio)
            fe, ft = file_level_cache(text, edited)
            ce, ct = chunk_level_cache(text, edited)
            total_file_embed += fe
            total_chunk_embed += ce
            total_chunks_all += ct
            n_files += 1

        saved = total_file_embed - total_chunk_embed
        pct = (saved / total_file_embed * 100) if total_file_embed else 0
        print(f"  Files tested      : {n_files}")
        print(f"  Total chunks       : {total_chunks_all}")
        print(f"  File-level re-embed: {total_file_embed} ({total_file_embed/total_chunks_all*100:.1f}%)")
        print(f"  Chunk-level re-embed:{total_chunk_embed} ({total_chunk_embed/total_chunks_all*100:.1f}%)")
        print(f"  SAVED             : {saved} chunks ({pct:.1f}% fewer)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
