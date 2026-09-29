"""Probe run 2: score every AST-plausible chunk of artifact_gc.py on P3/R2 queries.
Identifies which gold chunk reproduces eval logit -0.99 (P3) / -2.60 (R2).
"""
import io, json, math, re, sys, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8081"
OUT = sys.argv[1]
SRC = open("D:\\Project\\MSCodeBase\\src\\core\\artifact_gc.py", encoding="utf-8").read()


def score(query, passages):
    payload = json.dumps({"query": query, "texts": passages}).encode()
    req = urllib.request.Request(BASE + "/rerank", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def sig(x):
    return 1.0 / (1.0 + math.exp(-x))


# Split into module-head + per-def chunks, mimicking AST chunking w/ scope header
parts = re.split(r"(?m)^(?=def |^class )", SRC)
chunks = {}
for i, p in enumerate(parts):
    m = re.match(r"(def |class )(\w+)", p)
    name = m.group(2) if m else "module_head"
    hdr = f"// Scope: other | function | src.core.artifact_gc\n" if m else "// Scope: module\n"
    chunks[name] = (hdr + p)[:800].strip()

print(f"n_chunks={len(chunks)} lens=" + ",".join(f"{k}:{len(v)}" for k, v in chunks.items()), flush=True)
QUERIES = {
    "P3_orig": "ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy",
    "R2_orig": "ArtifactGC 30d projects 90d telemetry 7d logs retention",
}
result = {}
for qname, q in QUERIES.items():
    names = list(chunks)
    raw = score(q, [chunks[k] for k in names])
    logits = [d["score"] for d in sorted(raw, key=lambda d: d["index"])]
    print(f"== {qname} ==", flush=True)
    for n, lg in sorted(zip(names, logits), key=lambda t: t[1], reverse=True):
        print(f"  {n:22s} logit={lg:+.4f} sig={sig(lg):.4f}", flush=True)
    result[qname] = {n: lg for n, lg in zip(names, logits)}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1)
print(f"WROTE {OUT}", flush=True)
