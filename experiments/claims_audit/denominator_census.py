"""Census of our PUBLICLY PUBLISHED numbers — the DERIVED denominator that
CLAIMS_MANIFEST.md never had.

Tom's critique (dev.to, article 4342586, depth 0):
  "a hand-authored manifest made the presented set eligible by definition, so
   the denominator was an assertion wearing the clothes of a measurement. A
   number built that way can only ever come back at 100%."

So: enumerate candidates by SCAN, do not by memory. Each candidate = one
numeric claim in a published artifact. Print the scan rule next to the count so
the count is never quotable without its population definition.

Guard: if the scan finds nothing -> exit 2 (no metric over empty input).
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PORT = Path(r"D:\Project\MSPortfolio")
REPO = Path(r"D:\Project\MSCodeBase")

# A numeric claim = a token that is a number AND sits next to a unit-ish word.
UNIT = (r"passing|passed|failed|fails|tests?|asserts?|checks?|guards?|chunks?|"
        r"ms|s\b|sec|seconds?|min|minutes?|hours?|days?|%|x\b|×|k\b|MB|KB|"
        r"nodes?|files?|experiments?|claims?|runs?|cycles?|articles?|issues?|"
        r"versions?|commits?|tokens?|lines?|words?|bytes?|pct|ratio|score")
NUM = r"[-+]?\d[\d ,._]*\s?(?:%|x\b|×|k\b|MB|KB|ms|s\b)?"
PAT = re.compile(rf"(?<![\w.]){NUM}\s*(?:{UNIT})", re.IGNORECASE)


def census(path: Path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return 0, f"UNREADABLE: {e}"
    return len(PAT.findall(txt)), ""


print("=" * 88)
print("DERIVED DENOMINATOR — numeric-claim census over PUBLISHED artifacts")
print("=" * 88)
print(f"scan rule: {PAT.pattern[:96]}...")
print()

groups = {
    "portfolio mirror (public JSON)": sorted(PORT.glob("src/data/lab/*.json")),
    "portfolio published md": sorted(PORT.glob("src/**/*.md")) or sorted(PORT.glob("*.md")),
    "repo: EXPERIMENTS_LOG.md": [REPO / "EXPERIMENTS_LOG.md"],
    "repo: AGENT_DIARY.md": [REPO / "AGENT_DIARY.md"],
    "repo: KNOWN_ISSUES.md": [REPO / "KNOWN_ISSUES.md"],
    "repo: ISSUE.md": [REPO / "ISSUE.md"],
    "repo: WISDOM.md": [REPO / "WISDOM.md"],
    "repo: README.md": [REPO / "README.md"],
}

total_files = 0
total = 0
for label, files in groups.items():
    print(f"--- {label}")
    if not files:
        print("    (no files matched)")
        continue
    for f in files:
        if not f.exists():
            print(f"    MISSING {f.name}")
            continue
        n, err = census(f)
        print(f"    {n:>5}  {f.relative_to(PORT.parent) if PORT in f.parents else f.name}")
        total += n
        total_files += 1
    print()

print("=" * 88)
print(f"FILES SCANNED: {total_files}    NUMERIC CLAIM CANDIDATES: {total}")
print("=" * 88)
print()
print("Compare against the hand-authored manifest denominator:")
print("  manifest Tier A rows : 14")
print("  manifest Tier B rows :  3")
print("  manifest TOTAL       : 17   <-- ASSERTED (author-chosen, one week old, no scan rule)")
print(f"  scan-derived TOTAL   : {total}   <-- DERIVED (every file in groups[] x scan rule)")
print()

if total_files == 0:
    print("POPULATION EMPTY -> census not computable.")
    sys.exit(2)
if total == 0:
    print("SCAN FOUND NOTHING -> either the rule is wrong or the corpus is empty. Loudly stopping.")
    sys.exit(2)

ratio = total / 17 if total else 0
print(f"VERDICT: the audited set covers {17}/{total} = {17/total*100:.1f}% of the scan-derived candidates")
print(f"         (un-audited share: {total-17}/{total} = {(total-17)/total*100:.1f}%)")
sys.exit(0)
