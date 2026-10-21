"""Main-run driver for the corpus (fix / no-op / block classes).

Arms, all on the SAME gateway and the SAME instrumentation:

* **A** — one Tīrtha session does the whole task.
* **C** — planner (Tīrtha, no write tools) + bounded Briefs + one-shot Tīrtha
  workers, one file each. Model-matched with A at the gateway level.
* **D-direct** — the same as C, but the worker talks to `api.tirtha.ai`
  directly: the control for our own proxy (an instrument that reshapes the
  input must not be the thing that produces the result).

The evaluation is the task's hidden check only; the agent never sees it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from acp_client import AcpClient, AcpError, find_opencode
from brief_builder import build_brief
from config_factory import config_for, isolated_env
from corpus_tasks import (
    answer_tokens,
    diff_text,
    hidden_verdict,
    list_tasks,
    load_task,
    parse_status,
    prepare,
    repo_listing,
)
from proxy import Proxy, read_tirtha_key
from validate_plan import PlanError, validate

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
RUNS = EXPERIMENT / "runs"
WORKTREE_ROOT = Path(
    __import__("os").environ.get(
        "MSC_MICROTASK_WORKTREE_ROOT", str(EXPERIMENT.parents[2] / "mscodebase-microtask-runs")
    )
)
SESSION_TIMEOUT = 900.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Cell:
    def __init__(self, arm: str, task_id: str, transport: str) -> None:
        self.arm = arm
        self.task_id = task_id
        self.transport = transport
        self.run_id = f"{arm}-{task_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.run_dir = RUNS / self.run_id
        self.tree_root = WORKTREE_ROOT / self.run_id
        self.worktree = self.tree_root / "worktree"
        self.sessions: list[tuple[AcpClient, str, str]] = []
        self.proxy: Proxy | None = None
        self.timeline: list[dict] = []
        self.result: dict = {
            "run_id": self.run_id,
            "arm": arm,
            "task": task_id,
            "transport": transport,
            "started_at": now(),
            "outcome": "unknown",
        }

    def log(self, phase: str, detail: dict | None = None) -> None:
        self.timeline.append({"t": now(), "phase": phase, **(detail or {})})
        print(f"[{self.arm}/{self.task_id}] {phase} {detail or ''}", flush=True)

    def setup(self, task) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.tree_root.mkdir(parents=True, exist_ok=False)
        prepare(task, self.worktree)
        self.log("snapshot ready", {"sha": task.snapshot_sha[:10], "class": task.cls})

    def start_proxy(self) -> str:
        if self.proxy is None:
            budget = float(os.environ.get("MSC_MICROTASK_COST_BUDGET", "0.15"))
            cap = int(os.environ.get("MSC_MICROTASK_REQ_BUDGET", "60"))
            self.proxy = Proxy(
                "https://api.tirtha.ai",
                read_tirtha_key(),
                budget_usd=budget,
                max_requests=cap,
            )
            self.proxy.__enter__()
            self.log("proxy started", {"base": self.proxy.base_url, "budget_usd": budget, "max_requests": cap})
        return self.proxy.base_url

    def new_session(self, role: str, proxy_base: str | None = None) -> str:
        config = config_for(role, proxy_base, transport=self.transport)
        env = isolated_env(self.run_dir / "isolated", role, config)
        if self.transport == "direct" and role in {"worker", "executor", "planner_fast"}:
            env["TIRTHA_API_KEY"] = read_tirtha_key()
        client = AcpClient(find_opencode(), self.worktree, env)
        client.start(timeout=120)
        result = client.new_session(self.worktree, timeout=120)
        session_id = result.get("sessionId")
        if not session_id:
            raise AcpError(f"no sessionId for {role}")
        self.sessions.append((client, session_id, role))
        self.log("session", {"role": role, "session": session_id})
        return session_id

    def cleanup(self) -> None:
        for client, session_id, _role in self.sessions:
            try:
                client.close_session(session_id, timeout=30)
            except AcpError:
                pass
            try:
                client.delete_session_cli(session_id, timeout=30)
            except Exception:  # noqa: BLE001
                pass
            client.stop()
        if self.proxy:
            self.proxy.dump(self.run_dir / "proxy_requests.jsonl")

    def finish(self, outcome: str, extra: dict | None = None) -> dict:
        self.result["outcome"] = outcome
        self.result["finished_at"] = now()
        if extra:
            self.result.update(extra)
        (self.run_dir / "result.json").write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.run_dir / "timeline.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.timeline), encoding="utf-8"
        )
        return self.result


EXECUTOR_PROMPT = """\
You are a single-session coding agent. You have the repository in your working directory.

Rules:
- Read the files you need.
- Edit production code only; do not edit test files.
- Run the test command exactly as given.
- Do not use MCP, web, or external agents.

Return one JSON object, no prose outside it:

{
  "status": "done|blocked|failed",
  "summary": "short factual summary",
  "files_changed": ["relative/path.py"],
  "tests": [{"cmd": "exact command", "exit": 0}],
  "diff": "unified diff or empty string",
  "assumptions": []
}
"""


def run_arm_a(cell: Cell, task) -> dict:
    proxy_base = cell.start_proxy()
    prompt = "\n\n".join(
        [
            EXECUTOR_PROMPT,
            "## Task\n\n" + task.text,
            "## Test command\n\n```text\n" + task.acceptance() + "\n```",
            "## Repository\n\n" + repo_listing(cell.worktree),
        ]
    )
    session_id = cell.new_session("executor", proxy_base=proxy_base)
    client = cell.sessions[-1][0]
    answer = client.prompt(session_id, prompt, timeout=SESSION_TIMEOUT)
    (cell.run_dir / "agent_output.json").write_text(
        json.dumps(
            {"text": answer["text"], "tool_calls": answer["tool_calls"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (cell.run_dir / "diff.patch").write_text(
        diff_text(cell.tree_root / "pristine", cell.worktree), encoding="utf-8"
    )
    answer_tokens_used = answer_tokens(answer["text"])
    status = parse_status(answer["text"])
    verdict = hidden_verdict(task, cell.worktree, status)
    proxy_records = cell.proxy.recorder.records if cell.proxy else []
    return cell.finish(
        verdict["verdict"],
        {
            "agent_status": status,
            "answer_tokens": answer_tokens_used,
            "answer_capped": answer_tokens_used >= 1000,
            "hidden": verdict,
            "proxy_requests": len(proxy_records),
            "served_by": sorted(
                {(r.get("tirtha") or {}).get("served_by") for r in proxy_records if r.get("tirtha")}
            ),
            "prompt_tokens_max": max(
                [(r.get("usage") or {}).get("prompt_tokens") or 0 for r in proxy_records] or [0]
            ),
            "total_tokens": sum(
                [(r.get("usage") or {}).get("total_tokens") or 0 for r in proxy_records]
            ),
        },
    )


def run_arm_c(cell: Cell, task) -> dict:
    proxy_base = cell.start_proxy() if cell.transport == "proxy" else None
    planner_prompt = "\n\n".join(
        [
            (FROZEN_PROMPTS / "planner.md").read_text(encoding="utf-8").replace("{{CANARY}}", "none"),
            "## Task\n\n" + task.text,
            "## Test command (use exactly this in `acceptance`)\n\n```text\n"
            + task.acceptance()
            + "\n```",
            "## Repository\n\n" + repo_listing(cell.worktree),
        ]
    )
    planner_session = cell.new_session("planner_fast", proxy_base=proxy_base)
    planner_client = cell.sessions[-1][0]
    planner_answer = planner_client.prompt(planner_session, planner_prompt, timeout=SESSION_TIMEOUT)
    planner_usage = session_tokens(cell.run_dir, "planner_fast", planner_session)
    plan_payload = None
    rejection = ""
    attempts = 0
    while attempts < 2 and plan_payload is None:
        attempts += 1
        prompt = "\n\n".join(
            [
                (FROZEN_PROMPTS / "planner.md")
                .read_text(encoding="utf-8")
                .replace("{{CANARY}}", "none"),
                "## Task\n\n" + task.text,
                "## Test command (use exactly this in `acceptance`)\n\n```text\n"
                + task.acceptance()
                + "\n```",
                "## Repository\n\n" + repo_listing(cell.worktree),
            ]
        )
        if rejection:
            prompt += (
                "\n\n## Your previous plan was rejected by the plan gate\n\n"
                f"Reason: {rejection}\n\n"
                "Produce a corrected plan. Each file may be written by exactly one task; "
                "if two changes belong to the same file, they belong to one task."
            )
        planner_session = cell.new_session("planner_fast", proxy_base=proxy_base)
        planner_client = cell.sessions[-1][0]
        planner_answer = planner_client.prompt(planner_session, prompt, timeout=SESSION_TIMEOUT)
        planner_usage = session_tokens(cell.run_dir, "planner_fast", planner_session)
        plan_payload = _parse_json(planner_answer["text"])
        if plan_payload is None:
            rejection = "the answer was not a JSON object"
            continue
        try:
            decision = validate(plan_payload)
        except PlanError as exc:
            rejection = str(exc)
            plan_payload = None
            continue
        if decision.get("mode") != "microtasks" or not decision.get("tasks"):
            rejection = "the plan was empty or a fallback; return at least one task"
            plan_payload = None
    if plan_payload is None:
        # Deterministic fallback: if the planner cannot produce a plan the gate
        # accepts, the harness builds the minimal valid one (one task, the file
        # named in the task, the task's acceptance command) and records that it
        # did so. The arm then measures the WORKER, not the planner's
        # formatting — and the substitution is visible in the artifacts.
        plan_payload = {
            "tasks": [
                {
                    "id": "T1",
                    "goal": task.text.splitlines()[0][:200],
                    "symbol": task.src_file or "unknown",
                    "files": [task.src_file] if task.src_file else [],
                    "depends_on": [],
                    "acceptance": task.acceptance(),
                    "max_steps": 4,
                }
            ],
            "plan_source": "deterministic_fallback",
        }
        cell.log("plan fallback", {"reason": rejection})
    else:
        plan_payload["plan_source"] = "planner"
    try:
        decision = validate(plan_payload)
    except PlanError as exc:
        return cell.finish("invalid_plan", {"plan_error": str(exc), "plan_attempts": attempts})
    if decision.get("mode") != "microtasks" or not decision.get("tasks"):
        return cell.finish("invalid_plan", {"plan_error": "no usable plan", "plan_attempts": attempts})
    cell.log("plan", {"tasks": decision.get("tasks"), "attempts": attempts})
    (cell.run_dir / "plan.json").write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    briefs_dir = cell.run_dir / "briefs"
    briefs_dir.mkdir(exist_ok=True)
    outputs_dir = cell.run_dir / "worker_outputs"
    outputs_dir.mkdir(exist_ok=True)
    statuses = []
    for planned in plan_payload.get("tasks", []):
        brief = build_brief(planned, cell.worktree)
        (briefs_dir / f"{planned['id']}.md").write_text(brief.text, encoding="utf-8")
        prompt = (
            (FROZEN_PROMPTS / "worker.md").read_text(encoding="utf-8").replace("{{CANARY}}", "none")
            + "\n\n"
            + brief.text
        )
        session_id = cell.new_session("executor", proxy_base=proxy_base)
        client = cell.sessions[-1][0]
        budget = int(planned.get("max_steps", 4)) * 3
        exhausted = {"hit": False}

        def watchdog() -> None:
            """Bound the worker: cancel it when it exceeds its step budget.

            The microtask contract promises a bounded worker; without a
            watchdog the promise is only a word in a prompt (observed: the
            worker retried an unrunnable acceptance command for 15 minutes).
            The baseline arm is deliberately NOT bounded — its runaway is the
            thing we are measuring.
            """
            while not exhausted["hit"]:
                time.sleep(2)
                try:
                    if client.tool_call_count() > budget:
                        exhausted["hit"] = True
                        client.cancel(session_id)
                        return
                except Exception:  # noqa: BLE001
                    return

        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        answer = client.prompt(session_id, prompt, timeout=SESSION_TIMEOUT)
        watcher.join(timeout=5)
        if exhausted["hit"]:
            cell.log("worker budget exhausted", {"task": planned["id"], "budget": budget})
        (outputs_dir / f"{planned['id']}.json").write_text(
            json.dumps(
                {
                    "text": answer["text"],
                    "tool_calls": answer["tool_calls"],
                    "budget_exhausted": exhausted["hit"],
                },
                ensure_ascii=False,
                indent=2,
            ), encoding="utf-8")
        statuses.append(parse_status(answer["text"]))
    status = "done" if all(s == "done" for s in statuses) else (statuses[0] if statuses else "none")
    verdict = hidden_verdict(task, cell.worktree, status)
    (cell.run_dir / "diff.patch").write_text(
        diff_text(cell.tree_root / "pristine", cell.worktree), encoding="utf-8"
    )
    proxy_records = cell.proxy.recorder.records if cell.proxy else []
    return cell.finish(
        verdict["verdict"],
        {
            "agent_status": status,
            "answer_tokens": answer_tokens(answer["text"]),
            "worker_statuses": statuses,
            "hidden": verdict,
            "plan_tasks": [t["id"] for t in plan_payload.get("tasks", [])],
            "planner_usage": planner_usage,
            "proxy_requests": len(proxy_records),
            "served_by": sorted(
                {(r.get("tirtha") or {}).get("served_by") for r in proxy_records if r.get("tirtha")}
            ),
            "prompt_tokens_max": max(
                [(r.get("usage") or {}).get("prompt_tokens") or 0 for r in proxy_records] or [0]
            ),
            "total_tokens": sum(
                [(r.get("usage") or {}).get("total_tokens") or 0 for r in proxy_records]
            ),
        },
    )


FROZEN_PROMPTS = EXPERIMENT / "frozen" / "prompts"


def _parse_json(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def session_tokens(run_dir: Path, role: str, session_id: str) -> dict:
    """Token usage of a non-Tīrtha session (planner), read from its own DB."""
    db = (
        run_dir
        / "isolated"
        / role
        / "home"
        / ".local"
        / "share"
        / "opencode"
        / "opencode.db"
    )
    if not db.is_file():
        return {"measured": False}
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        row = con.execute(
            "select tokens_input, tokens_output, tokens_reasoning from session where id = ?",
            (session_id,),
        ).fetchone()
        con.close()
    except Exception:  # noqa: BLE001
        return {"measured": False}
    if not row:
        return {"measured": False}
    return {
        "measured": True,
        "input": row[0] or 0,
        "output": row[1] or 0,
        "reasoning": row[2] or 0,
        "total": (row[0] or 0) + (row[1] or 0) + (row[2] or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="corpus task id (see --list)")
    parser.add_argument("--arm", choices=["A", "C", "D-direct"], required=True)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for task_id in list_tasks():
            print(task_id)
        return 0

    task = load_task(args.task)
    transport = "direct" if args.arm == "D-direct" else "proxy"
    cell = Cell(args.arm, args.task, transport)
    try:
        cell.setup(task)
        result = run_arm_a(cell, task) if args.arm == "A" else run_arm_c(cell, task)
    except AcpError as exc:
        result = cell.finish("infra_provider_error", {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        import traceback

        result = cell.finish(
            "infra_error",
            {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1500:]},
        )
    finally:
        cell.cleanup()
    summary = {
        "run_id": result.get("run_id"),
        "outcome": result.get("outcome"),
        "agent_status": result.get("agent_status"),
        "hidden": (result.get("hidden") or {}).get("verdict"),
        "requests": result.get("proxy_requests"),
        "total_tokens": result.get("total_tokens"),
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



