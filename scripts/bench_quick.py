import httpx, time, sys, math

out = []
try:
    for bs in [1, 2, 4, 8]:
        texts = ["code %d" % i for i in range(bs)]
        t0 = time.time()
        r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": texts}, timeout=30)
        t1 = time.time()
        out.append("batch=%d status=%d time=%.3fs ch/s=%.0f" % (bs, r.status_code, t1 - t0, bs / (t1 - t0)))
        time.sleep(0.2)

    ok = 0
    t0 = time.time()
    for i in range(20):
        r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["x"] * 4}, timeout=30)
        if r.status_code == 200:
            ok += 1
    t1 = time.time()
    out.append("burst20_nosleep: %d/20 ok %.1fs %.0fch/s" % (ok, t1 - t0, 80 / (t1 - t0)))

    ok2 = 0
    t0 = time.time()
    for i in range(20):
        r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["x"] * 4}, timeout=30)
        if r.status_code == 200:
            ok2 += 1
        time.sleep(0.3)
    t1 = time.time()
    out.append("burst20_sleep03: %d/20 ok %.1fs %.0fch/s" % (ok2, t1 - t0, 80 / (t1 - t0)))

    r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["test code"] * 8}, timeout=30)
    vecs = [d["embedding"] for d in r.json()["data"]]
    zeros = sum(1 for v in vecs if max(abs(x) for x in v) < 1e-10)
    norms = [math.sqrt(sum(x * x for x in v)) for v in vecs]
    out.append("zero_check: %d/%d zeros" % (zeros, len(vecs)))
    out.append("norms: %s" % " ".join("%.3f" % n for n in norms))

except Exception as e:
    out.append("ERROR: %s" % str(e))

with open("bench_out.txt", "w") as f:
    f.write("\n".join(out))
print("DONE")
