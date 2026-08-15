"""
EXP-7 — Adversarial probe: VC/Merkle vs Verify-On-Read.

Attacks the baseline illustration (experiment_concurrency_vs_semantic.py)
from 6 angles (Red Team protocol, AGENTS.md §1.16). Each attack changes
ONE variable and reports:
  FP = lies accepted as truth, FN = truths rejected, abstain = UNCHECKABLE.

Goal: find where the baseline result ("VC=2 lies, VOR=0") is a LAW and
where it is an artifact of scenario tuning / input privileges.
"""
import hashlib


def page_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


PAGE_V1 = "<html><body><button id='pay'>Pay</button></body></html>"
PAGE_V2 = "<html><body><button id='pay'>Pay Now</button></body></html>"  # cosmetic change
H1, H2 = page_hash(PAGE_V1), page_hash(PAGE_V2)

REAL_IMPORTS = ["duckdb", "sys", "os"]  # ground truth from real AST
POLLUTED_IMPORTS = ["duckdb", "sys", "os", "stripe"]  # "stripe" from README example, NOT code

ACCEPT = {"ACCEPTED", "VERIFIED"}
REJECT = {"REJECTED", "REFUTED"}


# ---------------- validators ----------------
def vc_only(mem, cur_hash, writers):
    """Baseline Arm VC: structural integrity + no write conflict. No semantics."""
    if mem["hash"] == cur_hash and writers == 0:
        return "ACCEPTED"
    return "REJECTED"


def vor_anchor(mem, imports):
    """Baseline Arm VOR: anchor membership in import list. No deeper semantics."""
    if mem.get("anchor") is None:
        return "UNCHECKABLE"
    return "VERIFIED" if mem["anchor"] in imports else "REFUTED"


def vc_semantics(mem, cur_hash, writers, imports):
    """A1 hybrid: SAME privileges as VOR (gets imports) + structural checks."""
    if mem["hash"] != cur_hash or writers != 0:
        return "REJECTED"
    return vor_anchor(mem, imports)


def run(title, arm, memories, notes=""):
    fp = fn = abstain = 0
    print(f"\n--- {title} ---")
    if notes:
        print(f"  ({notes})")
    for m in memories:
        v = arm(m)
        if v in ACCEPT and not m["truth"]:
            fp += 1
        if v in REJECT and m["truth"]:
            fn += 1
        if v == "UNCHECKABLE":
            abstain += 1
        flag = ("FP" if v in ACCEPT and not m["truth"]
                else "FN" if v in REJECT and m["truth"]
                else "abstain" if v == "UNCHECKABLE" else "ok")
        print(f"  {m['id']:>3} truth={str(m['truth']):>5} anchor={str(m.get('anchor')):>8} "
              f"-> {v:>10}  [{flag:>7}]  {m['claim']}")
    print(f"  => FP={fp}  FN={fn}  abstained={abstain}")
    return fp, fn, abstain


# ---------------- shared memories ----------------
BASE = [
    {"id": "M1", "claim": "We use DuckDB for analytics", "anchor": "duckdb", "hash": H1, "truth": True},
    {"id": "M2", "claim": "We use Stripe for payments", "anchor": "stripe", "hash": H1, "truth": False},
    {"id": "M3", "claim": "We use Redis for caching", "anchor": "redis", "hash": H1, "truth": False},
]

print("=" * 74)
print("EXP-7: ATTACKING THE BASELINE ILLUSTRATION FROM 6 ANGLES")
print("=" * 74)

# ---- A1: equal input privileges (kills the confound) ----
print("\n[A1] Kill the confound: give Arm VC the SAME semantic input (imports).")
run("A1a baseline VC (hash+writers only)", lambda m: vc_only(m, H1, 0), BASE)
run("A1b hybrid VC + semantic layer", lambda m: vc_semantics(m, H1, 0, REAL_IMPORTS), BASE,
    notes="VC now gets the import list too")

# ---- A2: VOR blind spot - false claim about a REAL anchor ----
M4 = {"id": "M4", "claim": "We use DuckDB for analytics", "anchor": "duckdb", "hash": H1, "truth": False}
run("A2 VOR at anchor-granularity: lie about a real import",
    lambda m: vor_anchor(m, REAL_IMPORTS), [M4],
    notes="reality: duckdb imported only for CSV parsing, analytics uses parquet files")

# ---- A3: claims with NO code anchor ----
M5a = {"id": "M5a", "claim": "CI is green on main", "anchor": None, "hash": H1, "truth": False}
M5b = {"id": "M5b", "claim": "CI is green on main", "anchor": None, "hash": H1, "truth": True}
run("A3a VOR + accept-by-default policy on UNCHECKABLE", lambda m: vor_anchor(m, REAL_IMPORTS), [M5a],
    notes="no import anchor exists for CI state")
run("A3b VOR + reject-by-default policy on UNCHECKABLE", lambda m: vor_anchor(m, REAL_IMPORTS), [M5b],
    notes="same, but the claim is actually TRUE")

# ---- A4a: VC over-sensitivity - page hash changed cosmetically ----
M6 = {"id": "M6", "claim": "We use DuckDB", "anchor": "duckdb", "hash": H1, "truth": True}
run("A4a VC under cosmetic change (button label changed, code untouched)",
    lambda m: vc_only(m, H2, 0), [M6],
    notes="memory bound to H1, current page H2")
run("A4a' VOR under the same cosmetic change", lambda m: vor_anchor(m, REAL_IMPORTS), [M6])

# ---- A4b: what VC uniquely catches - lost write under concurrency ----
M7 = {"id": "M7", "claim": "We use DuckDB", "anchor": "duckdb", "hash": H1, "truth": True}
run("A4b VC under concurrent write conflict (writers=1)",
    lambda m: vc_only(m, H1, 1), [M7],
    notes="writer B overwrote A's memory without resolution; A's true write lost")
run("A4b' VOR sees only the surviving state", lambda m: vor_anchor(m, REAL_IMPORTS), [M7],
    notes="the lost write is structurally invisible to semantic check")

# ---- A5: polluted ground truth (truth extraction is itself an agent pipeline) ----
run("A5 VOR grounded on POLLUTED import list", lambda m: vor_anchor(m, POLLUTED_IMPORTS), [BASE[1]],
    notes="'stripe' in the list came from a README docstring example, not real code")

# ---- A6: mutation - flip the scenario, does the baseline result survive? ----
run("A6 mutation: writers=1 on the BASELINE scenario", lambda m: vc_only(m, H1, 1), BASE,
    notes="baseline says 'VC accepts lies'; with one writer VC now rejects EVERYTHING, incl. the truth")

# ---------------- bottom line ----------------
print("\n" + "=" * 74)
print("BOTTOM LINE")
print("=" * 74)
print("""
1. The baseline result (VC=2 lies, VOR=0) is an ARTIFACT of input
   privileges (A1) and scenario choice (A6), not a law of nature.
   -> A hybrid with equal privileges and a semantic layer scores 0 lies.

2. VOR at anchor-granularity has its OWN false positives:
   - lies about real imports (A2: duckdb 'for analytics' but used for CSV),
   - polluted truth extraction (A5: README example polluted the import list).
   VOR also cannot judge claims without a code anchor (A3: any policy
   on UNCHECKABLE produces FP or FN).

3. VC has unique coverage that VOR structurally lacks:
   - lost writes / concurrent conflicts (A4b),
   - staleness detection - but page-level hashing is TOO COARSE (A4a:
     cosmetic change rejects a true memory). Correct design binds the
     hash to the claim's referents, not the whole page.

4. Conclusion: VC and VOR are complementary LAYERS, not competitors.
   'Verify-On-Read' alone is not sufficient (A2/A3/A5); 'VC+Merkle'
   alone is not sufficient (baseline). What matters is the presence of
   an external grounding layer + concurrency integrity + truthful
   extraction of the anchors themselves.
""")
