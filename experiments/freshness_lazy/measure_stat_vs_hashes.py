"""Replicated measurement: stat-sweep vs sha256-sweep over the honest corpus.

Phase Zero fixes (2026-09-18):
- Corpus = src/ + tests/ + experiments/ + scripts/ + tools/ + adapters/, MINUS
  venv/, build/, __pycache__/, .git/, .local/ (all gitignored; first attempt hit
  9110 venv files and hung).
- flush=True everywhere (non-tty stdout is buffered; first run printed nothing
  and looked frozen).
Hypothesis: a lazy freshness check based on Path.stat() (mtime+size) is
hundreds of times cheaper than the existing FreshnessChecker (sha256 of every
indexed file), so it can run on every search for near-zero cost and close
KI-109 (new files invisible to the index).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

REPO = Path(r"D:\Project\MSCodeBase")
SKIP_DIRS = {"venv", ".venv", "build", "__pycache__", ".git", ".local", ".pytest_cache", ".ruff_cache"}
SKIP_FILES = {"install_artifacts.log"}
ALL_EXTS = {
    ".py", ".rs", ".go", ".java", ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".r", ".m", ".mm", ".ts", ".tsx", ".js", ".jsx", ".c", ".cpp", ".h", ".hpp",
    ".css", ".scss", ".sass", ".less", ".html", ".xml", ".json", ".yaml", ".yml",
    ".toml", ".md", ".ipynb", ".sql", ".sh", ".bash", ".txt",
}


def corpus(exts: set[str] | None = None) -> list[Path]:
    exts = exts or {".py"}
    result = []
    for p in REPO.rglob("*"):
        if p.is_dir():
            continue
        if p.suffix.lower() not in exts:
            continue
        parts = [x for x in p.relative_to(REPO).parts]
        if any(skip in parts for skip in SKIP_DIRS):
            continue
        if p.name in SKIP_FILES:
            continue
        result.append(p)
    return result


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(str(path), "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    py_files = corpus()
    print(f"honest corpus: {len(py_files)} files", flush=True)

    # 1) stat sweep (mtime + size), 3 runs
    stat_times = []
    seen = []
    for run in range(3):
        t0 = time.perf_counter()
        seen = []
        for p in py_files:
            st = p.stat()
            seen.append((str(p), st.st_mtime_ns, st.st_size))
        stat_times.append((time.perf_counter() - t0) * 1000)
        print(f"  stat sweep run{run+1}: {round(stat_times[-1], 2)} ms", flush=True)
    print(f"  stat entries: {len(seen)}", flush=True)

    # 2) sha256 sweep (what FreshnessChecker does), 1 run
    t0 = time.perf_counter()
    hashes = []
    for p in py_files:
        hashes.append((str(p), sha256_of(p)))
    sha_ms = (time.perf_counter() - t0) * 1000
    print(f"  sha256 sweep: {round(sha_ms, 1)} ms", flush=True)
    print(f"  sha256 entries: {len(hashes)}", flush=True)

    # 3) relative cost
    ratio = sha_ms / stat_times[2]
    per_file_us = stat_times[2] / len(py_files) * 1000
    print(f"ratio sha256/stat: {round(ratio, 1)}x", flush=True)
    print(f"mean stat per file: {round(per_file_us, 2)} us", flush=True)
    print(f"projected stat for 574 indexed files: {round(stat_times[2] / len(py_files) * 574, 1)} ms", flush=True)

    # 4) full INDEX_EXTENSIONS corpus (closer to the real 574-file index)
    all_files = corpus(ALL_EXTS)
    print(f"\nfull INDEX_EXTENSIONS corpus: {len(all_files)} files", flush=True)
    t0 = time.perf_counter()
    all_stat = []
    for p in all_files:
        st = p.stat()
        all_stat.append((str(p), st.st_mtime_ns, st.st_size))
    full_ms = (time.perf_counter() - t0) * 1000
    print(f"  stat sweep full corpus: {round(full_ms, 2)} ms", flush=True)
    print(f"  mean stat per file: {round(full_ms / len(all_files) * 1000, 2)} us", flush=True)


if __name__ == "__main__":
    main()
