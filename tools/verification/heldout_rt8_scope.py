"""RT8 held-out — every gate must declare its scope and its decisive region,
and OUT OF SCOPE must never read as ALLOW.

Source: arXiv 2608.06940. Verification changes a label only in the pivotal
region; outside it an aggregate statistic can obscure a reliable conditional
effect. The protocol translation: a gate must say WHERE its verdict is decisive
and must return OUT_OF_SCOPE — not ALLOW — when it does not apply.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates as g  # noqa: E402

results = []
print("=" * 100)
print("RT8 HELD-OUT — scope declaration + decisive region + OUT_OF_SCOPE semantics")
print("=" * 100)

SAMPLES = [
    ("population", dict(population=10, computed_rate=0.5), "G1"),
    ("referent", dict(claim="10/11 per `EXP-1`"), "G2"),
    ("generalization", dict(verdict="CONFIRMED", evidence="held-out disjoint"), "G3"),
    ("control", dict(experiment="e", negative_control_shown_failing=True, controls_required=2), "G4"),
]

print("\n-- 1. every gate declares a scope AND a decisive region")
for action, kw, gname in SAMPLES:
    res, _ = g.run(action, **kw)
    has_scope = bool(res.get("scope")) and len(res["scope"]) > 40
    has_dec = bool(res.get("decisive_region")) and "undeclared" not in res["decisive_region"]
    has_negative = "does NOT judge" in (res.get("scope") or "")
    ok = has_scope and has_dec and has_negative
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {gname}: scope={has_scope} decisive={has_dec} names-what-it-does-NOT-judge={has_negative}")
    if not ok:
        print(f"        scope={res.get('scope')!r}")
        print(f"        decisive={res.get('decisive_region')!r}")

print("\n-- 2. OUT_OF_SCOPE must NOT be ALLOW, and must exit 0 (not a false BLOCK)")
for action, kw, gname in SAMPLES:
    res, rc = g.run(action, in_scope=False, **kw)
    ok = res["verdict"] == g.OUT_OF_SCOPE and res["verdict"] != "ALLOW" and rc == 0
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {gname} in_scope=False -> {res['verdict']} rc={rc}")

print("\n-- 3. the OUT_OF_SCOPE reason must say silence is not consent")
res, _ = g.run("population", in_scope=False, population=10, computed_rate=0.5)
ok = "NOT A PASS" in (res.get("why") or "")
results.append(ok)
print(f"  [{'OK ' if ok else 'XX '}] why names it: {res.get('why')!r}")

print("\n-- 4. G2 must be SILENT (ALLOW) outside its decisive region, and the gate must say so")
# "just a sentence with 12 in it" — no publishable number -> G2 cannot judge
res, _ = g.run("referent", claim="the run took 12 attempts in prose only")
silent_ok = res["verdict"] == "ALLOW" and "no publishable number" in (res.get("why") or "")
results.append(silent_ok)
print(f"  [{'OK ' if silent_ok else 'XX '}] non-publishable -> {res['verdict']}: {res.get('why')!r}")
print(f"        decisive_region: {res.get('decisive_region')}")

# the honest failure mode: that ALLOW is SILENCE, and scope says so
dec = res.get("decisive_region") or ""
silent_declared = "silent" in dec.lower() or "not examined" in dec.lower()
results.append(silent_declared)
print(f"  [{'OK ' if silent_declared else 'XX '}] the decisive_region declares that this ALLOW is silence")

print("\n-- 5. G3 must be silent for a verdict with no generalization claim")
res, _ = g.run("generalization", verdict="PARTIAL", evidence="anything")
ok = res["verdict"] == "ALLOW" and "no generalization claim" in (res.get("why") or "")
results.append(ok)
print(f"  [{'OK ' if ok else 'XX '}] verdict=PARTIAL -> {res['verdict']}: {res.get('why')!r}")

print("\n-- 6. scope text must be gate-specific, not one boilerplate string")
scopes = {gname: g.run(a, **kw)[0].get("scope") for a, kw, gname in SAMPLES}
distinct = len(set(scopes.values())) == len(SAMPLES)
results.append(distinct)
print(f"  [{'OK ' if distinct else 'XX '}] {len(set(scopes.values()))} distinct scope strings for {len(SAMPLES)} gates")

print("\n" + "=" * 100)
bad = results.count(False)
if bad:
    print(f"RT8 HELD-OUT FAILED: {bad} of {len(results)} checks")
    sys.exit(1)
print(f"RT8 HELD-OUT PASSED — {len(results)}/{len(results)}: scope declared, silence labelled")
