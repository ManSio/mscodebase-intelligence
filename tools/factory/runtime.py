"""Execution, the journal (append-only hash chain), and replay verification.

The journal is the only persistent state of the factory. Every primitive step
writes one line:

    {"seq","ts","node","op","args","status","sha256","artifact_sha256","digest","prev","hash"}

`hash = sha256(prev + canonical(entry without hash))`, so a broken chain is
detectable without trusting the writer. `verify` replays the chain, re-runs the
read-only operators and compares their `sha256`, and re-hashes every file a
`write` produced against `artifact_sha256`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ops import BY_NAME, OpError
from plan import Node, PlanError, flatten, resolve, walk

READ_ONLY_OPS = {"ls", "grep", "read", "outline", "git"}


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Budget:
    max_steps: int = 25
    max_tokens_est: int = 60_000
    max_wall_s: float = 900.0


def _digest(result: dict) -> str:
    for key in ("tail", "text", "hits", "entries", "symbols"):
        if key in result:
            value = result[key]
            return value[:300] if isinstance(value, str) else canonical(value)[:300]
    return canonical(result)[:300]


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev = "0" * 64
        self.seq = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.prev = rec["hash"]
                    self.seq = rec["seq"]

    def append(self, *, node: str, op: str, args: dict, status: str, result: dict | None,
               error: str | None, duration_ms: int) -> dict:
        self.seq += 1
        body = {
            "seq": self.seq,
            "ts": now_iso(),
            "node": node,
            "op": op,
            "args": args,
            "status": status,
            "sha256": sha(result) if result is not None else None,
            "artifact_sha256": (result or {}).get("sha256") if op == "write" else None,
            "digest": _digest(result) if result is not None else (error or "")[:300],
            "duration_ms": duration_ms,
            "prev": self.prev,
        }
        body["hash"] = hashlib.sha256((body["prev"] + canonical(body)).encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body, ensure_ascii=False) + "\n")
        self.prev = body["hash"]
        return body


def estimate_tokens(obj: dict) -> int:
    return max(1, len(canonical(obj)) // 4)


def run_plan(root: Node, repo: Path, journal_path: Path, budget: Budget | None = None,
             on_step=None, decider=None) -> dict:
    budget = budget or Budget()
    repo = repo.resolve()
    journal = Journal(journal_path)
    results: dict[str, dict] = {}
    brain_calls: list[dict] = []
    started = time.time()
    steps = 0
    tokens = 0
    status = "ok"
    failure: dict | None = None
    last_digest = ""

    for node in flatten(root):
        if steps >= budget.max_steps:
            status, failure = "budget", {"reason": f"max steps {budget.max_steps}"}
            break
        if tokens >= budget.max_tokens_est:
            status, failure = "budget", {"reason": f"max tokens ~{budget.max_tokens_est}"}
            break
        if time.time() - started > budget.max_wall_s:
            status, failure = "budget", {"reason": f"max wall {budget.max_wall_s}s"}
            break

        try:
            if decider is not None and (not node.args or node.args.get("__decide__") is True):
                node.args = dict(node.args)
                node.args.pop("__decide__", None)
                args, call = decider(node, last_digest)
                brain_calls.append(call.as_dict() if hasattr(call, "as_dict") else dict(call))
                if getattr(call, "error", None):
                    rec = journal.append(node=node.id, op=node.op or "?", args={}, status="error",
                                         result=None, error=f"brain: {call.error}", duration_ms=0)
                    status, failure = "failed", {"node": node.id, "error": rec["digest"]}
                    break
            else:
                args = resolve(node.args, results)
        except (PlanError, KeyError, IndexError, TypeError) as exc:
            rec = journal.append(node=node.id, op=node.op or "?", args=node.args, status="error",
                                 result=None, error=f"arg resolution: {exc}", duration_ms=0)
            status, failure = "failed", {"node": node.id, "error": rec["digest"]}
            break

        t0 = time.time()
        try:
            result = BY_NAME[node.op].fn(repo, args)
        except (OpError, OSError, subprocess.SubprocessError, ValueError) as exc:
            duration_ms = int((time.time() - t0) * 1000)
            rec = journal.append(node=node.id, op=node.op, args=args, status="error", result=None,
                                 error=f"{type(exc).__name__}: {exc}", duration_ms=duration_ms)
            status, failure = "failed", {"node": node.id, "error": rec["digest"]}
            break

        duration_ms = int((time.time() - t0) * 1000)
        rec = journal.append(node=node.id, op=node.op, args=args, status="ok", result=result,
                             error=None, duration_ms=duration_ms)
        results[node.id] = result
        last_digest = rec["digest"][:200]
        tokens += estimate_tokens(result)
        steps += 1
        if on_step:
            on_step(rec, result)

    return {
        "status": status,
        "steps": steps,
        "tokens_est": tokens,
        "wall_s": round(time.time() - started, 2),
        "journal": str(journal_path),
        "journal_hash": journal.prev,
        "failure": failure,
        "brain_calls": brain_calls,
        "results": results,
    }


def read_journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify(journal_path: Path, repo: Path, rerun_readonly: bool = True) -> dict:
    repo = repo.resolve()
    lines = read_journal(journal_path)
    if not lines:
        return {"verdict": "EMPTY", "reason": "journal is empty", "nodes": []}

    prev = "0" * 64
    chain_ok = True
    broken_at = None
    for rec in lines:
        body = {k: v for k, v in rec.items() if k != "hash"}
        expect = hashlib.sha256((prev + canonical(body)).encode("utf-8")).hexdigest()
        if rec.get("prev") != prev or rec.get("hash") != expect:
            chain_ok, broken_at = False, rec.get("seq")
            break
        prev = rec["hash"]

    nodes = []
    for rec in lines:
        item = {"seq": rec["seq"], "node": rec["node"], "op": rec["op"], "status": rec["status"],
                "verdict": "recorded", "detail": ""}
        if rec["status"] != "ok":
            item["verdict"] = "error-recorded"
            item["detail"] = str(rec.get("digest"))[:160]
            nodes.append(item)
            continue
        if rec["op"] in READ_ONLY_OPS:
            if not rerun_readonly:
                item["verdict"] = "recorded-only"
                nodes.append(item)
                continue
            try:
                fresh = BY_NAME[rec["op"]].fn(repo, rec["args"])
                item["verdict"] = "replayed-match" if sha(fresh) == rec["sha256"] else "replayed-MISMATCH"
                if item["verdict"] != "replayed-match":
                    item["detail"] = "world changed since the run, or the operator is not deterministic"
            except Exception as exc:  # noqa: BLE001
                item["verdict"] = "replay-error"
                item["detail"] = f"{type(exc).__name__}: {exc}"[:160]
        elif rec["op"] == "write":
            path = repo / str(rec["args"].get("path"))
            if not path.exists():
                item["verdict"] = "artifact-MISSING"
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                item["verdict"] = "artifact-match" if digest == rec.get("artifact_sha256") else "artifact-MISMATCH"
                item["detail"] = digest[:16]
        else:
            item["verdict"] = "side-effect-recorded"
        nodes.append(item)

    bad = [n for n in nodes if n["verdict"] in {"replayed-MISMATCH", "replay-error",
                                               "artifact-MISSING", "artifact-MISMATCH"}]
    return {"verdict": "PASS" if chain_ok and not bad else "FAIL", "chain_ok": chain_ok,
            "broken_at": broken_at, "records": len(lines), "last_hash": lines[-1]["hash"],
            "nodes": nodes}


def plan_preview(root: Node) -> list[str]:
    lines = []
    for node, depth in walk(root):
        pad = "  " * depth
        if node.kind == "primitive":
            lines.append(f"{pad}- {node.id} {node.op}({json.dumps(node.args, ensure_ascii=False)})")
        else:
            lines.append(f"{pad}+ {node.id} {node.goal[:80]}")
    return lines
