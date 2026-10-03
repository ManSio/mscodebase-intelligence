import hashlib
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (compatible; research/1.0; +https://dev.to/api)"
AID = 4342586
DECLARED = 73
HANDLE = "tom_jones_230c4659491adcd"
OURS = "mansio"


def fetch(u):
    r = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/vnd.forem.api-v1+json"})
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read().decode("utf-8"))


def clean(h):
    t = re.sub(r"</p>", "\n\n", h or "")
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    for e, c in (("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        t = t.replace(e, c)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def walk(ns, d=0):
    for n in ns or []:
        yield n, d
        yield from walk(n.get("children"), d + 1)


allc = list(walk(fetch(f"https://dev.to/api/comments?a_id={AID}")))
if len(allc) != DECLARED:
    print(f"POPULATION MISMATCH: fetched {len(allc)} != declared {DECLARED}. Refusing to report.")
    sys.exit(2)

by_user = {}
for c, d in allc:
    by_user.setdefault((c.get("user") or {}).get("username"), []).append((d, c))

lines = [
    "# Tom Jones on dev.to — raw comments (frozen corpus)",
    "",
    f"- article_id: {AID}",
    "- article: https://dev.to/dengyier/when-an-ai-agent-says-i-ran-the-tests-and-they-passed-do-you-trust-it-4ni1",
    f"- dev.to handle: `{HANDLE}`  (display name 'Tom Jones')",
    f"- population: {len(allc)} comments, == declared comments_count({DECLARED}) — VERIFIED",
    f"- distinct authors in thread: {len(by_user)}",
    "- sha256 of this frozen corpus file is printed at write time by the fetcher",
    "",
    "## Volume",
    "",
]
for u, v in sorted(by_user.items(), key=lambda kv: -len(kv[1])):
    lines.append(f"- `{u}` — {len(v)}")
lines += ["", "---", ""]

for u, v in sorted(by_user.items(), key=lambda kv: -len(kv[1])):
    if u not in (HANDLE, OURS):
        continue
    lines.append(f"## {u}")
    lines.append("")
    for d, c in sorted(v, key=lambda dc: dc[1].get("created_at") or ""):
        lines.append(f"### depth={d} id_code={c.get('id_code')} at={c.get('created_at')}")
        lines.append("")
        lines.append(clean(c.get("body_html")))
        lines.append("")
        lines.append("---")
        lines.append("")

txt = "\n".join(lines)
p = r"C:\Users\misha\.config\opencode\knowledge\tom-devto-thread-FROZEN.md"
with open(p, "w", encoding="utf-8") as f:
    f.write(txt)
print(f"wrote {p}")
print(f"sha256 {hashlib.sha256(txt.encode('utf-8')).hexdigest()}")
print(f"chars {len(txt)}  lines {len(lines)}")
