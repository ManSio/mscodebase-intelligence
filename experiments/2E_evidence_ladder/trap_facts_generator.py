#!/usr/bin/env python3
"""trap_facts_generator.py — E5: расширение trap-категории с валидацией ПО СУБЪЕКТУ (P-00X).

Фикс генератора v4_rep (RED TEAM 2026-08-16): value обязан ОТСУТСТВОВАТЬ в файле
СУБЪЕКТА (grep файла = 0), а не просто отличаться от real_value. Иначе «false»-claim
может быть истинным (R43/R45/R46/R47).

Категории (N≈30):
  trap_false  — value импортирован в ПРОЕКТЕ (≥2 файлов), но НЕ в файле субъекта
                (grep файла = 0, проверено): claim «<Субъект> использует <value>» → false.
  trap_true   — value реально импортирован/использован в файле субъекта: claim → true.

Ground truth детерминированный (ast + grep по файлу субъекта), БЕЗ LLM.
Usage:
  python experiments/2E_evidence_ladder/trap_facts_generator.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
OUT_DIR = ROOT / "experiments" / "2E_evidence_ladder"

# Субъекты: (label_ru, rel_path) — реальные модули проекта
SUBJECTS = [
    ("Серверная обёртка", "src/mcp/server.py"),
    ("Граф знаний", "src/core/graph.py"),
    ("Кросс-проектный поиск", "src/core/multi_project_searcher.py"),
    ("Сторожевой таймер", "src/core/indexing/watchdog.py"),
    ("Загрузчик моделей", "src/providers/reranker/llama_install.py"),
    ("Слой верификации чтения", "src/core/intelligence/verify_on_read.py"),
    ("Поисковый движок", "src/core/search/engine.py"),
    ("Движок консистентности", "src/core/consistency.py"),
    ("Сканер инструкций", "src/core/instruction_scan.py"),
    ("Удалённый эмбеддер", "src/providers/embedder/remote_embedder.py"),
]

MIN_PROJECT_FILES = 2   # value должен встречаться минимум в N файлах проекта
MAX_FALSE_PER_SUBJECT = 2
MAX_TRUE_PER_SUBJECT = 1


def _ast_imports(text: str) -> list[str]:
    """Имена импортов файла: 'import x' / 'from x import y' → базовое имя x."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module.split(".")[0])
    return out


def _project_import_stats() -> Counter:
    """Counter: имя импорта → число файлов проекта, где встречается (word-boundary)."""
    counts: Counter = Counter()
    for f in SRC.rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen = set()
        for name in _ast_imports(text):
            if name not in seen:
                seen.add(name)
                counts[name] += 1
    return counts


def _in_file(text: str, value: str) -> bool:
    """Слово встречается в содержимом файла (case-insens, word-boundary) — валидация по субъекту."""
    return bool(re.search(rf"\b{re.escape(value)}\b", text, re.IGNORECASE))


def generate() -> list[dict]:
    stats = _project_import_stats()
    facts: list[dict] = []
    for label, rel in SUBJECTS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        actual = set(_ast_imports(text))
        # false-trap: value в проекте (>=MIN_PROJECT_FILES), НЕ в файле субъекта
        false_added = 0
        for value, nfiles in stats.most_common():
            if false_added >= MAX_FALSE_PER_SUBJECT:
                break
            if nfiles < MIN_PROJECT_FILES or value in actual or _in_file(text, value):
                continue
            facts.append({
                "id": f"TP{len(facts) + 1:02d}", "truth": False, "kind": "trap_false",
                "subject": rel.split("/")[-1][:-3], "value": value,
                "claim": f"{label} использует {value}",
                "support_patterns": [value],
                "label_validated": f"project_files={nfiles}, subject_file=0 (P-00X: grep субъекта)",
            })
            false_added += 1
        # true-control: value реально используется субъектом (не boilerplate)
        for value in sorted(actual):
            if value in ("__future__", "annotations", "typing") or len(facts) >= len(SUBJECTS) * 3:
                continue
            facts.append({
                "id": f"TP{len(facts) + 1:02d}", "truth": True, "kind": "trap_true",
                "subject": rel.split("/")[-1][:-3], "value": value,
                "claim": f"{label} использует {value}",
                "support_patterns": [value],
                "label_validated": "subject_file>0 (P-00X: grep субъекта)",
            })
            break  # 1 true на субъект
    return facts


def main() -> int:
    facts = generate()
    doc = {
        "_meta": {
            "experiment": "Exp 2-E E5 — расширение trap-категории (P-00X фикс генератора)",
            "date": "2026-08-16",
            "design": "trap_false: value в проекте (>=2 файлов), НЕ в файле субъекта (grep=0); "
                      "trap_true: value в файле субъекта. Валидация лейблов ПО СУБЪЕКТУ.",
            "n_total": len(facts),
        },
        "facts": facts,
    }
    from collections import Counter
    sha = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    out = OUT_DIR / f"trap_facts_expanded_{sha}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[trap-gen] N={len(facts)} kinds={dict(Counter(f['kind'] for f in facts))} fp={sha}")
    print(f"[trap-gen] written: {out.relative_to(ROOT)}")
    for f in facts[:6]:
        print(f"  {f['id']} {f['kind']:10s} truth={f['truth']} | {f['claim']} [{f['label_validated']}]")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — §5.11: try/except в каждом скрипте
        import traceback
        traceback.print_exc()
        sys.exit(1)
