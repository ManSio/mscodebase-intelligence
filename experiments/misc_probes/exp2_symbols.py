"""Exp 2: сравнение извлечения символов — текущий CodeParser vs tree-sitter tags.scm.

Запуск: <venv>/python.exe -X utf8 experiments/exp2_symbols.py
Сравнение на src/core/graph.py (реальный файл ~1100 строк).

Предусловие для метода B (tags.scm): pip install tree-sitter-language-pack
(в любом окружении с tree-sitter 0.26+; abi3-колесо совместимо с 3.14).
"""
import re
import sys
import time
from pathlib import Path

TARGET = r"D:\Project\MSCodeBase\src\core\graph.py"

# ── Ground truth: все определения из файла (grep-эквивалент) ──────────────
with open(TARGET, encoding="utf-8") as f:
    source = f.read()

def_truth = re.findall(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", source, re.M)
print(f"Ground truth (regex def/class, включая методы): {len(def_truth)}")

# ── Метод A: текущий CodeParser (проект) ──────────────────────────────────
sys.path.insert(0, r"D:\Project\MSCodeBase")
from src.core.indexing.parser import CodeParser  # noqa: E402

t0 = time.time()
cp = CodeParser()
chunks, symbols = cp.parse_file(Path(TARGET))
t_a = time.time() - t0
print(f"\n[A] CodeParser init+parse_file: {t_a*1000:.0f} ms")
print(f"[A] chunks: {len(chunks)}")
print(f"[A] symbols: {len(symbols)}")
names_a = [s.get("name") for s in symbols if s.get("name")]
print(f"[A] symbol names: {len(names_a)}, sample: {names_a[:15]}")

# ── Метод B: tags.scm через tree-sitter-language-pack ────────────────────
try:
    from tree_sitter_language_pack import get_parser, get_tags_query  # noqa: E402
    from tree_sitter import Query, QueryCursor  # noqa: E402
    HAVE_PACK = True
except ImportError:
    HAVE_PACK = False
    print("\n[B] tree-sitter-language-pack не установлен — метод B пропущен.")
    print("    Предусловие: pip install tree-sitter-language-pack")

if HAVE_PACK:
    t0 = time.time()
    parser = get_parser("python")
    tree = parser.parse(source.encode("utf-8"))
    query = Query(parser.language, get_tags_query("python"))
    cursor = QueryCursor(query)
    res = cursor.captures(tree.root_node)
    t_b = time.time() - t0
    print(f"\n[B] tags.scm parse+query: {t_b*1000:.0f} ms")
    defs_b = []
    for node in res.get("definition.function", []):
        m = re.search(r"def\s+(\w+)", node.text.decode())
        if m:
            defs_b.append(m.group(1))
    for node in res.get("definition.class", []):
        m = re.search(r"class\s+(\w+)", node.text.decode())
        if m:
            defs_b.append(m.group(1))
    print(f"[B] defs from tags.scm: {len(defs_b)}")

    # ── Сравнение ────────────────────────────────────────────────────────────
    set_truth = set(def_truth)
    set_b = set(defs_b)
    missing_b = set_truth - set_b
    extra_b = set_b - set_truth
    print(f"\n[B] recall vs truth: {len(set_truth & set_b)}/{len(set_truth)} = {100*len(set_truth & set_b)/max(1,len(set_truth)):.1f}%")
    print(f"[B] missing: {sorted(missing_b)[:10]}")
    print(f"[B] extra: {sorted(extra_b)[:10]}")
