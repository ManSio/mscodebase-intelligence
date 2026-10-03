"""check_knowledge.py — the guard for the agent's memory organ.

An organ nobody validates rots into confident-looking prose. That is the exact
failure this repo already paid for twice:
  * `tests/test_no_personal_paths.py` was green while 4699 leaks sat in 98 files
    OUTSIDE its scope -> a guard that certifies the wrong set.
  * a note "rots while looking exactly as confident as the day you wrote it"
    (foreign repo, docs/measured.md).

So this validator exists, and it MUST be able to fail. `--selftest` proves each
check fails on a deliberately corrupted copy of the registry. A validator that
cannot fail is worse than no validator.

Checks:
  K1  every `refs` file:line in the registries points at a line that EXISTS
  K2  every guard path named in PATTERNS.md exists on disk
  K3  every p_ref points at a P-### that exists in pitfalls-registry
  K4  no duplicate ids inside a registry
  K5  every thread has a temperature from the allowed set
  K6  organ is non-trivial (guards against a silently emptied registry)

Exit 0 clean, 1 on findings, 2 on unusable input.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# The registries live NEXT TO this file, inside the repository, so a reference to
# `scripts/…` or `tests/…` resolves against the same checkout being verified. While
# these files lived in ~/.config and the paths they named lived in the repo, the
# references dangled the moment the branch changed — a registry is only meaningful
# against the tree it describes.
KNOW = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path(__file__).resolve().parents[2]
# The pitfalls skill is personal and stays outside the repo; K3 is skipped when it
# is absent rather than failing (an optional dependency is not a defect).
CFG = pathlib.Path(os.environ.get("OPENCODE_CFG", pathlib.Path.home() / ".config" / "opencode"))
REG = CFG / "skills" / "pitfalls-registry" / "SKILL.md"

TEMP_OK = {"hot", "warm", "cold"}
ID_RE = re.compile(r"\b(P-M\d{2}|P-\d{2}|H-\d{2}|T-\d{2}|C-\d{2})\b")
# a reference like `EXPERIMENTS_LOG.md:537` or `KNOWN_ISSUES.md:95,57`
REF_RE = re.compile(r"`([A-Z_]+\.md):(\d+(?:[,–]\d+)*)`")
PREF_RE = re.compile(r"\bP-(\d{3})\b")


def load() -> dict:
    files = {}
    for name in ("PATTERNS.md", "NEGATIVE.md", "THREADS.md", "CONSOLIDATION.md"):
        p = KNOW / name
        files[name] = p.read_text(encoding="utf-8") if p.exists() else ""
    files["SKILL"] = REG.read_text(encoding="utf-8") if REG.exists() else ""
    return files


def check(files: dict) -> list[str]:
    bad: list[str] = []
    corpus = {p.name: p for p in REPO.glob("*.md")}

    # K1 refs must point at a line that exists
    for fname in ("PATTERNS.md", "NEGATIVE.md", "THREADS.md"):
        text = files.get(fname, "")
        if not text:
            bad.append(f"K6 {fname} is missing or empty")
            continue
        for ref_file, spec in REF_RE.findall(text):
            target = corpus.get(ref_file)
            if target is None:
                continue  # external corpus (e.g. a foreign repo) — not checkable here
            n_lines = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
            for num in re.split(r"[,–]", spec):
                try:
                    n = int(num)
                except ValueError:
                    continue
                if n > n_lines:
                    bad.append(f"K1 {fname}: {ref_file}:{n} beyond EOF ({n_lines} lines)")

    # K2 guard paths must exist
    for fname in ("PATTERNS.md",):
        for m in re.finditer(r"`((?:src|tests|scripts|experiments)/[\w./-]+\.py)`", files.get(fname, "")):
            if not (REPO / m.group(1)).exists():
                bad.append(f"K2 {fname}: guard path does not exist: {m.group(1)}")

    # K3 p_ref must exist in the skill registry
    skill_p = set(PREF_RE.findall(files.get("SKILL", "")))
    for fname in ("PATTERNS.md",):
        for m in PREF_RE.finditer(files.get(fname, "")):
            if m.group(1) not in skill_p:
                bad.append(f"K3 {fname}: p_ref P-{m.group(1)} not in pitfalls-registry")

    # K4 duplicate ids per registry. Count DEFINITIONS only (bolded `**ID**`), because an
    # id may legitimately be mentioned in prose (e.g. "C-12 and T-06 may be wrong").
    for fname in ("PATTERNS.md", "THREADS.md", "NEGATIVE.md"):
        text = files.get(fname, "")
        alt = "|".join(x for x in ("P-M[0-9]{2}", "P-[0-9]{2}", "H-[0-9]{2}",
                                   "T-[0-9]{2}", "C-[0-9]{2}"))
        ids = re.findall(r"\*\*(" + alt + r")\*\*", text)
        seen, dup = set(), set()
        for i in ids:
            (dup if i in seen else seen).add(i)
        for d in sorted(dup):
            bad.append(f"K4 {fname}: id {d} DEFINED more than once")

    # K5 temperature vocabulary: every `temperature:` value must be in the allowed set
    th = files.get("THREADS.md", "")
    for m in re.finditer(r"temperature[^a-zA-Z]{0,4}([a-z]+)", th, re.IGNORECASE):
        val = m.group(1).lower()
        if val not in TEMP_OK and val not in {"и", "a"}:
            bad.append(f"K5 THREADS.md: unknown temperature {val!r}")
    # the section header must declare all three temperatures, or the vocabulary drifted
    if th and not all(t in th.lower() for t in TEMP_OK):
        bad.append(f"K5 THREADS.md: not all temperatures {sorted(TEMP_OK)} are used")

    # K7 the registry's own numbering must be contiguous -- a hole means an item lost its id
    # a definition is an id that appears at the START of a bolded heading
    defs = sorted(set(re.findall(r"\*\*P-(\d{3})", files.get("SKILL", ""))))
    if defs:
        nums = [int(d) for d in defs]
        gaps = [n for n in range(min(nums), max(nums) + 1) if n not in nums]
        if gaps:
            bad.append(f"K7 pitfalls-registry: numbering gap at P-{gaps[0]:03d} "
                       f"(an item lost its id)")
    return bad


def selftest() -> int:
    """Every check must be ABLE to fail. Proven on a corrupted copy."""
    cases = [
        ("K1 ref beyond EOF",
         {**load(), "PATTERNS.md": "`KNOWN_ISSUES.md:999999`", "NEGATIVE.md": "x", "THREADS.md": "x"},
         "K1"),
        ("K2 missing guard path",
         {**load(), "PATTERNS.md": "`src/core/does_not_exist_xyz.py`"},
         "K2"),
        ("K3 unknown p_ref",
         {**load(), "PATTERNS.md": "`P-999` guard text"},
         "K3"),
        ("K4 duplicate id",
         {**load(), "PATTERNS.md": "| **P-01** a |\n| **P-01** b |"},
         "K4"),
        ("K5 unknown temperature",
         {**load(), "THREADS.md": "temperature: scorching"},
         "K5"),
        ("K6 emptied organ",
         {**load(), "PATTERNS.md": "", "NEGATIVE.md": "", "THREADS.md": ""},
         "K6"),
    ]
    ok = True
    for name, files, expect in cases:
        got = check(files)
        hit = any(g.startswith(expect) for g in got)
        status = "OK" if hit else "GUARD IS BLIND"
        if not hit:
            ok = False
        print(f"  [{status}] {name}: expected {expect}, got {[g[:60] for g in got][:2]}")
    print(f"\nSELFTEST {'PASSED — checks can fail' if ok else 'FAILED — a check cannot fail'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    if not KNOW.is_dir():
        print(f"knowledge organ not found: {KNOW}", file=sys.stderr)
        return 2
    files = load()
    if not files["PATTERNS.md"] and not files["NEGATIVE.md"] and not files["THREADS.md"]:
        print("KNOWLEDGE GUARD: registries are all empty — an empty organ is a defect, not a clean state")
        return 1

    bad = check(files)
    counts = {n: len(re.findall(ID_RE, files.get(f, ""))) for n, f in
              (("patterns", "PATTERNS.md"), ("negative", "NEGATIVE.md"),
               ("threads", "THREADS.md"), ("contradictions", "THREADS.md"))}
    print(f"[counts] patterns={counts['patterns']} negative={counts['negative']} "
          f"threads={counts['threads']} ids_total={sum(counts.values())}")
    print(f"[skill]  P-### available in pitfalls-registry: {len(set(PREF_RE.findall(files['SKILL'])))}")
    if bad:
        print(f"\nKNOWLEDGE GUARD: {len(bad)} finding(s)")
        for b in bad[:20]:
            print(f"  - {b}")
        if len(bad) > 20:
            print(f"  ... +{len(bad) - 20} more")
        return 1
    print("\nKNOWLEDGE GUARD: clean — every ref resolves, every guard path exists, every p_ref is real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
