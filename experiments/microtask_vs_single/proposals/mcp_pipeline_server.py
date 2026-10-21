"""Pipeline as ONE MCP tool for OpenCode (stdlib only, no service, no account).

OpenCode (cloud) calls a single tool:

    pipeline_run({"task": "...", "repo": "D:/path/to/repo"})

and gets back a **receipt** plus a short summary. It never sees the workers,
their briefs, their artifacts or their transcripts — that is the point.

The pipeline itself is deterministic code (plan → gate → brief → executor loop
→ code verifier → receipt); only the executor loop calls a model, and it does
so with a minimal prompt and ONE tool schema, which is what makes a 2k–8k
context budget possible at all (an OpenCode session's own floor is ≈4.5k
tokens; ours is ≈1.5k).

Protocol: MCP over stdio, line-delimited JSON-RPC. Implemented directly to
keep the dependency count at zero.

Executor backends (env var MSC_EXECUTOR):
    * ``lmstudio`` — our own LM Studio server (default http://192.168.2.5:1234/v1,
      the OpenAI-compatible endpoint; the native /api/v1/chat does NOT support
      custom tools, so we use /v1/chat/completions)
    * ``llama``    — a plain llama.cpp server, same wire format
    * ``tirtha``   — Tīrtha gateway, mode=low, no_cache, via MSC_TIRTHA_BASE
    * ``fake``     — offline stub, for tests (no network, no model)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- constants

MAX_STEPS = 3
MAX_TOKENS = 2048
CONTEXT_BUDGET = 8192
BRIEF_BUDGET_BYTES = 4000
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write the complete new content of one file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file path relative to the repo root"},
                "content": {"type": "string", "description": "the full new content of the file"},
            },
            "required": ["path", "content"],
        },
    },
}


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- executor


@dataclass
class Executor:
    """One model call with ONE tool; the loop is ours, not the runtime's."""

    backend: str = field(default_factory=lambda: os.environ.get("MSC_EXECUTOR", "fake"))
    model: str = field(
        default_factory=lambda: os.environ.get(
            "MSC_EXECUTOR_MODEL", "google/gemma-4-26b-a4b-qat"
        )
    )
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "MSC_EXECUTOR_BASE", "http://192.168.2.5:1234/v1"
        )
    )
    calls: int = 0

    def complete(self, messages: list[dict], tools: list[dict] | None) -> dict:
        self.calls += 1
        if self.backend == "fake":
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {"status": "done", "summary": "fake executor", "files_changed": []}
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        body: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }
        if tools:
            body["tools"] = tools
        if self.backend == "tirtha":
            body["tirtha"] = {"mode": "low", "no_cache": True}
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        key = os.environ.get("MSC_EXECUTOR_KEY")
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- pipeline


@dataclass
class Microtask:
    id: str
    file: str
    goal: str
    acceptance: str


@dataclass
class Receipt:
    receipt_id: str
    microtask: str
    artifact: str
    artifact_sha256: str
    verify: dict
    scope_ok: bool
    status: str
    cost: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "receipt_id": self.receipt_id,
            "microtask": self.microtask,
            "artifact": self.artifact,
            "artifact_sha256": self.artifact_sha256,
            "verify": self.verify,
            "scope_ok": self.scope_ok,
            "status": self.status,
            "cost": self.cost,
        }


def plan(task: str, repo: Path) -> list[Microtask]:
    """Deterministic planning: one microtask per candidate file, in order.

    A model planner can replace this later; the gate below is what enforces the
    shape, so the orchestrator's plan can never exceed one file per step.
    """
    tests = sorted(p for p in (repo / "tests").glob("test_*.py")) if (repo / "tests").is_dir() else []
    modules = sorted(p for p in (repo / "src").rglob("*.py")) if (repo / "src").is_dir() else []
    steps: list[Microtask] = []
    for index, test in enumerate(tests[:6], start=1):
        steps.append(
            Microtask(
                id=f"T{index}",
                file=test.relative_to(repo).as_posix(),
                goal=f"Make the failing test(s) in {test.name} pass. {task}",
                acceptance=f"python -m pytest {test.relative_to(repo).as_posix()} -q",
            )
        )
    if not steps and modules:
        steps.append(
            Microtask(
                id="T1",
                file=modules[0].relative_to(repo).as_posix(),
                goal=task,
                acceptance="",
            )
        )
    return steps


def gate(steps: list[Microtask]) -> tuple[bool, list[str]]:
    """The code gate: one file per step, no duplicates, no tests edited."""
    problems: list[str] = []
    seen: set[str] = set()
    for step in steps:
        if step.file in seen:
            problems.append(f"{step.id}: file {step.file} has two writers")
        seen.add(step.file)
        if step.file.startswith("tests/") or step.file.startswith("test_"):
            problems.append(f"{step.id}: test files are not editable")
        if not step.goal.strip():
            problems.append(f"{step.id}: empty goal")
    if len(steps) > 8:
        problems.append(f"too many microtasks: {len(steps)}")
    return (not problems), problems


def build_brief(step: Microtask, repo: Path) -> str:
    path = repo / step.file
    content = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if len(content.encode("utf-8")) > BRIEF_BUDGET_BYTES:
        content = content[:BRIEF_BUDGET_BYTES] + "\n# [truncated]\n"
    brief = (
        f"# Task {step.id}\n\n"
        f"## Goal\n\n{step.goal}\n\n"
        f"## File to edit (the only one)\n\n`{step.file}`\n\n"
        f"## Current content\n\n```\n{content}\n```\n\n"
        f"## Acceptance\n\n```text\n{step.acceptance}\n```\n\n"
        "## Answer\n\n"
        'One JSON object, <=150 words, no diff and no file content: '
        '{"status": "done|blocked|failed", "summary": "<=20 words", '
        '"files_changed": ["..."], "assumptions": []}\n'
    )
    return brief


def run_executor(executor: Executor, brief: str, repo: Path, step: Microtask) -> dict:
    """Our loop: model → (maybe write_file) → model → receipt."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a one-shot micro-worker. You may call write_file at most "
                f"{MAX_STEPS} times and only for `{step.file}`. Then answer with a "
                "short JSON receipt."
            ),
        },
        {"role": "user", "content": brief},
    ]
    written: list[str] = []
    status = "failed"
    summary = ""
    for _ in range(MAX_STEPS):
        response = executor.complete(messages, [TOOL_SCHEMA])
        message = (response.get("choices") or [{}])[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            text = message.get("content") or ""
            if not text:
                # A reasoning model may answer only in `reasoning_content`;
                # that is not a receipt, so we treat it as an unusable answer
                # rather than silently accepting prose.
                reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
                text = reasoning
                status = "unparsed"
                summary = text[:200]
                break
            try:
                payload = json.loads(text)
                status = str(payload.get("status", "failed"))
                summary = str(payload.get("summary", ""))[:200]
            except json.JSONDecodeError:
                status = "unparsed"
                summary = text[:200]
            break
        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name")
            if name != "write_file":
                continue
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            target = (repo / str(args.get("path", ""))).resolve()
            if not str(target).startswith(str(repo.resolve())):
                log(f"refused write outside the repo: {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(args.get("content", "")), encoding="utf-8")
            written.append(target.relative_to(repo).as_posix())
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.get("id", "c1"),
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": function.get("arguments", "{}"),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", "c1"),
                    "content": f"written: {written[-1]}",
                }
            )
    return {"status": status, "summary": summary, "files_changed": written}


def verify(step: Microtask, repo: Path) -> dict:
    if not step.acceptance:
        return {"cmd": "", "exit": 0, "skipped": True}
    import subprocess

    proc = subprocess.run(
        step.acceptance,
        cwd=str(repo),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    return {"cmd": step.acceptance, "exit": proc.returncode, "tail": (proc.stdout or "")[-400:]}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def execute(task: str, repo_path: str, executor: Executor) -> dict:
    repo = Path(repo_path).resolve()
    steps = plan(task, repo)
    ok, problems = gate(steps)
    if not ok:
        return {"status": "invalid_plan", "problems": problems}
    receipts = []
    for step in steps:
        brief = build_brief(step, repo)
        result = run_executor(executor, brief, repo, step)
        check = verify(step, repo)
        artifact = repo / step.file
        receipts.append(
            Receipt(
                receipt_id=f"r-{hashlib.sha256((step.id + step.file).encode()).hexdigest()[:8]}",
                microtask=step.id,
                artifact=step.file,
                artifact_sha256=sha256_of(artifact),
                verify=check,
                scope_ok=all(f in {step.file} for f in result.get("files_changed", [])),
                status=result.get("status", "failed"),
            ).to_json()
        )
    passed = all(r["verify"].get("exit") == 0 for r in receipts) and all(
        r["scope_ok"] for r in receipts
    )
    return {
        "status": "done" if passed else "failed",
        "receipts": receipts,
        "summary": " | ".join(f"{r['microtask']}:{r['status']}" for r in receipts),
        "executor_calls": executor.calls,
    }


# ---------------------------------------------------------------- MCP glue


def respond(msg_id, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> int:
    executor = Executor()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            respond(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "microtask-pipeline", "version": "0.1.0"},
                },
            )
        elif method == "tools/list":
            respond(
                msg_id,
                {
                    "tools": [
                        {
                            "name": "pipeline_run",
                            "description": (
                                "Run a task through the microtask pipeline: plan, gate, "
                                "bounded briefs, one-shot workers, code verification. "
                                "Returns a receipt list and a short summary."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "task": {"type": "string"},
                                    "repo": {"type": "string"},
                                },
                                "required": ["task", "repo"],
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            started = time.monotonic()
            try:
                payload = execute(
                    str(args.get("task", "")), str(args.get("repo", ".")), executor
                )
            except Exception as exc:  # noqa: BLE001
                payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            payload["wall_s"] = round(time.monotonic() - started, 2)
            respond(
                msg_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, ensure_ascii=False)[:6000]}
                    ],
                    "isError": payload.get("status") in {"error", "invalid_plan"},
                },
            )
        elif msg_id is not None:
            respond(msg_id, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

