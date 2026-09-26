import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
t = open(r"D:\Project\MSCodeBase\experiments\embeddinggemma\bench.py", encoding="utf-8").read()

m = re.search(r"GOLD\s*=\s*\[(.*?)\]\n\n", t, re.S)
g = m.group(1)
pairs = re.findall(r"\(" + '"' + r"[^\"']+" + r"',\s*['\"]" + r"([^\"']+)" + r"['\"]\)", g)
print("GOLD pairs:", len(pairs))
for q, f in pairs[:16]:
    print("  RU?" , q, "->", f.rsplit("/", 1)[-1])
