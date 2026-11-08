"""The tree: plan schema, the gate, the rule-based brain, and arg resolution.

A plan is a tree of nodes. Compound nodes only group; primitive nodes name one
operator and its arguments. Arguments may reference an earlier node:

    {"op": "read", "args": {"path": "$t1.hits.0.file", "start": "$t1.hits.0.line"}}

The gate rejects: unknown operators, wrong argument names, dangling references,
forward references, duplicate ids, too many nodes. The brain never gets to skip
the gate — it is code, not a promise.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ops import BY_NAME

MAX_NODES = 40
MAX_DEPTH = 6


class PlanError(ValueError):
    pass


@dataclass
class Node:
    id: str
    kind: str                      # compound | primitive
    op: str | None = None
    args: dict = field(default_factory=dict)
    goal: str = ""
    children: list["Node"] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"id": self.id, "kind": self.kind}
        if self.goal:
            out["goal"] = self.goal
        if self.op:
            out["op"] = self.op
        if self.args:
            out["args"] = self.args
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


def from_dict(data: dict) -> Node:
    return Node(
        id=str(data.get("id")),
        kind=str(data.get("kind") or ("compound" if data.get("children") else "primitive")),
        op=data.get("op"),
        args=dict(data.get("args") or {}),
        goal=str(data.get("goal") or ""),
        children=[from_dict(c) for c in data.get("children") or []],
    )


def walk(node: Node, depth: int = 0):
    yield node, depth
    for child in node.children:
        yield from walk(child, depth + 1)


def flatten(root: Node) -> list[Node]:
    """Post-order: children before parents; only primitives are returned."""
    out: list[Node] = []
    for child in root.children:
        out.extend(flatten(child))
    if root.kind == "primitive":
        out.append(root)
    return out


_REF = re.compile(r"^\$([A-Za-z0-9_]+)\.(.+)$")


def references(args: dict) -> list[str]:
    refs: list[str] = []
    for value in args.values():
        if isinstance(value, str):
            m = _REF.match(value)
            if m:
                refs.append(m.group(1))
    return refs


def validate(root: Node) -> list[str]:
    errors: list[str] = []
    seen: dict[str, Node] = {}
    order: list[str] = []
    nodes = list(walk(root))
    if len(nodes) > MAX_NODES:
        errors.append(f"too many nodes: {len(nodes)} > {MAX_NODES}")
    for node, depth in nodes:
        if depth > MAX_DEPTH:
            errors.append(f"{node.id}: depth {depth} > {MAX_DEPTH}")
        if node.id in seen:
            errors.append(f"duplicate id: {node.id}")
        if node.kind not in {"compound", "primitive"}:
            errors.append(f"{node.id}: bad kind {node.kind!r}")
        if node.kind == "compound":
            if node.op:
                errors.append(f"{node.id}: compound node cannot have an operator")
            if not node.children:
                errors.append(f"{node.id}: compound node without children")
        else:
            if not node.op:
                errors.append(f"{node.id}: primitive node without an operator")
            elif node.op not in BY_NAME:
                errors.append(f"{node.id}: unknown operator {node.op!r}")
            else:
                spec = BY_NAME[node.op]
                extra = set(node.args) - set(spec.params)
                if extra:
                    errors.append(f"{node.id}: {node.op} got unknown args {sorted(extra)}")
                for ref in references(node.args):
                    if ref not in seen:
                        errors.append(f"{node.id}: reference to {ref} which is not an earlier node")
        seen[node.id] = node
        order.append(node.id)
    return errors


def resolve(args: dict, results: dict[str, dict]) -> dict:
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            m = _REF.match(value)
            if not m:
                out[key] = value
                continue
            node_id, dotted = m.group(1), m.group(2)
            if node_id not in results:
                raise PlanError(f"unresolved reference: {value}")
            cur: Any = results[node_id]
            for part in dotted.split("."):
                if isinstance(cur, list):
                    cur = cur[int(part)]
                elif isinstance(cur, dict):
                    cur = cur[part]
                else:
                    raise PlanError(f"cannot descend into {type(cur).__name__} at {part!r} of {value}")
            out[key] = cur
        else:
            out[key] = value
    return out


# ------------------------------------------------------------------ rule brain

_CLAUSE_SPLIT = re.compile(r"\s*(?:;|\.\s|\bзатем\b|\bпотом\b|\bthen\b|\band then\b)\s*", re.I)
_TEST_PATH = re.compile(r"(tests?/[\w./\\-]+\.py|[\w./\\-]+/test_[\w./\\-]+\.py|tests/[\w./\\-]+)")
_QUOTED = re.compile(r"[`\"']([^`\"']{2,80})[`\"']")
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")


def _first_symbol(clause: str) -> str | None:
    q = _QUOTED.search(clause)
    if q:
        return q.group(1)
    stop = {"найди", "найти", "где", "find", "search", "locate", "покажи", "show", "тест", "тесты",
            "test", "tests", "pytest", "запусти", "run", "файл", "file", "класс", "class", "функция",
            "function", "определён", "определен", "defined", "код", "code"}
    for m in _IDENT.finditer(clause):
        word = m.group(1)
        if word.lower() not in stop:
            return word
    return None


def rule_plan(task: str) -> Node:
    """Deterministic decomposition of the task text. No model involved."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(task) if c.strip()]
    children: list[Node] = []
    counter = 0

    def nid() -> str:
        nonlocal counter
        counter += 1
        return f"t{counter}"

    for clause in clauses:
        low = clause.lower()
        symbol = _first_symbol(clause)
        test_path = _TEST_PATH.search(clause)

        if any(w in low for w in ("тест", "test", "pytest")):
            target = test_path.group(1) if test_path else "tests/"
            node = Node(nid(), "primitive", "run", {"cmd": f"python -m pytest {target} -q"})
            children.append(node)
            continue

        if any(w in low for w in ("деплой", "deploy", "выкат", "release")):
            children.append(Node(nid(), "primitive", "deploy", {"script": "scripts/deploy.sh"}))
            continue

        if any(w in low for w in ("статус", "status", "что изменено", "diff")):
            children.append(Node(nid(), "primitive", "git", {"sub": "status"}))
            continue

        if any(w in low for w in ("найди", "найти", "где", "find", "search", "locate")) and symbol:
            grep_id = nid()
            children.append(Node(grep_id, "primitive", "grep", {"pattern": rf"\b{re.escape(symbol)}\b"}))
            children.append(Node(nid(), "primitive", "read",
                                 {"path": f"${grep_id}.hits.0.file", "start": f"${grep_id}.hits.0.line"}))
            continue

        if any(w in low for w in ("покажи", "show", "прочитай", "read")) and symbol:
            children.append(Node(nid(), "primitive", "grep", {"pattern": rf"\b{re.escape(symbol)}\b"}))
            continue

        if any(w in low for w in ("структур", "outline", "символ")) and symbol:
            children.append(Node(nid(), "primitive", "outline", {"path": symbol}))
            continue

        if symbol:
            children.append(Node(nid(), "primitive", "grep", {"pattern": rf"\b{re.escape(symbol)}\b"}))

    if not children:
        raise PlanError("the task text produced no steps; give an explicit action (find/test/show)")
    return Node("root", "compound", goal=task, children=children)


# ------------------------------------------------------------------- LLM brain

PLANNER_SYSTEM = """You decompose a coding task into a tree of primitive operator calls.
Return JSON only, shape:
{"root": {"id": "root", "kind": "compound", "goal": "...", "children": [
  {"id": "t1", "kind": "primitive", "op": "<name>", "args": {...}}
]}}
Rules:
- primitive nodes only call the operators listed below;
- an argument may reference an earlier node as "$t1.field" (e.g. "$t1.hits.0.file");
- no prose, no markdown fences, JSON only;
- prefer fewer nodes; each node must be one action.
Operators:
{catalogue}
"""


def llm_plan(task: str, endpoint: str, model: str, timeout: int = 120) -> Node:
    """Ask an OpenAI-compatible endpoint for a plan, then run the same gate."""
    import urllib.request

    from ops import catalogue_prompt

    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM.replace("{catalogue}", catalogue_prompt())},
            {"role": "user", "content": task},
        ],
    }
    req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise PlanError("the model did not return JSON")
    data = json.loads(text[start:end + 1])
    root = from_dict(data["root"] if "root" in data else data)
    errors = validate(root)
    if errors:
        raise PlanError("model plan rejected by the gate: " + "; ".join(errors))
    return root


def gate_summary(root: Node) -> dict:
    primitives = flatten(root)
    ops_used = sorted({n.op for n in primitives})
    shell = [n.args.get("cmd") for n in primitives if n.op == "run"]
    return {"nodes": len(list(walk(root))), "primitives": len(primitives), "ops": ops_used,
            "shell": shell, "errors": validate(root)}
