import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g5_denominator as g  # noqa: E402

found, hard = g.scan()
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
    reg[label] = {
        "class": e["class"],
        "reason": e["why"],
        "n_sig1": e["sig1"],
        "n_sig2": e["sig2"],
        # n_reviewed is the count a HUMAN has actually classified. It starts at 0
        # and may only rise by explicit per-artifact classification. Bootstrapping
        # it to n_sig1 is the exact pathology G5 exists to prevent (RT9).
        "n_reviewed": 0,
    }

man = {
    "rule_version": g.RULE_VERSION,
    "rule1": g.RULE_1_SRC,
    "rule2": g.RULE_2_SRC,
    "rule_sha256": hashlib.sha256((g.RULE_1_SRC + "|" + g.RULE_2_SRC).encode()).hexdigest(),
    "projects_root": str(g.PROJECTS_ROOT),
    "note": (
        "n_sig1 is DERIVED by the rule above. n_reviewed is AUTHORED and starts at 0. "
        "class and reason are JUDGEMENT (RT4), stated per artifact so the boundary is visible. "
        "Coverage is n_reviewed / n_sig1 and is 0% by construction until real classification happens."
    ),
    "artifacts": reg,
}

p = Path(__file__).resolve().parent / "denominator_manifest.json"
p.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", p, "artifacts:", len(reg))
print("total found:", sum(v["n_sig1"] for v in reg.values()))
print("total reviewed:", sum(v["n_reviewed"] for v in reg.values()))
tot = {}
for k, v in sorted(reg.items(), key=lambda kv: -kv[1]["n_sig1"]):
    tot[v["class"]] = tot.get(v["class"], 0) + v["n_sig1"]
    print("  %5d  %-9s %s" % (v["n_sig1"], v["class"], k))
print("by class:", tot)
