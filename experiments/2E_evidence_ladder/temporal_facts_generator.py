#!/usr/bin/env python3
"""temporal_facts_generator.py — Exp 2-E, Rung 4 (temporal_first): git-археология.

Детерминированный генератор temporal-claims (ground truth БЕЗ LLM, из git):

  removed  — символ/файл СУЩЕСТВОВАЛ на коммите C, удалён до HEAD:
             claim (наст. время) «X определён в F» → truth=false (на HEAD),
             был правдой на C (validated: git show C:F содержит X).
  real     — текущие символы: «X определён в F» → truth=true.
  absent   — вымышленные имена (grep-0 в репо): truth=false (контроль).

Формат выхода — как v4_rep + поля valid_at_commit / evidence_git
(hash/date/subject/branch коммита, где факт был правдой). Всё без LLM.

Usage:
  python experiments/2E_evidence_ladder/temporal_facts_generator.py [--seed 7] [--out PATH]
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = ROOT / "experiments" / "2E_evidence_ladder"
SRC = ROOT / "src"

SEED = 7
N_DELETE_COMMITS = 40        # сколько удалений смотрим (git log -N --diff-filter=D)
N_REAL_FILES = 16
N_ABSENT = 8
N_REMOVED = 12
BRANCH = ""


def _git(*args: str) -> str:
    """git-вызов, короткоживущий (не daemon-тред → §5.16 не про нас)."""
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=30)
    if r.returncode != 0:
        return ""
    return r.stdout


def _ast_names(text: str) -> list[str]:
    """Топ-уровневые классы/функции из текста (git show C:file)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    return [n.name for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]


def _git_branch() -> str:
    global BRANCH
    if not BRANCH:
        BRANCH = _git("rev-parse", "--abbrev-ref", "HEAD").strip() or "?"
    return BRANCH


def _deleted_files(limit: int) -> list[tuple[str, str, str, str]]:
    """[(commit, date, subject, path)] — файлы, удалённые в последних limit коммитах."""
    out = _git("log", f"-{limit}", "--diff-filter=D", "--name-only",
               "--format=COMMIT %H|%ad|%s", "--date=short")
    files: list[tuple[str, str, str, str]] = []
    cur: tuple[str, str, str] | None = None
    for line in out.splitlines():
        if line.startswith("COMMIT "):
            h, d, s = line[7:].split("|", 2)
            cur = (h, d, s)
        elif line.strip() and cur and line.strip().endswith(".py"):
            files.append((cur[0], cur[1], cur[2], line.strip()))
    return files


def _symbols_in_commit(commit: str, path: str) -> list[str]:
    """Символы файла на коммите (пусто, если файла там не было)."""
    text = _git("show", f"{commit}:{path}")
    return _ast_names(text)


def _symbols_at_head(path: Path) -> list[str]:
    try:
        return _ast_names(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def _grep_zero(name: str) -> bool:
    """Имя не встречается в src/**/*.py (детерминированная проверка)."""
    pat = re.compile(rf"\b{re.escape(name)}\b")
    for f in SRC.rglob("*.py"):
        try:
            if pat.search(f.read_text(encoding="utf-8", errors="replace")):
                return False
        except OSError:
            continue
    return True


def generate(seed: int = SEED) -> list[dict]:
    import random
    rng = random.Random(seed)
    facts: list[dict] = []

    # 1) removed: файл удалён, символ был на C~1
    seen: set[tuple[str, str]] = set()
    for commit, date, subject, path in _deleted_files(N_DELETE_COMMITS):
        if len(facts) >= N_REMOVED:
            break
        syms = _symbols_in_commit(f"{commit}~1", path)
        if not syms:
            continue
        sym = syms[0]
        if (sym, path) in seen:
            continue
        seen.add((sym, path))
        facts.append({
            "id": f"T{len(facts) + 1:02d}", "truth": False, "kind": "removed",
            "subject": path.split("/")[-1][:-3], "value": sym,
            "claim": f"Символ {sym} определён в файле {path}",
            "support_patterns": [f"file:{path}"],
            "valid_at_commit": commit, "was_true": True,
            "evidence_git": {"hash": commit, "date": date,
                             "subject": subject, "branch": _git_branch()},
        })

    # 2) removed-символ в живущем файле: был в C, нет в HEAD (по свежим коммитам)
    log = _git("log", "-30", "--format=%H|%ad|%s", "--date=short", "--", "src")
    for line in log.splitlines()[:N_REMOVED]:
        if len(facts) >= N_REMOVED * 2:
            break
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        commit, date, subject = parts
        files = _git("show", "--name-only", "--format=", commit, "--", "src").splitlines()
        py = [f.strip() for f in files if f.strip().endswith(".py")]
        rng.shuffle(py)
        for path in py[:3]:
            old = _symbols_in_commit(commit, path)
            head = _symbols_at_head(ROOT / path)
            diff = [s for s in old if s not in head]
            if not diff or (diff[0], path) in seen:
                continue
            sym = diff[0]
            seen.add((sym, path))
            facts.append({
                "id": f"T{len(facts) + 1:02d}", "truth": False, "kind": "removed",
                "subject": path.split("/")[-1][:-3], "value": sym,
                "claim": f"Символ {sym} определён в файле {path}",
                "support_patterns": [f"file:{path}"],
                "valid_at_commit": commit, "was_true": True,
                "evidence_git": {"hash": commit, "date": date,
                                 "subject": subject, "branch": _git_branch()},
            })
            break

    # 3) real: текущие символы (детерминированный сэмпл файлов)
    py_files = sorted(SRC.rglob("*.py"))
    rng.shuffle(py_files)
    for f in py_files:
        if len(facts) >= N_REMOVED * 2 + N_REAL_FILES:
            break
        syms = _symbols_at_head(f)
        if not syms:
            continue
        sym = syms[0]
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if (sym, rel) in seen:
            continue
        seen.add((sym, rel))
        commit = _git("log", "-1", "--format=%H|%ad|%s", "--date=short", "--", rel)
        h, d, s = (commit.split("|", 2) + ["?", "?", "?"])[:3]
        facts.append({
            "id": f"T{len(facts) + 1:02d}", "truth": True, "kind": "real",
            "subject": rel.split("/")[-1][:-3], "value": sym,
            "claim": f"Символ {sym} определён в файле {rel}",
            "support_patterns": [f"file:{rel}"],
            "valid_at_commit": h or None, "was_true": True,
            "evidence_git": {"hash": h, "date": d, "subject": s, "branch": _git_branch()},
        })

    # 4) absent: вымышленные имена, grep-0
    candidates = ["TemporalSnapshotEngine", "GitProvenanceIndexer", "CommitTimelineStore",
                  "BlameVectorizer", "EpochDeltaTracker", "VersionLattice", "ChangeSetOracle",
                  "RetrospectiveSymbolCache"]
    for name in candidates:
        if len(facts) >= N_REMOVED * 2 + N_REAL_FILES + N_ABSENT:
            break
        if not _grep_zero(name):
            continue
        facts.append({
            "id": f"T{len(facts) + 1:02d}", "truth": False, "kind": "absent",
            "subject": "?", "value": name,
            "claim": f"Символ {name} определён в файле src/core/{name.lower()}.py",
            "support_patterns": [f"file:src/core/{name.lower()}.py"],
            "valid_at_commit": None, "was_true": False,
            "evidence_git": {"hash": "", "date": "", "subject": "", "branch": _git_branch()},
        })

    return facts


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else SEED
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    facts = generate(seed)
    doc = {
        "_meta": {
            "experiment": "Exp 2-E Evidence Ladder — temporal facts (Rung 4)",
            "date": "2026-08-15",
            "seed": seed,
            "branch": _git_branch(),
            "design": "removed (был правдой на C, false@HEAD) + real (true@HEAD) + absent (grep-0)",
            "n_total": len(facts),
        },
        "facts": facts,
    }
    sha = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]
    out = out_dir / f"temporal_facts_{sha}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter
    print(f"[temporal] N={len(facts)} kinds={dict(Counter(f['kind'] for f in facts))} sha={sha}")
    print(f"[temporal] written: {out.relative_to(ROOT)}")
    for f in facts[:4]:
        print(f"  {f['id']} {f['kind']:7s} truth={f['truth']} @{f['valid_at_commit']} | {f['claim']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — §5.11: try/except в каждом скрипте
        import traceback
        traceback.print_exc()
        sys.exit(1)
