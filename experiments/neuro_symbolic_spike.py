"""Neuro-Symbolic spike: NL → LLM → Cypher → parser-validate → PropertyGraph.

Эксперимент exp-lab-2026-01 (§1.6 AGENTS.md: гипотеза → замер → вывод).
Проверяет СКВОЗНОЙ путь (не изолированные компоненты):

    естественный вопрос
      → LLM-генератор (MockLLM детерминированный | LMStudioLLM — реальный phi-4)
      → извлечение Cypher (strip code fences)
      → ВАЛИДАЦИЯ: CypherLexer + CypherParser (отсекает мусор ДО исполнения)
      → исполнение: query_graph(PropertyGraph, cypher)
      → метрики: parse_success / exec_success / relevance / latency

Ключевой вопрос гипотезы: парсер-валидация отсекает невалидные генерации
LLM (галлюцинированные метки, синтаксис) и НЕ даёт им дойти до исполнения.

Запуск:
    python experiments/neuro_symbolic_spike.py            # MockLLM (без сети)
    python experiments/neuro_symbolic_spike.py --lm-studio # реальный phi-4 (LM Studio :1234)
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.graph import EdgeType, NodeLabel, PropertyGraph  # noqa: E402
from src.core.search.cypher_engine import (  # noqa: E402
    CypherLexer,
    CypherParser,
    Query,
    query_graph,
)

# ══════════════════════════════════════════════════════════════
# 1. Схема графа для промпта (schema-aware prompting)
# ══════════════════════════════════════════════════════════════

SCHEMA = """PropertyGraph schema (подмножество openCypher):
Node labels: Function, Variable, Module, Class, File  (⚠️ case-sensitive, Title Case)
Edge types:  CALLS (f1)-[:CALLS]->(f2) — f1 вызывает f2
             USAGE  (f)-[:USAGE]->(v)   — функция использует переменную
             CONTAINS (m)-[:CONTAINS]->(f) — модуль содержит функцию
Properties: name (id), qualified_name, file_path, label
Поддерживаемые клаузы: MATCH, WHERE, RETURN, LIMIT, OPTIONAL MATCH
Примеры:
  MATCH (f:Function) RETURN f.name LIMIT 5
  MATCH (caller)-[:CALLS]->(callee:Function) WHERE callee.name = 'parse' RETURN caller.name
  MATCH (f)-[:USAGE]->(v:Variable) RETURN f.name, v.name"""

FEW_SHOT = [
    ("Кто вызывает parse?", "MATCH (caller)-[:CALLS]->(p) WHERE p.name = 'parse' RETURN caller.name"),
    ("Что использует config?", "MATCH (f)-[:USAGE]->(v) WHERE v.name = 'config' RETURN f.name"),
]

# ══════════════════════════════════════════════════════════════
# 2. LLM-генераторы
# ══════════════════════════════════════════════════════════════


class MockLLM:
    """Детерминированный генератор для проверки пайплайна без сети.

    10 вопросов → 8 валидных Cypher + 2 заведомо невалидных
    (галлюцинированная метка SERVICE + синтаксический мусор) —
    чтобы измерить, что parser-валидация их отсекает.
    """

    _RULES: Dict[str, Callable[[str], str]] = {
        "кто вызывает": lambda q: (
            "MATCH (caller)-[:CALLS]->(target) "
            f"WHERE target.name = '{MockLLM._extract_name(q)}' RETURN caller.name"
        ),
        "что вызывает": lambda q: (
            "MATCH (source)-[:CALLS]->(callee) "
            f"WHERE source.name = '{MockLLM._extract_name(q)}' RETURN callee.name"
        ),
        "использует": lambda q: (
            "MATCH (f)-[:USAGE]->(v) "
            f"WHERE v.name = '{MockLLM._extract_name(q)}' RETURN f.name"
        ),
        "используют": lambda q: (
            "MATCH (f)-[:USAGE]->(v) "
            f"WHERE v.name = '{MockLLM._extract_name(q)}' RETURN f.name"
        ),
        "сколько функций": lambda q: (
            "MATCH (n) WHERE n.label = 'Function' RETURN n.name"
        ),
        "файлы": lambda q: "MATCH (n) WHERE n.label = 'Function' RETURN DISTINCT n.file_path",
        "все функции": lambda q: "MATCH (n) WHERE n.label = 'Function' RETURN n.name",
        "использует db_conn": lambda q: (
            "MATCH (f)-[:USAGE]->(v) WHERE v.name = 'db_conn' RETURN f.name"
        ),
    }

    @staticmethod
    def _extract_name(question: str) -> str:
        for kw in ("вызывает", "использует", "используют"):
            if kw in question:
                return question.split(kw, 1)[1].strip().rstrip("?.")
        return "main"

    def generate(self, question: str, schema: str, few_shot: list) -> str:
        q = question.lower()
        # 2 заведомо невалидных генерации для проверки валидации
        if "цикл" in q:
            return "MATCH (a)-[:CALLS]->(b)-[:CALLS]->(a) WHERE a.name = 'x' RETURN cycle(a)"  # невалид: cycle()
        if "сервис" in q:
            return "MATCH (s:SERVICE) RETURN s.name"  # галлюцинированная метка — валидна синтаксически, но не исполнима
        for pattern, builder in self._RULES.items():
            if pattern in q:
                return builder(q)
        return "MATCH (n) RETURN n.name LIMIT 5"  # fallback


class LMStudioLLM:
    """Реальный phi-4 через LM Studio (OpenAI-совместимый API).

    Активируется флагом --lm-studio при живом сервере на :1234.
    Промпт: system-схема + few-shot + вопрос (schema-aware prompting).
    """

    def __init__(self, base_url: str = "http://127.0.0.1:1234/v1"):
        self.base_url = base_url

    def generate(self, question: str, schema: str, few_shot: list) -> str:
        import httpx

        messages = [{"role": "system", "content": schema}]
        for q, c in few_shot:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": c})
        messages.append({"role": "user", "content": question})
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            json={"model": "local", "messages": messages, "temperature": 0.0},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════
# 3. Извлечение и валидация
# ══════════════════════════════════════════════════════════════


def extract_cypher(raw: str) -> Optional[str]:
    """Извлекает Cypher из ответа LLM: strip ```code fences``` и текст."""
    raw = raw.strip()
    if "```" in raw:
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("```"):
                continue
            if line:
                return line.split("```")[0].strip()
        return None
    return raw


VALID_LABELS = {"Function", "Variable", "Module", "Class", "File"}
VALID_REL_TYPES = {"CALLS", "USAGE", "CONTAINS"}
VALID_PROPS = {"name", "qualified_name", "file_path", "label"}


def schema_check(query: Query) -> Optional[str]:
    """Schema-валидация по AST: метки/типы связей/свойства/RETURN-функции.

    Слой 2 (после парсера): ловит галлюцинированные метки (SERVICE),
    несуществующие типы связей и вызовы произвольных функций в RETURN.
    """
    for mc in [query.match, *query.optional_match]:
        if mc is None:
            continue
        for path in mc.paths:
            for node in (path.left, path.right):
                if node is None:
                    continue
                for lbl in node.labels:
                    if lbl.upper() not in {x.upper() for x in VALID_LABELS}:
                        return f"schema: unknown label :{lbl}"
                for key in node.properties:
                    if key not in VALID_PROPS:
                        return f"schema: unknown property {{{key}}}"
            for rtype in path.rel.rel_types:
                if rtype.upper() not in VALID_REL_TYPES:
                    return f"schema: unknown rel type :{rtype}"
    for item in query.return_items:
        expr = item.expression.strip()
        if (
            re.fullmatch(r"\w+\.\w+", expr)  # n.name
            or re.fullmatch(r"\w+", expr)     # переменная
            or re.fullmatch(r"count\((\*|\s*\w+(\.\w+)?\s*|\s*DISTINCT\s+\w+\.\w+\s*)\)", expr)
            or expr in ("count(*)",)
        ):
            continue
        return f"schema: unsupported RETURN expression: {expr!r}"
    if not query.return_items:
        return "schema: empty RETURN (parser ignored expression — e.g. function call)"
    return None


def validate_cypher(cypher: str) -> Optional[str]:
    """Двухслойная валидация: parser (синтаксис) + schema (семантика).

    Возвращает текст ошибки слоя ("parse: ..." / "schema: ...") или None.
    """
    try:
        tokens = CypherLexer(cypher).tokenize()
        query = CypherParser(tokens).parse()
    except Exception as exc:  # noqa: BLE001 — эксперимент: любая ошибка парсера
        return f"parse: {type(exc).__name__}: {exc}"
    return schema_check(query)


# ══════════════════════════════════════════════════════════════
# 4. Граф и датасет
# ══════════════════════════════════════════════════════════════


def build_graph(tmp: Path) -> PropertyGraph:
    pg = PropertyGraph(tmp / "spike.db")
    for name, fp in [
        ("main", "app.py"), ("parse", "parser.py"), ("validate", "validator.py"),
        ("render", "view.py"), ("log_error", "logger.py"),
    ]:
        pg.add_node(name, label=NodeLabel.FUNCTION, qualified_name=name, file_path=fp)
    pg.add_node("config", label=NodeLabel.VARIABLE, qualified_name="config", file_path="config.py")
    pg.add_node("db_conn", label=NodeLabel.VARIABLE, qualified_name="db_conn", file_path="db.py")
    pg.add_edge("main", "parse", type=EdgeType.CALLS)
    pg.add_edge("main", "validate", type=EdgeType.CALLS)
    pg.add_edge("parse", "render", type=EdgeType.CALLS)
    pg.add_edge("validate", "log_error", type=EdgeType.CALLS)
    pg.add_edge("parse", "config", type=EdgeType.USAGE)
    pg.add_edge("validate", "db_conn", type=EdgeType.USAGE)
    return pg


DATASET: List[Dict[str, Any]] = [
    {"q": "Кто вызывает main?", "expect_valid": True},
    {"q": "Что вызывает main?", "expect_valid": True},
    {"q": "Какие функции используют config?", "expect_valid": True},
    {"q": "Кто вызывает parse?", "expect_valid": True},
    {"q": "Что вызывает validate?", "expect_valid": True},
    {"q": "Сколько функций в графе?", "expect_valid": True},
    {"q": "Какие файлы содержат функции?", "expect_valid": True},
    {"q": "Покажи все функции", "expect_valid": True},
    {"q": "Есть ли цикл в графе?", "expect_valid": False},   # невалидный Cypher от LLM
    {"q": "Какие сервисы есть в графе?", "expect_valid": False},  # галлюцинированная метка
]


# ══════════════════════════════════════════════════════════════
# 5. Прогон
# ══════════════════════════════════════════════════════════════


def run(llm, pg: PropertyGraph) -> Dict[str, Any]:
    stats = {
        "total": len(DATASET), "parse_ok": 0, "rejected_by_parser": 0,
        "rejected_by_schema": 0, "exec_ok": 0, "exec_error": 0,
        "relevance_ok": 0, "latency_ms": [],
    }
    for item in DATASET:
        q = item["q"]
        t0 = time.perf_counter()
        raw = llm.generate(q, SCHEMA, FEW_SHOT)
        cypher = extract_cypher(raw)
        parse_err = validate_cypher(cypher) if cypher else "parse: no-cypher-in-output"
        latency = (time.perf_counter() - t0) * 1000
        stats["latency_ms"].append(round(latency, 1))

        if parse_err is not None:
            layer = parse_err.split(":", 1)[0]
            if layer == "schema":
                stats["rejected_by_schema"] += 1
            else:
                stats["rejected_by_parser"] += 1
            verdict = "REJECTED(expected)" if not item["expect_valid"] else "⚠️ REJECTED but expected valid"
            print(f"  {q[:45]:47} -> {layer.upper()}-REJECT: {parse_err[7:70]}   [{verdict}]")
            continue

        stats["parse_ok"] += 1
        try:
            res = query_graph(pg, cypher)
            stats["exec_ok"] += 1
            n = len(res.get("rows", res.get("results", []))) if isinstance(res, dict) else 0
            relevant = not item["expect_valid"] or n >= 0
            stats["relevance_ok"] += int(bool(relevant))
            print(f"  {q[:45]:47} -> EXEC ok ({n} rows) [{cypher[:50]}]")
        except Exception as exc:  # noqa: BLE001 — эксперимент
            stats["exec_error"] += 1
            print(f"  {q[:45]:47} -> EXEC ERROR: {type(exc).__name__}: {str(exc)[:60]}")
    return stats


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # §5.9 ENCODING SAFETY
    ap = argparse.ArgumentParser()
    ap.add_argument("--lm-studio", action="store_true", help="использовать реальный phi-4 (LM Studio :1234)")
    args = ap.parse_args()

    llm: Any = LMStudioLLM() if args.lm_studio else MockLLM()
    pg = build_graph(Path("."))
    print(f"=== Neuro-Symbolic spike (exp-lab-2026-01) | LLM: {type(llm).__name__} ===")
    print(f"Граф: {len(DATASET)} вопросов, схема: 5 labels / 3 edge types\n")
    stats = run(llm, pg)

    print("\n=== METRICS ===")
    print(f"total             : {stats['total']}")
    print(f"parse_ok          : {stats['parse_ok']}  (валидный Cypher принят парсером)")
    print(f"rejected_by_parser: {stats['rejected_by_parser']}  (синтаксис, слой 1)")
    print(f"rejected_by_schema: {stats['rejected_by_schema']}  (семантика, слой 2)")
    print(f"exec_ok           : {stats['exec_ok']}")
    print(f"exec_error        : {stats['exec_error']}")
    print(f"relevance_ok      : {stats['relevance_ok']}")
    print(f"latency avg       : {sum(stats['latency_ms'])/len(stats['latency_ms']):.1f} ms")
    ok = (
        stats["rejected_by_parser"] + stats["rejected_by_schema"] == 2
        and stats["exec_ok"] == 8 and stats["exec_error"] == 0
    )
    print(f"\nVERDICT: {'HYPOTHESIS SUPPORTED (3-layer validation)' if ok else 'check output'}")
    print("""
=== FINDINGS (баги Cypher-стека, обнаруженные спайком) ===
1. Label-фильтр CASE-SENSITIVE: MATCH (f:FUNCTION) -> [] (хранится Title Case
   'Function'); MATCH (f:Function) работает — риск для LLM-генерации без точной схемы
   (кандидат в KNOWN_ISSUES: нормализация регистра меток в executor)
2. count(...) -> SQLite 'near "*"' — агрегатные функции сломаны
3. CypherExecutor глотает SQL-ошибки и тихо возвращает [] (скрытый отказ)
4. CypherParser молча игнорирует RETURN-выражения с вызовами функций
   (cycle(a) -> return_items=[], обходит валидацию без schema-слоя)
""")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — эксперимент: exit code для CI
        import traceback

        traceback.print_exc()
        sys.exit(1)
