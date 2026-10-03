"""A test must not mutate a file that outlives it.

Incident (2026-10-03, PR #65): tests/test_negative_controls_runner.py proved the
digest pin by editing the REAL fixture
scripts/negative_controls/fixtures/dead_guard.py and restoring it in `finally`.
Under `pytest -n auto` another worker read that fixture's digest inside the
window between the write and the restore, computed a different digest, and
classified a healthy guard as UNPROVEN. Green locally, red on every CI runner, and
it presented as a defect in the digest guard rather than as a race between tests.

The same class cost hours earlier in this project: a held-out that snapshotted its
fixture from the already-dirty on-disk file, and a "sabotage" that restored the
sabotaged bytes.

Why this is a test and not a script: a script nobody runs is not a gate.

Rule: inside tests/, a write must target a path derived from tmp_path,
tmp_path_factory, or a scratch directory the test creates. A write through a name
bound to ROOT/<literal> is a finding — including when the binding is several lines
above the write. An earlier version of this guard only looked for ROOT on the
same line as the write call, which missed the exact pattern it was written for:
the fixture was bound to a local first and written three lines later. A guard
that cannot see its own bug is worse than no guard — it reads as coverage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

WRITE_CALLS = re.compile(
    r"\.(?P<method>write_text|write_bytes|mkdir|unlink|rename)\s*\(|"
    r"\b(?:os\.remove|os\.unlink|shutil\.copyfile|shutil\.copy2|shutil\.rmtree)\s*\("
)
# `name = ROOT / "..."`, also `name = Path(ROOT) / "..."`, also `name = ROOT / "a" / "b"`.
# The optional Path(...) wrapper is INSIDE the group; an earlier version had it
# outside and the constant got consumed by the wrapper alternative, so no name
# ever bound and the selftest flagged 0 of 2 known-bad writes.
ROOT_BINDING = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?:Path\(\s*)?(?:ROOT|REPO|PROJECT_ROOT|REPO_ROOT)\b"
)
# a write whose receiver is literally the constant
DIRECT_ROOT_WRITE = re.compile(
    r"\.\s*write_(?:text|bytes)\s*\(\s*(?:ROOT|REPO|PROJECT_ROOT|REPO_ROOT)\b|"
    r"\b(?:os\.remove|os\.unlink|shutil\.rmtree)\s*\(\s*(?:ROOT|REPO|PROJECT_ROOT|REPO_ROOT)\b"
)
SAFE_HINTS = ("tmp_path", "tmp_path_factory", "scratch", "tmpdir", "temp_dir",
              "_repo_tmp_dir", "isolated", "sandbox", "shutil.rmtree(scratch")

# Exemptions carry a REASON. An unnamed allowlist is how a guard decays into
# decoration: each new entry looks harmless and nobody re-reads the list.
# Each reason below was verified by reading the test, not assumed.
EXEMPTIONS = {
    "test_planted_break_gate.py": (
        "RESULTS_FILE is a generated artifact read by nobody. The write is now "
        "atomic (temp file + os.replace on the same volume), so no reader can "
        "observe an intermediate state, and the file is gitignored. mkdir with "
        "exist_ok=True is idempotent and cannot corrupt."
    ),
}


def scan() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for f in sorted(TESTS.rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if f.name == Path(__file__).name:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        root_names = {m.group("name") for m in
                      (ROOT_BINDING.match(ln) for ln in lines) if m}

        for n, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if not WRITE_CALLS.search(code):
                continue
            if any(h in code for h in SAFE_HINTS):
                continue
            if f.name in EXEMPTIONS:
                continue
            if DIRECT_ROOT_WRITE.search(code):
                findings.append((rel, n, code.strip()[:92]))
                continue
            w = WRITE_CALLS.search(code)
            assert w is not None
            receiver = code[: w.start()].strip().rstrip(".").split(".")[-1].strip()
            if receiver in root_names:
                findings.append((rel, n,
                                 f"{code.strip()[:62]}  <- '{receiver}' is bound to ROOT"))
    return findings


def selftest() -> int:
    """§19.3: the guard must be able to FAIL, and must fail on the REAL shape."""
    # The exact pre-fix incident, reproduced as source.
    incident = [
        'fixture = ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard.py"',
        "orig = fixture.read_bytes()",
        "try:",
        '    fixture.write_bytes(orig + b"\\n# digest-mutant\\n")',
        "    p = _run()",
        "finally:",
        "    fixture.write_bytes(orig)",
    ]
    root_names = {m.group("name") for m in (ROOT_BINDING.match(ln) for ln in incident) if m}
    flagged = 0
    for ln in incident:
        code = ln.split("#", 1)[0]
        if not WRITE_CALLS.search(code):
            continue
        if any(h in code for h in SAFE_HINTS):
            continue
        w = WRITE_CALLS.search(code)
        receiver = code[: w.start()].strip().rstrip(".").split(".")[-1].strip()
        if DIRECT_ROOT_WRITE.search(code) or receiver in root_names:
            flagged += 1
    if flagged != 2:
        print(f"SELFTEST FAILED: flagged {flagged}/2 writes in the known incident shape")
        return 1

    # and a safe pattern must NOT be flagged
    safe = 'shutil.copyfile(ROOT / "scripts" / "x.py", scratch / "x.py")'
    sw = WRITE_CALLS.search(safe)
    safe_receiver = safe[: sw.start()].strip().rstrip(".").split(".")[-1].strip()
    false_positive = (not any(h in safe for h in SAFE_HINTS)
                      and (DIRECT_ROOT_WRITE.search(safe) or safe_receiver in root_names))
    if false_positive:
        print("SELFTEST FAILED: a safe scratch copy was flagged")
        return 1
    print("SELFTEST PASSED — catches the incident shape, ignores scratch copies")
    return 0


def test_no_test_mutates_a_root_relative_path():
    """The guard itself, as a test.

    A module named test_*.py that defines no test function is silently skipped by
    pytest — which is how a guard ends up looking like coverage while never
    running. This function exists so the file is collected, and so a finding is a
    RED BUILD rather than a script somebody has to remember to execute.
    """
    findings = scan()
    assert not findings, (
        "a test writes through a ROOT-relative path; another worker may observe "
        "the intermediate state and compute a different result from the same "
        "input:\n" + "\n".join(f"  {rel}:{n}: {c}" for rel, n, c in findings)
    )


def test_guard_scanner_can_fail():
    """§19.3: the scanner must be able to FAIL on the shape it was written for."""
    incident = [
        'fixture = ROOT / "scripts" / "negative_controls" / "fixtures" / "dead_guard.py"',
        "orig = fixture.read_bytes()",
        'fixture.write_bytes(orig + b"\\n# digest-mutant\\n")',
        "fixture.write_bytes(orig)",
    ]
    root_names = {m.group("name") for m in (ROOT_BINDING.match(ln) for ln in incident) if m}
    assert "fixture" in root_names, "scanner no longer sees a ROOT-bound name"
    flagged = 0
    for ln in incident:
        code = ln.split("#", 1)[0]
        w = WRITE_CALLS.search(code)
        if not w or any(h in code for h in SAFE_HINTS):
            continue
        receiver = code[: w.start()].strip().rstrip(".").split(".")[-1].strip()
        if DIRECT_ROOT_WRITE.search(code) or receiver in root_names:
            flagged += 1
    assert flagged == 2, f"scanner flagged {flagged}/2 writes in the known incident"

    # a scratch copy must NOT be flagged, or the guard is noise
    safe = 'shutil.copyfile(ROOT / "scripts" / "x.py", scratch / "x.py")'
    sw = WRITE_CALLS.search(safe)
    assert sw is not None
    safe_receiver = safe[: sw.start()].strip().rstrip(".").split(".")[-1].strip()
    assert not (DIRECT_ROOT_WRITE.search(safe) or safe_receiver in root_names)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    findings = scan()
    print("=" * 88)
    print("GUARD: no test may mutate a file that outlives it")
    print("=" * 88)
    if not findings:
        print("CLEAN: every write in tests/ targets a scratch path")
        return 0
    print(f"{len(findings)} finding(s) — a test writes through a ROOT-relative path:")
    for rel, n, code in findings:
        print(f"  {rel}:{n}: {code}")
    print()
    print("Copy the file into a scratch dir created by the test instead.")
    print("See the fix in tests/test_negative_controls_runner.py for the pattern.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
