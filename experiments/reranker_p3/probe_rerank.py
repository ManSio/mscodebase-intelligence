"""Fresh-process direct reranker probe for OPEN item #3 (P3/R2 gold below threshold).
Bypasses retrieval: POSTs straight to llama.cpp /v1/rerank on :8081.
Stdlib only. Raw JSON -> same dir as this script (%TEMP%\\opencode\\).
"""
import io, json, math, sys, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:8081"
OUT = sys.argv[1] if len(sys.argv) > 1 else "rerank_probe_out.json"

REPO = "D:\\Project\\MSCodeBase"


def load(rel, n=800):
    with open(REPO + "\\" + rel, encoding="utf-8") as f:
        return f.read()[:n].strip()


def score(query, passages):
    payload = json.dumps({"query": query, "texts": passages}).encode()
    req = urllib.request.Request(BASE + "/rerank", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def sig(x):
    return 1.0 / (1.0 + math.exp(-x))


GOLD_DOC = load("src\\core\\artifact_gc.py", 800)          # module docstring head
GOLD_CODE = open(REPO + "\\src\\core\\artifact_gc.py", encoding="utf-8").read()[1500:2300]  # _prune body
D_ENGINE = load("src\\core\\search\\engine.py", 800)
D_SETTINGS = load("src\\config\\settings.py", 800)
D_DIARY = load("AGENT_DIARY.md", 800)

QUERIES = {
    "P3_orig": "ArtifactGC _cleanup_old_projects 30d 90d 7d retention_policy",
    "R2_orig": "ArtifactGC 30d projects 90d telemetry 7d logs retention",
    "short": "ArtifactGC",
    "keyword": "ArtifactGC cleanup old projects retention days",
    "defform": "What is the ArtifactGC retention policy for old projects telemetry logs",
    "real_symbols": "ArtifactGC prune_stale_artifacts project_max_age_days telemetry_max_age_days",
}

PASSAGES = {"gold_doc": GOLD_DOC, "gold_code": GOLD_CODE, "distr_engine": D_ENGINE,
            "distr_settings": D_SETTINGS, "distr_diary": D_DIARY}

print(f"gold_doc len={len(GOLD_DOC)} gold_code len={len(GOLD_CODE)} "
      f"max_passage={max(len(p) for p in PASSAGES.values())}", flush=True)

result = {"queries": {}, "passage_lens": {k: len(v) for k, v in PASSAGES.items()}}
for qname, q in QUERIES.items():
    names = list(PASSAGES)
    raw = score(q, [PASSAGES[k] for k in names])
    logits = [d["score"] for d in sorted(raw, key=lambda d: d["index"])]
    ranked = sorted(zip(names, logits), key=lambda t: t[1], reverse=True)
    result["queries"][qname] = {
        "query": q,
        "logits": {n: lg for n, lg in zip(names, logits)},
        "sigmoid": {n: round(sig(lg), 4) for n, lg in zip(names, logits)},
        "rank": [n for n, _ in ranked],
    }
    print(f"== {qname} ==", flush=True)
    for n, lg in ranked:
        print(f"  {n:14s} logit={lg:+.4f} sig={sig(lg):.4f}", flush=True)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1)
print(f"WROTE {OUT}", flush=True)
