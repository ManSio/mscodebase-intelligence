"""Extract every comment (recursively nested) from all dengyier articles and
attribute them to Tom. Reports ROOT-vs-NESTED vs DECLARED so the population
of the answer is always printed with the answer.

Guard (protocol 19.6 / T10): if nothing is fetched, exit 2. If declared counts
disagree with fetched counts, the printed numbers are LOWER BOUNDS and the
script says so and exits 3.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (compatible; research/1.0; +https://dev.to/api)"

ARTICLES = [
    (4342586, 73, "Aug 7  'I ran the tests and they passed'"),
    (4361521, 26, "Aug 10 'Passes 2,283 Tests - Still Fails in Production'"),
    (4348641, 18, "Aug 8  'Protocol for Verifiable Execution'"),
    (4342553, 7,  "Aug 7  'On what authority do we accept delivery'"),
    (4475400, 6,  "Aug 24 'A Signed AI Agent Receipt Can Still Be Wrong'"),
    (4405184, 5,  "Aug 15 'Verifying the Verifier'"),
    (4474116, 4,  "Aug 24 'Verifiable Human Authority'"),
    (4378895, 4,  "Aug 12 'Protocol Specification'"),
    (4482066, 3,  "Aug 25 'The Biggest Barrier Is Not Intelligence'"),
    (4416607, 3,  "Aug 17 '68 Comments Later'"),
    (4439374, 2,  "Aug 20 'Two Verifiers One Verdict'"),
    (4476416, 1,  "Aug 24 'Human Control Cannot Be a Checkbox'"),
    (4610854, 0,  "Sep 9  'OpenWorkProof Update'"),
    (4410629, 0,  "Aug 16 'I Tampered With a VERIFIED delivery'"),
    (4474463, 0,  "Aug 24 'More Autonomous, More Final Say'"),
    (4341352, 0,  "Aug 7  'I built a protocol'"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.forem.api-v1+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def text_of(c):
    h = c.get("body_html") or ""
    t = re.sub(r"<[^>]+>", "", h)
    for ent, ch in (("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        t = t.replace(ent, ch)
    return t.strip()


def walk(nodes, depth=0):
    for n in nodes or []:
        yield n, depth
        yield from walk(n.get("children"), depth + 1)


TARGET = {"tjonesit", "tirthahq"}
rows = []
mismatch = []
grand = 0
tom_n = 0

print("=" * 96)
print("POPULATION LEDGER — declared (comments_count) vs fetched roots vs fetched all (incl. nested replies)")
print("=" * 96)
print(f"{'id':>8} {'declared':>9} {'roots':>6} {'nested':>7} {'all':>5} {'Tom':>4}  article")
for aid, declared, title in ARTICLES:
    try:
        data = fetch(f"https://dev.to/api/comments?a_id={aid}")
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        print(f"{aid:>8} {declared:>9} {'ERR':>6} {'-':>7} {'-':>5} {'-':>4}  {title}  [{e}]")
        mismatch.append((aid, declared, None, title))
        continue
    roots = [c for c in data if not c.get("parent_id")]
    allc = list(walk(data))
    nested = len(allc) - len(roots)
    hits = []
    for c, depth in allc:
        u = (c.get("user") or {}).get("username", "").lower()
        if u in TARGET:
            hits.append((c, depth))
    grand += len(allc)
    tom_n += len(hits)
    flag = ""
    if len(allc) != declared:
        flag = f"  MISMATCH (delta {len(allc) - declared:+d})"
        mismatch.append((aid, declared, len(allc), title))
    print(f"{aid:>8} {declared:>9} {len(roots):>6} {nested:>7} {len(allc):>5} {len(hits):>4}  {title}{flag}")
    for c, depth in hits:
        rows.append({
            "article_id": aid, "article_title": title,
            "id_code": c.get("id_code"), "created_at": c.get("created_at"),
            "username": (c.get("user") or {}).get("username"),
            "name": (c.get("user") or {}).get("name"),
            "depth": depth, "text": text_of(c),
        })
    time.sleep(0.25)

print()
print("=" * 96)
print(f"FETCHED ALL COMMENTS (roots+nested): {grand}")
print(f"TOM COMMENTS: {tom_n}")
print(f"ARTICLES WITH declared != fetched: {len(mismatch)}")
print("=" * 96)

with open(r"C:\Users\misha\.config\opencode\knowledge\tom-devto-comments.json", "w", encoding="utf-8") as f:
    json.dump({"population": {"fetched_all": grand, "articles_fetched": len(ARTICLES),
                             "declared_vs_fetched_mismatches": len(mismatch)},
               "tom_comments": rows}, f, ensure_ascii=False, indent=1)

if grand == 0:
    print("POPULATION EMPTY -> no metric computable.")
    sys.exit(2)
if mismatch:
    print("PARTIAL / CONTESTED POPULATION -> counts above are LOWER BOUNDS.")
    sys.exit(3)
print("saved -> knowledge/tom-devto-comments.json")
