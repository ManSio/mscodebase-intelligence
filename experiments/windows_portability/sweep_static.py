"""WINDOWS-PORTABILITY SWEEP — static, over Tom's repo.

Implements the static half of HYPOTHESES.md (groups A/B/C/D/E). Reports the
exact site (file:line, the expression) for every hazard class, so the counts
are checkable and each site can be turned into an experiment.

Read-only. No file is modified. Foreign repo: analysed in place, never written.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

SRC = pathlib.Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479")
SCRIPTS = SRC / "scripts"


def txt(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def site(node: ast.AST) -> str:
    return f"L{getattr(node, 'lineno', 0)}"


# ---------------------------------------------------------------- A: path shape
RE_HARDCODED_PATH_LITERAL = re.compile(r"""["'][^"'\n]*(?:^|[/=])[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-/]*["']""")
RE_PYTHON3 = re.compile(r"\bpython3\b")


def group_a() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for p in sorted(SCRIPTS.glob("*.py")):
        for i, line in enumerate(txt(p).splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            # A1: relpath / abspath delivered into a string
            if re.search(r"relpath\(|abspath\(", line):
                out["A1 relpath/abspath into text"].append(f"{p.name}:{i}  {s[:100]}")
            # A2: hardcoded forward-slash path used for lookup or comparison
            for m in re.finditer(r"""["']((?:memory|catalogue|docs|scripts|starter|scratch)/[^"']*)["']""", line):
                out["A2 hardcoded '/' path literal"].append(f"{p.name}:{i}  {m.group(0)}  |  {s[:80]}")
            # A3: glob/rglob/iterdir with a slash in the pattern
            if re.search(r"""(r?glob|iterdir|is_dir|is_file|exists)\(\s*["'][^"']*/""", line):
                out["A3 glob/Path pattern with '/'"].append(f"{p.name}:{i}  {s[:100]}")
            if RE_PYTHON3.search(line) and "https" not in line:
                out["A3b literal 'python3' invocation"].append(f"{p.name}:{i}  {s[:100]}")
    return out


# ------------------------------------------------------------- B: process side
def group_b() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for p in sorted(SCRIPTS.glob("*.py")):
        src = txt(p)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = None
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess":
                name = fn.attr
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                    and fn.value.id == "os" \
                    and fn.attr in ("system", "popen", "kill", "execv"):
                name = fn.attr
            if not name:
                continue
            kw = {k.arg: k for k in node.keywords if k.arg}
            args = [a for a in node.args]
            # B1 decoding without encoding
            decodes = ("text" in kw or "universal_newlines" in kw or "capture_output" in kw
                       or name in ("os.system", "os.popen"))
            if decodes and "encoding" not in kw and "errors" not in kw:
                out["B1 decode without encoding="].append(
                    f"{p.name}:{site(node)}  {name}  args={len(args)}")
            # B2 shell=True
            if "shell" in kw and isinstance(kw["shell"].value, ast.Constant) and kw["shell"].value.value is True:
                out["B2 shell=True"].append(f"{p.name}:{site(node)}")
            # first positional arg is a string literal / f-string -> command, not argv list
            if args and isinstance(args[0], (ast.Constant, ast.JoinedStr, ast.BinOp)):
                out["B5 command as STRING (not argv list)"].append(f"{p.name}:{site(node)}")
            # signals
            if name == "kill" and args and isinstance(args[0], ast.Constant):
                v = args[0].value
                out["B6 os.kill with signal"].append(f"{p.name}:{site(node)}  sig={v!r}")
    # B4 timeout + kill
    for p in sorted(SCRIPTS.glob("*.py")):
        for i, line in enumerate(txt(p).splitlines(), 1):
            if "timeout" in line and ("subprocess" in line or "run(" in line or "Popen" in line):
                out["B4 subprocess with timeout"].append(f"{p.name}:{i}  {line.strip()[:90]}")
    return out


# ------------------------------------------------------- C: filesystem axioms
def group_c() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    patterns = {
        "C1 lock primitives (fcntl/flock/LOCK_EX/msvcrt)": r"\b(fcntl|flock|LOCK_EX|LOCK_NB|msvcrt\.locking|lockf)\b",
        "C2 write-temp + rename/replace": r"\b(os\.replace|os\.rename|\.replace\(|NamedTemporaryFile|mkstemp)\b",
        "C3 mtime / utime age tests": r"\b(getmtime|utime|getctime|st_mtime)\b",
        "C4 os.walk / listdir recursion": r"\b(os\.walk|os\.listdir|rglob\(|iterdir\()",
        "C5 chmod / permissions": r"\b(os\.chmod|os\.umask|stat\.S_)\b",
        "C6 realpath / resolve / symlink": r"\b(realpath|resolve\(|islink|symlink|junction)\b",
        "C7 os.kill / terminate": r"\b(os\.kill|terminate\(|taskkill|SIGKILL|SIGTERM)\b",
        "C8 signal module": r"\b(import signal|signal\.signal|signal\.alarm)\b",
    }
    for p in sorted(SCRIPTS.glob("*.py")):
        for i, line in enumerate(txt(p).splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            for label, pat in patterns.items():
                if re.search(pat, line):
                    out[label].append(f"{p.name}:{i}  {s[:95]}")
    return out


# ------------------------------------------------------- D: text/locale/timing
def group_d() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for p in sorted(SCRIPTS.glob("*.py")):
        src = txt(p)
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if re.search(r"""open\([^)]*encoding=["']utf-8["'][^)]*\)""", line) and "errors=" not in line:
                out["D3a file read strict utf-8 (no errors=)"].append(f"{p.name}:{i}  {s[:85]}")
            if re.search(r"""open\([^)]*errors=["']""", line):
                out["D3b file read tolerant (errors=)"].append(f"{p.name}:{i}  {s[:85]}")
            if re.search(r"strftime\(|strptime\(|isoformat\(", line):
                out["D1 date formatting"] .append(f"{p.name}:{i}  {s[:85]}")
            if re.search(r"datetime\.now\(\)|datetime\.utcnow\(\)", line):
                out["D2 naive vs aware now()"].append(f"{p.name}:{i}  {s[:85]}")
    return out


# ----------------------------------------------------- E: is it inert on Win?
def group_e() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for p in sorted(SCRIPTS.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(SRC).as_posix()
        if rel.endswith((".md", ".sh", ".json", ".toml")) or rel.startswith("."):
            for i, line in enumerate(txt(p).splitlines(), 1):
                s = line.strip()
                if re.search(r"\b(bash|/bin/sh|#!/|chmod \+x|hooks?\b|settings\.json)", s, re.IGNORECASE):
                    out["E1 shell/hook wiring mentioned"].append(f"{rel}:{i}  {s[:95]}")
    for p in sorted(SCRIPTS.glob("*.py")):
        for i, line in enumerate(txt(p).splitlines(), 1):
            if re.search(r"HOOK|hook_path|CLAUDE|settings\.json", line):
                out["E1 hook path construction"].append(f"{p.name}:{i}  {line.strip()[:95]}")
            if re.search(r"ledger|LEDGER|\.act-ledger", line) and re.search(r"basename|relpath|key|\[", line):
                out["E2 ledger key construction"].append(f"{p.name}:{i}  {line.strip()[:95]}")
    return out


def main() -> int:
    groups = {
        "A — path shape": group_a(),
        "B — process boundary": group_b(),
        "C — filesystem semantics": group_c(),
        "D — text/locale/time": group_d(),
        "E — product inertness on Windows": group_e(),
    }
    total = 0
    for gname, sites in groups.items():
        print("=" * 100)
        print(f"### {gname}")
        for label, rows in sorted(sites.items()):
            print(f"\n  [{label}]  n={len(rows)}")
            for r in rows[:40]:
                print(f"      {r}")
            if len(rows) > 40:
                print(f"      ... +{len(rows) - 40} more")
            total += len(rows)
    print("=" * 100)
    print(f"TOTAL sites reported: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
