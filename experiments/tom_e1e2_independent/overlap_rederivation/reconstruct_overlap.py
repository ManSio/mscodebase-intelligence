"""RECONSTRUCT overlap() verification from scratch (lost VERIFY_OVERLAP producer).

The 416-row frozen fixture (frozen/lab/overlap-fixture-fe4e465/) was built by the
package's own overlap() from starter/ + catalogue/ inputs. Those paths changed
across history (starter/ was added AFTER fe4e465; catalogue pages edited later),
so each input is taken from the revision whose derived sha256 equals the fixture's
own essence_sha256 -> the input set is provably the one the fixture used.

Independent impl (exact package semantics at fe4e465):
  _essence: text between markers, .strip("\\n")
  overlap: Jaccard over lowercase \\w{3,} token sets; essence[:1500] BEFORE lower; 0.0 if either empty.

Controls: 171 nonzero rows must not collapse to 0; 245 zero rows must stay 0.
Deterministic, $0.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CLONE = Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479")
ROOT = Path(r"D:\Project\tom_e1e2_2026-10-10")
FIX = ROOT / "frozen" / "lab" / "overlap-fixture-fe4e465" / "overlap-fixture-fe4e465.json"
MAKER = FIX.parent / "make-overlap-fixture.py"
OUT = ROOT / "results" / "VERIFY_OVERLAP_REDERV.json"

d = json.loads(FIX.read_text(encoding="utf-8"))
OM, CM = "<!-- crystal:essence -->", "<!-- /crystal:essence -->"
TOK = re.compile(r"\w{3,}")


def git_show(rev: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(CLONE), "show", f"{rev}:{path}"],
                          capture_output=True, text=True, encoding="utf-8").stdout


def git_revs(path: str) -> list[str]:
    return subprocess.run(["git", "-C", str(CLONE), "log", "--all", "--format=%H", "--", path],
                          capture_output=True, text=True, encoding="utf-8").stdout.split()


def raw_essence(t: str) -> str:
    a = t.find(OM)
    if a == -1:
        return ""
    b = t.find(CM, a)
    return t[a + len(OM):(b if b != -1 else None)].strip("\n")


def catalogue_body(t: str) -> str:
    return t.split("\n---\n", 1)[-1]


def pin(path: str, derive, want: str) -> tuple[str, str]:
    for rv in git_revs(path):
        if hashlib.sha256(derive(git_show(rv, path)).encode()).hexdigest() == want:
            return rv, derive(git_show(rv, path))
    return "", ""


synthetic_unicode = re.search(r'ess\["SYNTHETIC-unicode"\] = "([^"]*)"',
                              MAKER.read_text(encoding="utf-8")).group(1)

texts: dict[str, str] = {}
resolved_revs: dict[str, str] = {}
for key in d["input_kind"]:
    want = d["essence_sha256"][key]
    if key.startswith("starter/"):
        path = "starter/" + key[len("starter/"):]
        rv, txt = pin(path, raw_essence, want)
        texts[key], resolved_revs[key] = txt, rv
    elif key.startswith("catalogue/"):
        path = "catalogue/" + key[len("catalogue/"):]
        rv, txt = pin(path, catalogue_body, want)
        texts[key], resolved_revs[key] = txt, rv
    elif key == "SYNTHETIC-long-essence":
        texts[key] = d["synthetic_long_essence"]
    elif key == "SYNTHETIC-unicode":
        texts[key] = synthetic_unicode

integrity = {"checked": len(texts), "match": 0, "mismatch": 0, "diffs": []}
for k in d["input_kind"]:
    if hashlib.sha256(texts[k].encode()).hexdigest() == d["essence_sha256"][k]:
        integrity["match"] += 1
    else:
        integrity["mismatch"] += 1
        integrity["diffs"].append(k)
print("input integrity:", integrity["checked"], "match", integrity["match"], "mismatch", integrity["mismatch"])
if integrity["mismatch"]:
    print("unresolved inputs:", integrity["diffs"])


def overlap(a: str, e: str) -> float:
    at = set(re.findall(TOK, (a or "").lower()))
    et = set(re.findall(TOK, (e or "")[:1500].lower()))
    return len(at & et) / len(at | et) if (at and et) else 0.0


acts = d["acts"]
agree = disagree = 0
pos_total = pos_collapsed = neg_total = neg_collapsed = 0
samples = []
for r in d["rows"]:
    got, exp = overlap(acts[r["act_id"]], texts[r["entry"]]), r["overlap"]
    if round(got, 12) == round(exp, 12):
        agree += 1
    else:
        disagree += 1
        if len(samples) < 6:
            samples.append({"entry": r["entry"], "act_id": r["act_id"], "got": got, "exp": exp})
    if exp > 0:
        pos_total += 1
        pos_collapsed += (got == 0.0)
    else:
        neg_total += 1
        neg_collapsed += (got != 0.0)

res = {
    "note": "reconstruction of the lost VERIFY_OVERLAP producer; inputs pinned by fixture essence_sha256",
    "fixture": str(FIX), "clone": str(CLONE),
    "input_integrity": integrity, "resolved_revs": resolved_revs,
    "agree": agree, "disagree": disagree, "rows": len(d["rows"]),
    "control_positive_nonzero": pos_total, "control_positive_collapsed": pos_collapsed,
    "control_negative_zero": neg_total, "control_negative_flipped": neg_collapsed,
    "sample_disagreements": samples,
    "verdict": "ALL 416 ROWS REPRODUCE" if (agree == len(d["rows"]) and integrity["mismatch"] == 0)
               else f"MISMATCH rows={disagree} inputs={integrity['mismatch']}",
}
OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"agree={agree}/{len(d['rows'])} disagree={disagree}")
print(f"positive {pos_total} collapsed={pos_collapsed} | negative {neg_total} flipped={neg_collapsed}")
print("verdict:", res["verdict"])
print("wrote", OUT)