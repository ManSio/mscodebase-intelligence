"""
stale_detector v2 — Content-hash based doc/code drift detection.

Instead of matching version strings in text, this uses PropertyGraph
content hashes to detect when documentation references a symbol whose
code has changed since the doc was written.

Usage:
    python -m tools.stale_detector.graph_stale_check               # report
    python -m tools.stale_detector.graph_stale_check --docs-dir docs

Anchor format in markdown:
    <!-- doc-ref: function_name@abcdef01 -->

Where @abcdef01 is the first 8 chars of the symbol's content hash
at the time the doc was written. If the code changes, the hash diverges.

Minimal viable approach — extend to full Backstage/Swimm later.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Pattern: <!-- doc-ref: symbol_name@hash -->
_DOC_REF_RE = re.compile(r"<!--\s*doc-ref:\s*(\w+)@([0-9a-f]{8})\s*-->")


@dataclass
class StaleRef:
    doc_path: str
    line: int
    symbol: str
    doc_hash: str
    current_hash: str


def compute_symbol_hash(source_path: Path, symbol_name: str) -> Optional[str]:
    """Compute SHA256 of a symbol's source code lines.

    Finds `def symbol_name` or `class symbol_name` and hashes everything
    until the next def/class at the same indentation level.
    """
    if not source_path.exists():
        return None

    try:
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    # Find symbol start
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if re.match(rf"(async\s+)?(def|class)\s+{re.escape(symbol_name)}\b", stripped):
            start_idx = i
            break

    if start_idx is None:
        return None

    # Find symbol end (next def/class at same or lesser indentation)
    symbol_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(lines[i]) - len(lines[i].lstrip())
        if line_indent <= symbol_indent and re.match(r"(async\s+)?(def|class)\s+", stripped):
            end_idx = i
            break

    body = "\n".join(lines[start_idx:end_idx])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def scan_source_for_hashes(
    src_dir: Path,
    extensions: tuple = (".py",),
) -> Dict[str, str]:
    """Scan source directory and compute hashes for all top-level symbols.

    Returns: {symbol_name: sha256_hex}
    """
    hashes: Dict[str, str] = {}

    for ext in extensions:
        for py_file in src_dir.rglob(f"*{ext}"):
            if any(skip in str(py_file) for skip in ("__pycache__", ".venv", "venv", "node_modules")):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for match in re.finditer(r"^(async\s+)?(def|class)\s+(\w+)", content, re.MULTILINE):
                name = match.group(3)
                h = compute_symbol_hash(py_file, name)
                if h:
                    hashes[name] = h

    return hashes


def find_doc_refs(doc_path: Path) -> List[Tuple[int, str, str]]:
    """Extract (line_number, symbol_name, hash) from <!-- doc-ref: name@hash --> anchors."""
    results = []
    try:
        lines = doc_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return results

    for i, line in enumerate(lines, 1):
        m = _DOC_REF_RE.search(line)
        if m:
            results.append((i, m.group(1), m.group(2)))

    return results


def check_graph_staleness(
    src_dir: Path,
    docs_dir: Path,
) -> List[StaleRef]:
    """Compare doc-ref hashes against current source code hashes.

    Args:
        src_dir: Source code root (e.g. src/)
        docs_dir: Documentation root (e.g. docs/)

    Returns:
        List of StaleRef where doc hash != current hash.
    """
    source_hashes = scan_source_for_hashes(src_dir)
    stale: List[StaleRef] = []

    for md_file in docs_dir.rglob("*.md"):
        if any(skip in str(md_file) for skip in ("__pycache__", ".venv", "node_modules")):
            continue

        for line_num, symbol, doc_hash in find_doc_refs(md_file):
            current = source_hashes.get(symbol)
            if current is None:
                continue  # symbol not found — might be external
            if current[:8] != doc_hash:
                stale.append(StaleRef(
                    doc_path=str(md_file),
                    line=line_num,
                    symbol=symbol,
                    doc_hash=doc_hash,
                    current_hash=current[:8],
                ))

    return stale


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Content-hash doc/code drift detector v2")
    parser.add_argument("--src-dir", default="src", help="Source directory")
    parser.add_argument("--docs-dir", default="docs", help="Documentation directory")
    parser.add_argument("--report-format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    src_dir = project_root / args.src_dir
    docs_dir = project_root / args.docs_dir

    if not src_dir.exists():
        print(f"Source dir not found: {src_dir}")
        sys.exit(1)
    if not docs_dir.exists():
        print(f"Docs dir not found: {docs_dir}")
        sys.exit(1)

    stale = check_graph_staleness(src_dir, docs_dir)

    if args.report_format == "json":
        import json
        print(json.dumps([{
            "doc": s.doc_path,
            "line": s.line,
            "symbol": s.symbol,
            "doc_hash": s.doc_hash,
            "current_hash": s.current_hash,
        } for s in stale], indent=2))
    else:
        if not stale:
            print("✅ No doc/code drift detected.")
        else:
            print(f"⚠️  Found {len(stale)} stale doc-ref(s):\n")
            for s in stale:
                print(f"  {s.doc_path}:{s.line} — {s.symbol}")
                print(f"    doc hash:     {s.doc_hash}")
                print(f"    current hash: {s.current_hash}")

    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
