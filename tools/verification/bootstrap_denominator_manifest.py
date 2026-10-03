import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g5_denominator as g  # noqa: E402

profile, profile_why = g.choose_profile()
print(f"scope profile: {profile} — {profile_why}")

found, hard = g.scan(profile)
if hard:
    print("HARD FAILURES:")
    for h in hard:
        print("  ", h)
    sys.exit(2)
if not found:
    print("EMPTY POPULATION")
    sys.exit(2)

reg = {}
for label, e in sorted(found.items()):
    entry = {
        "class": e["class"],
        "reason": e["why"],
        "n_sig1": e["sig1"],
        "n_sig2": e["sig2"],
        # n_reviewed is the count a HUMAN has actually classified. It starts at 0
        # and may only rise by explicit per-artifact classification. Bootstrapping
        # it to n_sig1 is the exact pathology G5 exists to prevent (RT9).
        "n_reviewed": 0,
    }
    reg[label] = entry

# A manifest holds every artifact, plus which profiles each belongs to. Regenerating
# from one profile must not delete the other profile's entries, or a bare clone
# would rewrite the manifest into a shape that then fails on a full checkout.
all_labels = {lbl for lbl, *_ in g.ARTIFACTS}
for lbl, path, cls, why, profiles in g.ARTIFACTS:
    if lbl in reg:
        reg[lbl]["profiles"] = list(profiles)
    else:
        reg[lbl] = {
            "class": cls, "reason": why,
            "n_sig1": None, "n_sig2": None,
            "n_reviewed": 0,
            "profiles": list(profiles),
            "note": "out of scope for the profile this manifest was generated with; "
                    "regenerate under that profile to fill it in",
        }

man = {
    "rule_version": g.RULE_VERSION,
    "generated_for_profile": profile,
    "scope_profiles": {k: v for k, v in g.SCOPE_PROFILES.items()},
    "rule1": g.RULE_1_SRC,
    "rule2": g.RULE_2_SRC,
    "rule_sha256": hashlib.sha256((g.RULE_1_SRC + "|" + g.RULE_2_SRC).encode()).hexdigest(),
    "projects_root": str(g.PROJECTS_ROOT),
    "note": (
        "n_sig1 is DERIVED by the rule above. n_reviewed is AUTHORED and starts at 0. "
        "class and reason are JUDGEMENT (RT4), stated per artifact so the boundary is visible. "
        "Coverage is n_reviewed / n_sig1 and is 0% by construction until real classification happens. "
        "Each artifact lists the scope profiles it belongs to; null counts mean it was out of scope "
        "when this manifest was generated."
    ),
    "artifacts": reg,
}

p = Path(__file__).resolve().parent / "denominator_manifest.json"
p.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", p, "artifacts:", len(reg))
in_scope = {k: v for k, v in reg.items() if v["n_sig1"] is not None}
out_scope = [k for k, v in reg.items() if v["n_sig1"] is None]
print("total found (in profile %s):" % profile, sum(v["n_sig1"] for v in in_scope.values()))
print("total reviewed:", sum(v["n_reviewed"] for v in reg.values()))
if out_scope:
    print("out of profile (%d, counts left null — regenerate under their profile):" % len(out_scope))
    for k in out_scope:
        print("    ", k)
tot = {}
for k, v in sorted(in_scope.items(), key=lambda kv: -kv[1]["n_sig1"]):
    tot[v["class"]] = tot.get(v["class"], 0) + v["n_sig1"]
    print("  %5d  %-9s %s" % (v["n_sig1"], v["class"], k))
print("by class:", tot)
