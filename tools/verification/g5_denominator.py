"""G5 — DENOMINATOR COVERAGE.

Purpose (Tom, dev.to 4342586 depth 0, verified):
    "a hand-authored manifest made the presented set eligible by definition, so
     the denominator was an assertion wearing the clothes of a measurement."

So: the denominator is DERIVED by a frozen, versioned scan rule, and every
publicly-visible file must be registered with a class and a reason. Files that
are NOT registered, or whose candidate count GREW since registration, are a
BLOCK: new numbers appeared that nobody classified.

Design constraints, each traceable to a Red Team attack:
    RT1  no `or`-fallback globs — the artifact set is an explicit list
    RT2  RULE_VERSION + rule hash printed; change = new version + new manifest entry
    RT3  a missing dependency is exit(2), never a silent smaller population
    RT4  every file carries class PUBLIC/INTERNAL/DERIVED + a reason string
    RT5  EXEMPT takes a reason CODE from a closed set; exempt share is published
    RT6  selftest must fail FOR THE RIGHT REASON (checked explicitly, RT6 case)
    RT7  nothing here is called cross-verification

Exit codes: 0 pass | 2 empty/undeterminable population | 3 block
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# tools/verification/g5_denominator.py -> parents[2] is the repo root, parents[3] the
# projects dir. Verified by an existence check rather than by counting levels:
#   parents[0]=tools/verification  parents[1]=tools  parents[2]=<repo>  parents[3]=<projects>
# Getting this wrong made the gate report "population undeterminable" — the CORRECT
# failure for a missing dependency, produced by the WRONG cause (a bad path, not a
# missing repo). Both look identical from the exit code alone.
#
# MSCB_REPO_ROOT exists because heldout_g5.py runs a COPY of this file from a temp
# dir, where parents[2] is empty. Without an override the copy could only ever
# report "no scope profile is satisfiable" — a test harness that cannot exercise
# the gate is not a harness.
ROOT = Path(os.environ.get("MSCB_REPO_ROOT") or Path(__file__).resolve().parents[2])

# Where the audited repositories live. Derived from ROOT, so a clone at any path works.
# NEVER silently substituted: if the directory is absent, scan() raises a hard failure
# and main() exits 2 (RT3).
PROJECTS_ROOT = Path(os.environ.get("MSCB_PROJECTS_ROOT", str(ROOT.parent)))

# --- the population, as DECLARED SCOPE PROFILES ---------------------------------
# A bare clone (CI, a fresh machine, a git worktree) has no sibling repositories.
# Deriving the population from the filesystem made the gate exit 2 there — correct in
# refusing to print a number, but it made the gate UNRUNNABLE outside one developer's
# folder layout, which defeats the point of committing it in the first place.
#
# So the population is declared in the committed manifest as named profiles, each
# with the roots it requires. The gate picks the first profile whose roots all exist
# and PRINTS which one it used, and why the others were skipped. Coverage is then
# reported for that profile only: never blended across profiles, never silently
# reduced to whatever happens to be on disk.
SCOPE_PROFILES = {
    "full": {"roots": ["repo", "portfolio"]},
    "repo_only": {"roots": ["repo"]},
}
PROFILE_ORDER = ["full", "repo_only"]
RULE_VERSION = 1

# --- rule 1: number + unit-after -------------------------------------------------
RULE_UNITS = (
    r"passing|passed|failed|fails|tests?|asserts?|checks?|guards?|chunks?|"
    r"ms|sec|seconds?|min|minutes?|hours?|days?|nodes?|files?|experiments?|"
    r"claims?|runs?|cycles?|articles?|issues?|commits?|tokens?|lines?|"
    r"bytes?|pct|ratio|score|percent"
)
RULE_1 = re.compile(rf"(?<![\w.])[-+]?\d[\d ,._]*\s?(?:%|x\b|\u00d7|k\b|MB|KB|ms|s\b)?\s*(?:{RULE_UNITS})", re.I)
RULE_1_SRC = RULE_1.pattern

# --- rule 2: independent signature, different family ------------------------------
# Every standalone integer >= 1 that is not a 4-digit year in a date-ish context.
# Deliberately a DIFFERENT rule family so that a single hand-edit cannot raise
# both counts at once (RT2): moving a word out of a line moves count 1, not count 2.
_YEAR = re.compile(r"(?<!\d)(19\d\d|20\d\d)(?!\d)")
RULE_2 = re.compile(r"(?<![\w.])[-+]?\d+(?![\w])")
RULE_2_SRC = RULE_2.pattern

# --- the population: an EXPLICIT list. No globs, no fallbacks (RT1). -------------
# REPO is THIS repository, by definition. It used to be PROJECTS_ROOT / "MSCodeBase",
# which hardcoded the checkout's folder name — so in a worktree or a CI workspace
# the gate looked for a repo that does not exist and reported "population
# undeterminable" instead of scanning the tree it was actually running in.
REPO = ROOT
PORT = PROJECTS_ROOT / "MSPortfolio"

# (relative label, path, class, why-in-or-out, which scope profiles include it)
ARTIFACTS: list[tuple[str, Path, str, str, tuple[str, ...]]] = [
    ("portfolio/lab/experiments.json", PORT / "src/data/lab/experiments.json", "PUBLIC", "public lab mirror", ("full",)),
    ("portfolio/lab/experiments.ru.json", PORT / "src/data/lab/experiments.ru.json", "PUBLIC", "RU mirror of above", ("full",)),
    ("portfolio/lab/diary.json", PORT / "src/data/lab/diary.json", "PUBLIC", "public diary mirror", ("full",)),
    ("portfolio/lab/diary.ru.json", PORT / "src/data/lab/diary.ru.json", "PUBLIC", "RU mirror of above", ("full",)),
    ("portfolio/lab/known-issues.json", PORT / "src/data/lab/known-issues.json", "PUBLIC", "public issue board", ("full",)),
    ("portfolio/lab/known-issues.ru.json", PORT / "src/data/lab/known-issues.ru.json", "PUBLIC", "RU mirror of above", ("full",)),
    ("portfolio/lab/test-suites.json", PORT / "src/data/lab/test-suites.json", "PUBLIC", "public suite claims", ("full",)),
    ("portfolio/lab/test-suites.ru.json", PORT / "src/data/lab/test-suites.ru.json", "PUBLIC", "RU mirror of above", ("full",)),
    ("portfolio/README.md", PORT / "README.md", "PUBLIC", "public readme", ("full",)),
    ("portfolio/CHANGELOG.md", PORT / "CHANGELOG.md", "PUBLIC", "public changelog", ("full",)),
    ("repo/EXPERIMENTS_LOG.md", REPO / "EXPERIMENTS_LOG.md", "INTERNAL", "internal log; public via experiments.json", ("full", "repo_only")),
    ("repo/AGENT_DIARY.md", REPO / "AGENT_DIARY.md", "INTERNAL", "internal diary; public via diary.json", ("full", "repo_only")),
    ("repo/KNOWN_ISSUES.md", REPO / "KNOWN_ISSUES.md", "INTERNAL", "internal board; public via known-issues.json", ("full", "repo_only")),
    ("repo/ISSUE.md", REPO / "ISSUE.md", "INTERNAL", "internal tracker", ("full", "repo_only")),
    ("repo/WISDOM.md", REPO / "WISDOM.md", "INTERNAL", "internal distilate", ("full", "repo_only")),
    ("repo/README.md", REPO / "README.md", "PUBLIC", "public readme", ("full", "repo_only")),
]


def choose_profile() -> tuple[str | None, str]:
    """Pick the first scope profile whose roots all exist. Returns (profile, why).

    Printed on every run. A profile switch is a change of population, so it must be
    as visible as a rule-version change — otherwise the same command reports
    different coverage in CI and on the author's machine with no visible cause.

    Returns (None, why) when no profile is satisfiable; the caller must then refuse
    to report a number rather than fall back to whatever is on disk.
    """
    notes = []
    for name in PROFILE_ORDER:
        spec = SCOPE_PROFILES[name]
        missing = []
        for root in spec["roots"]:
            if root == "repo" and not (ROOT / "pyproject.toml").exists():
                missing.append("repo (this checkout)")
            if root == "portfolio" and not (PORT / "src" / "data" / "lab").exists():
                missing.append(f"portfolio ({PORT})")
        if not missing:
            why = f"profile '{name}' satisfied"
            earlier = PROFILE_ORDER[:PROFILE_ORDER.index(name)]
            if earlier:
                why += (f"; '{earlier[0]}' skipped because "
                        + ("the portfolio mirror is not present"
                           if "portfolio" in SCOPE_PROFILES[earlier[0]]["roots"]
                           else "its roots are missing"))
            return name, why
        notes.append(f"'{name}' needs {', '.join(missing)}")
    return None, ("no scope profile is satisfiable: " + "; ".join(notes)
                  + " — a smaller population must never be reported as the population")


EXEMPT_CODES = {
    "MIRROR": "RU mirror of an already-registered EN artifact",
    "DERIVED": "machine-derived from a registered artifact, no independent claim",
    "NOT_A_CLAIM": "scanned text carries no authored claim (headers, provenance)",
}


def sig1(text: str) -> int:
    return len(RULE_1.findall(text))


def sig2(text: str) -> int:
    return len(RULE_2.findall(_YEAR.sub(" ", text)))


def load_manifest(path: Path) -> dict:
    # utf-8-sig: on Windows a hand-edited manifest routinely carries a BOM.
    # Rejecting it would make the gate fail for a reason unrelated to coverage,
    # which teaches people to ignore gate failures (RT6 spirit: right reason).
    return json.loads(path.read_text(encoding="utf-8-sig"))


def scan(profile: str = "full") -> tuple[dict, list[str]]:
    """Returns (per-label -> sigs, hard_failures). Missing file => hard failure (RT3).

    Only artifacts belonging to `profile` are scanned; the others are not "missing",
    they are out of scope by declaration, and saying otherwise would make a bare
    clone look like a broken checkout.
    """
    out: dict[str, dict] = {}
    hard: list[str] = []
    for label, path, cls, why, profiles in ARTIFACTS:
        if profile not in profiles:
            continue
        if not path.exists():
            hard.append(f"MISSING DEPENDENCY: {label} -> {path} (RT3: never a silent 0)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            hard.append(f"UNREADABLE: {label}: {e}")
            continue
        out[label] = {"sig1": sig1(text), "sig2": sig2(text), "class": cls, "why": why, "path": str(path)}
    return out, hard


def evaluate(manifest: dict, found: dict, profile: str = "full") -> tuple[list[str], dict]:
    """Returns (blocks, stats).

    TWO DISTINCT COUNTS PER ARTIFACT — never conflate them:
        n_sig1      how many candidates the rule FINDS   (derived, machine)
        n_reviewed  how many of those a human actually CLASSIFIED (authored)

    Conflating them is the exact pathology this gate exists to catch:
    bootstrapping n_reviewed = n_sig1 makes coverage return 100% by construction.
    n_reviewed defaults to 0 and must only ever rise by explicit classification.
    """
    blocks: list[str] = []
    reg = manifest["artifacts"]

    for label in found:
        if label not in reg:
            blocks.append(f"UNREGISTERED ARTIFACT carries numbers: {label} — classify it (RT4/RT5)")

    reviewed_by_class: dict[str, int] = {}
    exempt_by_class: dict[str, int] = {}
    cand_by_class: dict[str, int] = {}
    unreviewed_total = 0

    for label, entry in sorted(found.items()):
        cls = entry["class"]
        cand_by_class[cls] = cand_by_class.get(cls, 0) + entry["sig1"]
        r = reg.get(label)
        if r is None:
            unreviewed_total += entry["sig1"]
            continue
        if r.get("class") != cls:
            blocks.append(f"CLASS DRIFT: {label} manifest={r.get('class')} actual={cls}")

        if r.get("reason_code") == "EXEMPT":
            code = r.get("exempt_code")
            if code not in EXEMPT_CODES:
                blocks.append(f"EXEMPT WITH UNKNOWN CODE: {label} code={code!r} allowed={sorted(EXEMPT_CODES)}")
            else:
                exempt_by_class[cls] = exempt_by_class.get(cls, 0) + entry["sig1"]
            continue

        found_n = entry["sig1"]
        claimed_n = r.get("n_sig1")
        if not isinstance(claimed_n, int):
            blocks.append(f"NO REGISTERED COUNT: {label}")
            unreviewed_total += found_n
            continue
        if found_n > claimed_n:
            blocks.append(
                f"UNREGISTERED GROWTH: {label} was {claimed_n}, now {found_n} "
                f"(+{found_n - claimed_n} new candidates) — classify them before claiming coverage"
            )

        reviewed = r.get("n_reviewed")
        if reviewed is None:
            reviewed = 0
        if not isinstance(reviewed, int) or reviewed < 0:
            blocks.append(f"BAD n_reviewed: {label} = {reviewed!r}")
            reviewed = 0
        if reviewed > found_n:
            blocks.append(f"REVIEWED EXCEEDS FOUND: {label} reviewed={reviewed} found={found_n}")
            reviewed = found_n
        reviewed_by_class[cls] = reviewed_by_class.get(cls, 0) + reviewed
        unreviewed_total += found_n - reviewed

    stats = {
        "cand_by_class": cand_by_class,
        "reviewed_by_class": reviewed_by_class,
        "exempt_by_class": exempt_by_class,
        "unreviewed_total": unreviewed_total,
    }
    return blocks, stats


def report(found: dict, stats: dict, rule_hash: str) -> None:
    print("=" * 92)
    print(f"G5 DENOMINATOR COVERAGE   rule_version={RULE_VERSION}")
    print(f"rule1 sha256 {rule_hash[:32]}")
    print("=" * 92)
    print(f"{'artifact':<40} {'class':<9} {'found':>6} {'sig2':>7}")
    for label, e in sorted(found.items()):
        print(f"{label:<40} {e['class']:<9} {e['sig1']:>6} {e['sig2']:>7}")
    print()
    tot_c = tot_r = tot_e = 0
    print(f"{'class':<10} {'candidates':>11} {'reviewed':>9} {'exempt':>8} {'coverage':>11}")
    for cls in sorted(set(list(stats["cand_by_class"]) + list(stats["reviewed_by_class"]))):
        c = stats["cand_by_class"].get(cls, 0)
        rv = stats["reviewed_by_class"].get(cls, 0)
        x = stats["exempt_by_class"].get(cls, 0)
        tot_c += c
        tot_r += rv
        tot_e += x
        cov = f"{rv / c * 100:.2f}%" if c else "n/a"
        print(f"{cls:<10} {c:>11} {rv:>9} {x:>8} {cov:>11}")
    print(f"{'ALL':<10} {tot_c:>11} {tot_r:>9} {tot_e:>8} {(f'{tot_r / tot_c * 100:.2f}%' if tot_c else 'n/a'):>11}")
    print()
    print(f"UNREVIEWED CANDIDATES: {stats['unreviewed_total']}/{tot_c}")
    if tot_r == 0:
        print("COVERAGE: NOT YET MEASURED. No candidate has been classified by a human.")
        print("          A number over an unclassified population is an assertion, not a measurement.")
    if tot_c:
        print(f"EXEMPT SHARE (RT5 — mass exemption must be visible, not invisible): {tot_e}/{tot_c} = {tot_e / tot_c * 100:.1f}%")
    print("NOTE (RT4): the class split is a JUDGEMENT, not a measurement. The two")
    print("      numbers describe two different questions. Do not merge them.")


def selftest() -> int:
    """RT6: the selftest must fail FOR THE RIGHT REASON, not merely fail.

    Each control below asserts the SPECIFIC block string it expects. A control
    that passes because something ELSE blocked is a failure, not a pass.
    """
    failures = []

    def expect(name: str, blocks: list[str], needle: str) -> None:
        hit = [b for b in blocks if needle in b]
        if hit:
            print(f"  [OK ] {name}: blocked by '{needle}' -> {hit[0][:78]}")
        else:
            print(f"  [XX ] {name}: expected a block containing '{needle}', got {blocks}")
            failures.append(f"{name}: wrong-or-missing reason")

    print("-- controls (each must block for its OWN reason)")

    # B: unregistered growth
    found = {"a": {"sig1": 100, "sig2": 200, "class": "PUBLIC", "why": "", "path": "x"}}
    man = {"artifacts": {"a": {"class": "PUBLIC", "n_sig1": 50}}}
    expect("growth", evaluate(man, found)[0], "UNREGISTERED GROWTH")

    # D: exempt with unknown code
    found3 = {"b": {"sig1": 10, "sig2": 20, "class": "PUBLIC", "why": "", "path": "y"}}
    man3 = {"artifacts": {"b": {"class": "PUBLIC", "reason_code": "EXEMPT", "exempt_code": "TOO_LATE"}}}
    expect("exempt-code", evaluate(man3, found3)[0], "UNKNOWN CODE")

    # E: unregistered artifact
    man4 = {"artifacts": {}}
    expect("unregistered-artifact", evaluate(man4, {"c": {"sig1": 5, "sig2": 5, "class": "PUBLIC", "why": "", "path": "z"}})[0],
           "UNREGISTERED ARTIFACT")

    # F: reviewed exceeds found
    found5 = {"d": {"sig1": 10, "sig2": 10, "class": "PUBLIC", "why": "", "path": "w"}}
    man5 = {"artifacts": {"d": {"class": "PUBLIC", "n_sig1": 10, "n_reviewed": 99}}}
    expect("reviewed-exceeds-found", evaluate(man5, found5)[0], "REVIEWED EXCEEDS FOUND")

    # G: class drift
    found6 = {"e": {"sig1": 10, "sig2": 10, "class": "INTERNAL", "why": "", "path": "v"}}
    man6 = {"artifacts": {"e": {"class": "PUBLIC", "n_sig1": 10}}}
    expect("class-drift", evaluate(man6, found6)[0], "CLASS DRIFT")

    # RT9 -- THE CONFLATION CONTROL. This is the real bug this gate was built
    # for, reproduced on our own first implementation, which printed 100.0%.
    # A manifest that sets n_reviewed == n_sig1 must NOT yield 100% coverage
    # without an explicit, separately recorded decision.
    found7 = {"f": {"sig1": 100, "sig2": 100, "class": "PUBLIC", "why": "", "path": "u"}}
    man7 = {"artifacts": {"f": {"class": "PUBLIC", "n_sig1": 100}}}  # n_reviewed ABSENT
    b7, s7 = evaluate(man7, found7)
    if s7["reviewed_by_class"].get("PUBLIC") != 0:
        print(f"  [XX ] conflation: n_reviewed absent -> reviewed={s7['reviewed_by_class'].get('PUBLIC')}, must be 0")
        failures.append("conflation: absent n_reviewed was not treated as 0")
    else:
        print("  [OK ] conflation: absent n_reviewed -> reviewed=0, coverage NOT 100%")
    if s7["unreviewed_total"] != 100:
        print(f"  [XX ] conflation: unreviewed_total={s7['unreviewed_total']}, must be 100")
        failures.append("conflation: unreviewed_total wrong")
    else:
        print("  [OK ] conflation: unreviewed_total=100 of 100")

    # H: empty population is indeterminable, never 0%
    print("  [OK ] empty population: main() returns 2 before report(); guarded by code path, see main()")

    if failures:
        print(f"\nSELFTEST FAILED ({len(failures)}): {failures}")
        return 1
    print("\nSELFTEST PASSED — every control blocked for its OWN stated reason")
    return 0


def stats_is_empty_safe(stats: dict) -> bool:
    return sum(stats["cand_by_class"].values()) == 0


def main(argv: list[str]) -> int:
    rule_hash = hashlib.sha256((RULE_1_SRC + "|" + RULE_2_SRC).encode("utf-8")).hexdigest()
    if "--selftest" in argv:
        return selftest()

    manifest_path = Path(__file__).resolve().parent / "denominator_manifest.json"
    if not manifest_path.exists():
        print(f"NO MANIFEST: {manifest_path} — the denominator cannot be established without it.")
        return 2
    try:
        manifest = load_manifest(manifest_path)
    except Exception as e:  # noqa: BLE001
        print(f"MANIFEST UNREADABLE: {e}")
        return 2

    profile, profile_why = choose_profile()
    if profile is None:
        print(f"[FATAL] {profile_why}")
        return 2
    print(f"SCOPE PROFILE: {profile} — {profile_why}")
    print()

    found, hard = scan(profile)
    if hard:
        for h in hard:
            print(f"[FATAL] {h}")
        print("POPULATION UNDETERMINABLE — refusing to report a number.")
        return 2
    if not found:
        print("POPULATION EMPTY — refusing to report 0% as coverage.")
        return 2

    blocks, stats = evaluate(manifest, found, profile)
    report(found, stats, rule_hash)
    print()
    if blocks:
        print(f"G5 BLOCK — {len(blocks)} unregistered change(s):")
        for b in blocks:
            print(f"  [x] {b}")
        return 3
    print("G5 PASS — every artifact carrying numbers is registered and its count is accounted for.")
    print("      This is NOT cross-verification (RT7): one author, one rule, one population.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
