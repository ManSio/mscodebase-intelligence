"""EXP-DUP: детекция дупликации через AST-нормализованные отпечатки функций (H-DUP).

Гипотеза: для multi-language (54 языка) AST-нормализация (tree-sitter уже есть)
+ minhash ближних дублей — реализуемо stdlib+numpy, без suffix-array движка
(fallow: suffix-array покрывает только JS/TS+CSS). pylint-django — НЕ dup-detector
(опровергнуто на PyPI-описании 2.8.0).
"""
import sys
import time
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from tree_sitter import Language, Parser
    import tree_sitter_python
    if hasattr(tree_sitter_python, "LANGUAGE"):
        _LANG = Language(tree_sitter_python.LANGUAGE)
    else:
        _LANG = Language(tree_sitter_python.language())
except Exception as e:
    print("tree_sitter_python недоступен:", e)
    sys.exit(1)

ID_TOKEN = {"identifier", "type_identifier", "field_identifier"}
LIT_TOKEN = {"string", "integer", "float", "bytes", "comment"}

def norm_tokens(node):
    """Листовые токены функции: идентификаторы/литералы -> плейсхолдеры."""
    out = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.child_count == 0:
            t = n.type
            if t in ID_TOKEN:
                out.append("<id>")
            elif t in LIT_TOKEN:
                out.append("<lit>")
            else:
                out.append(t)
        else:
            stack.extend(reversed(n.children))
    return out

def shingle_hash(tokens, k=8):
    """Хэши 8-грамм (64-бит) — база для minhash-близости."""
    sig = []
    for i in range(len(tokens) - k + 1):
        h = int.from_bytes(
            hashlib.sha1("|".join(tokens[i : i + k]).encode("utf-8")).digest()[:8],
            "big",
        )
        sig.append(h)
    return sig

def minhash(sig, size=64):
    if not sig:
        return []
    return [min(sig[i::size]) if i < len(sig) else min(sig) for i in range(size)]

def sim(a, b):
    """Jaccard-оценка по пересечению minhash-подписей."""
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / size

SRC = Path("D:/Project/MSCodeBase/src")
files = sorted(SRC.rglob("*.py"))
files = [f for f in files if "node_modules" not in str(f) and ".venv" not in str(f)]

t0 = time.perf_counter()
parser = Parser()
parser.language = _LANG

funcs = []  # (path, name, tokens, exact_hash)
size = 64
for fp in files:
    try:
        code = fp.read_bytes()
        if len(code) > 200_000:  # ограничение как в FileGuard (1MB, но для бенча меньше)
            continue
        tree = parser.parse(code)
    except Exception:
        continue
    root = tree.root_node
    for node in root.children:
        if node.type not in ("function_definition", "class_definition"):
            continue
        name = None
        for ch in node.children:
            if ch.type == "identifier":
                name = ch.text.decode("utf-8", "replace")
                break
        toks = norm_tokens(node)
        if len(toks) < 24:  # функции короче 24 токенов — шум
            continue
        h = hashlib.sha1("|".join(toks).encode("utf-8")).hexdigest()
        funcs.append((str(fp), name or "?", toks, h))

scan_ms = (time.perf_counter() - t0) * 1000
print(f"files={len(files)} functions/classes>=24tokens={len(funcs)} scan_ms={round(scan_ms, 1)}")

# Точные дубли
exact = {}
for fp, name, toks, h in funcs:
    exact.setdefault(h, []).append((fp, name))
dups = {h: v for h, v in exact.items() if len(v) > 1}
print(f"EXACT дубликаты (одинаковый нормализованный AST): {len(dups)} групп")
for h, v in list(dups.items())[:8]:
    print("   ", [f"{fp}:{name}" for fp, name in v])

# Ближние дубли (minhash Jaccard > 0.85) — выборка пар для бенча
t1 = time.perf_counter()
sigs = []
for fp, name, toks, h in funcs:
    sigs.append((fp, name, minhash(shingle_hash(toks), size)))
near = []
for i in range(len(sigs)):
    for j in range(i + 1, len(sigs)):
        s = sim(sigs[i][2], sigs[j][2])
        if s > 0.85:
            near.append((round(s, 3), sigs[i][0], sigs[i][1], sigs[j][0], sigs[j][1]))
near.sort(reverse=True)
pair_ms = (time.perf_counter() - t1) * 1000
print(f"NEAR-дубли (minhash>0.85): {len(near)} пар, pair_scan_ms={round(pair_ms, 1)}")
for s, a1, n1, a2, n2 in near[:10]:
    print(f"   {s}  {a1}:{n1}  ~  {a2}:{n2}")
