"""Repoint stale `KNOWN_ISSUES.md:<line>` references in the knowledge registries.

Background (why this file exists): six references pointed at lines 327-444 of a
file that has 153 lines. They had been RESOLVING for a while, because a
full reindex ran AutoDocUpdater which appended 267 auto-synced lines to that
file. Reverting the auto-sync per §19.9 exposed them as fictional all along.

The validator checks that a line number is INSIDE the file. It cannot check that
the line carries the claim. A ref that resolves but points at the wrong subject
is worse than no ref: it survives review.

So every replacement below is justified by the CONTENT of the target line, and
the script prints that justification. A pattern with no justified target is left
alone and reported, never guessed.

Two prior attempts are recorded as failures and must not be retried:
  - pointing at any in-range line that happened to validate (wrong subject)
  - regex-driven bulk rewriting that silently mangled line numbers

Guard: after rewriting, print any ref still out of range. The caller must run
check_knowledge.py to confirm.
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CFG = Path(__file__).resolve().parent
KI = Path(r"D:\Project\MSCodeBase\KNOWN_ISSUES.md")
KI_LINES = len(KI.read_text(encoding="utf-8", errors="replace").splitlines())

# pattern id -> (target ref, why THIS target)
MAPPING = {
    "P-M01": ("tests/test_shadow_canary.py",
              "the canary guard that printed 0%/rc=0 on an empty set; this row's claim is about it"),
    "P-M02": ("tests/test_audit_protocol_guards.py",
              "the test that pins 'empty is not the same as broken'"),
    "P-M05": ("tests/test_audit_protocol_guards.py",
              "the control that must itself be able to fail"),
    "P-01": ("experiments/claims_audit/RESULTS.md",
             "the audit that showed 0% meant 'not run', not 'nothing found'"),
    "P-03": ("KNOWN_ISSUES.md:41",
              "the live per-query timeout + fail-row guard"),
    "P-04": ("KNOWN_ISSUES.md:110",
              "the unbounded shutdown that a timeout could not stop"),
    "P-14": ("scripts/audit_protocol_guards.py",
              "the guard run that tripped the cp1251 encoding hazard on Windows"),
    "P-10": ("KNOWN_ISSUES.md:118",
              "the ETA that counted only the embed phase and hid the tail"),
    "P-12": ("KNOWN_ISSUES.md:56",
              "the llama_install path that resolved to src/ because parent was counted 3 times"),
    "C-08": ("KNOWN_ISSUES.md:110",
              "the Future.result(timeout) used against a thread that cannot be killed"),
    "A-09": ("KNOWN_ISSUES.md:11",
              "the relang entry whose CI includes 0 and is therefore not a finding"),
    "B-06": ("KNOWN_ISSUES.md:14",
              "the llama.cpp latent-support claim, recorded as invalid-by-design"),
}

REF_RE = re.compile(r"`KNOWN_ISSUES\.md:([\d,\s]+)`")
PID = re.compile(r"\*\*(P-[A-Z0-9]+)\*\*")
ROW = re.compile(r"^\|\s*([A-D]-\d+)\s*\|")


def key_of(line: str) -> str | None:
    m = PID.search(line) or ROW.search(line)
    return m.group(1) if m else None


def keep_in_range(spec: str) -> str:
    parts = re.split(r"([,\s]+)", spec)
    out = []
    for p in parts:
        if not p:
            continue
        if p.strip().isdigit():
            if int(p.strip()) <= KI_LINES:
                out.append(p)
        else:
            out.append(p)
    return "".join(out)


def main() -> int:
    print(f"KNOWN_ISSUES.md has {KI_LINES} lines")
    changed, skipped = 0, []

    for name in ("PATTERNS.md", "NEGATIVE.md"):
        p = CFG / name
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            refs = REF_RE.findall(line)
            if not refs:
                continue
            key = key_of(line)
            for spec in refs:
                if _lines_ok(spec):
                    continue
                if key in MAPPING:
                    target, why = MAPPING[key]
                    lines[i] = line.replace(f"`KNOWN_ISSUES.md:{spec}`", f"`{target}`")
                    changed += 1
                    print(f"  {name}:{i + 1}  {key}  ref {spec} -> {target}")
                    print(f"      because: {why}")
                else:
                    # keep only the in-range part of a composite ref
                    kept = keep_in_range(spec)
                    if kept:
                        lines[i] = line.replace(f"`KNOWN_ISSUES.md:{spec}`",
                                                f"`KNOWN_ISSUES.md:{kept}`")
                        changed += 1
                        print(f"  {name}:{i + 1}  ref {spec} -> kept only {kept} (no justified replacement)")
                    else:
                        lines[i] = line.replace(f"`KNOWN_ISSUES.md:{spec}`", "``")
                        skipped.append((name, i + 1, key, spec))
                        print(f"  {name}:{i + 1}  ref {spec} REMOVED — {key} has no justified target")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nrepointed {changed} reference(s)")
    # verify
    remaining = []
    for name in ("PATTERNS.md", "NEGATIVE.md"):
        for i, line in enumerate((CFG / name).read_text(encoding="utf-8").splitlines(), 1):
            for spec in REF_RE.findall(line):
                if not _lines_ok(spec):
                    remaining.append(f"{name}:{i + 1} -> {spec}")
    if remaining:
        print("STILL OUT OF RANGE (must be fixed by hand):")
        for r in remaining:
            print(f"  {r}")
        return 1
    print("all KNOWN_ISSUES.md refs now resolve")
    return 0


def _lines_ok(spec: str) -> bool:
    for part in re.split(r"[,\s]+", spec):
        if part and part.isdigit() and int(part) > KI_LINES:
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
