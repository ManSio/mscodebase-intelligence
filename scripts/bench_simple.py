import httpx, time
results = []
for bs in [1, 2, 4, 8]:
    texts = ["code snippet %d" % i for i in range(bs)]
    times = []
    for _ in range(3):
        t0 = time.time()
        r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": texts}, timeout=30)
        elapsed = time.time() - t0
        if r.status_code == 200:
            times.append(elapsed)
        time.sleep(0.15)
    if times:
        avg = sum(times)/len(times)
        results.append("batch=%d avg=%.3fs ch/s=%.0f" % (bs, avg, bs/avg))

t0 = time.time()
ok = 0
for i in range(30):
    r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["x"]*4}, timeout=30)
    if r.status_code == 200:
        ok += 1
burst1 = time.time() - t0
results.append("burst30_nosleep: %d/30 ok %.1fs %.0fch/s" % (ok, burst1, 120/burst1))

t0 = time.time()
ok2 = 0
for i in range(30):
    r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["x"]*4}, timeout=30)
    if r.status_code == 200:
        ok2 += 1
    time.sleep(0.3)
burst2 = time.time() - t0
results.append("burst30_sleep03: %d/30 ok %.1fs %.0fch/s" % (ok2, burst2, 120/burst2))

r = httpx.post("http://127.0.0.1:8080/v1/embeddings", json={"input": ["test code"]*8}, timeout=30)
vecs = [d["embedding"] for d in r.json()["data"]]
import math
zeros = sum(1 for v in vecs if max(abs(x) for x in v) < 1e-10)
norms = [math.sqrt(sum(x*x for x in v)) for v in vecs]
results.append("zero_check: %d/%d zeros, norms=[%s]" % (zeros, len(vecs), ",".join("%.3f" % n for n in norms)))

with open("embed_bench_result.txt","w") as f:
    f.write("\n".join(results))
print("OK")
for r in results:
    print(r)
