import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (compatible; research/1.0; +https://dev.to/api)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.forem.api-v1+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


aid = 4342586
declared = 73
top = fetch(f"https://dev.to/api/comments?a_id={aid}")
roots = [c for c in top if not c.get("parent_id")]
kids = [c for c in top if c.get("parent_id")]
print(f"article {aid}: declared={declared}  a_id-fetch={len(top)}  roots={len(roots)}  children_included={len(kids)}")
print()
print("ACTUAL KEYS on one payload item:")
print(sorted(top[0].keys()))
print()
print("SAMPLE item (body truncated):")
s = dict(top[0])
if "body_html" in s:
    s["body_html"] = s["body_html"][:120] + "..."
print(json.dumps(s, ensure_ascii=False, indent=1)[:1200])
print()

# Are children reachable at all? dev.to nests replies inside body_html or a children key.
for key in ("children", "descendants", "replies"):
    if key in top[0]:
        print(f"FOUND nested key: {key} -> len={len(top[0][key])}")
print()
has_nested = sum(1 for c in top for k in ("children", "descendants") if c.get(k))
print(f"items carrying a nested-children key: {has_nested}/{len(top)}")
