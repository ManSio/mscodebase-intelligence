import collections
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (compatible; research/1.0; +https://dev.to/api)"
AIDS = [4342586, 4361521, 4348641, 4342553, 4475400, 4405184, 4474116,
        4378895, 4482066, 4416607, 4439374, 4476416]


def fetch(u):
    r = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/vnd.forem.api-v1+json"})
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read().decode("utf-8"))


def walk(ns, d=0):
    for n in ns or []:
        yield n, d
        yield from walk(n.get("children"), d + 1)


authors = collections.Counter()
names = collections.defaultdict(set)
rows = []
for aid in AIDS:
    for c, d in walk(fetch(f"https://dev.to/api/comments?a_id={aid}")):
        u = (c.get("user") or {})
        un = u.get("username") or "?"
        authors[un] += 1
        names[un].add(u.get("name") or "?")
        h = re.sub(r"<[^>]+>", " ", c.get("body_html") or "")
        rows.append((aid, d, un, u.get("name"), h))

print(f"TOTAL COMMENTS: {len(rows)}   DISTINCT AUTHORS: {len(authors)}")
print("=" * 78)
print("AUTHORS BY VOLUME (username | display name | comments)")
print("=" * 78)
for un, n in authors.most_common():
    print(f"  {n:>3}  {un:<34} {'/'.join(sorted(names[un]))}")

print()
print("=" * 78)
print("FUZZY MATCHES on name fields (jones / tom / tirtha / crystal)")
print("=" * 78)
hits = 0
for aid, d, un, nm, h in rows:
    blob = f"{un} {nm}".lower()
    if any(k in blob for k in ("jones", "tom", "tirtha", "crystal", "t_jones", "tjones")):
        hits += 1
        print(f"\n--- article {aid} depth={d} user={un} name={nm}")
        print("   ", h.strip()[:700].replace("\n", " "))
print(f"\nMATCHES: {hits}")
if hits == 0:
    print("\nNEGATIVE CONTROL RESULT: no author in the 152-comment population matches the name.")
    sys.exit(0)
