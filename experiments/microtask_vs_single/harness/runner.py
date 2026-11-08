"""Run one pilot cell: arm A (single session) or arm D (microtasks).

Every mechanical step is recorded; the LLM outcome is classified into the
pre-registered taxonomy from frozen/HYPOTHESES.md. The hidden tests are only
touched at evaluation time, never during the run.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from acp_client import AcpClient, AcpError, find_opencode
from brief_builder import build_brief
from config_factory import config_for, isolated_env
from proxy import Proxy, read_tirtha_key
from validate_plan import PlanError, validate

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
FROZEN = EXPERIMENT / "frozen"
REPO = FROZEN / "repo"
HIDDEN = FROZEN / "hidden"
RUNS = EXPERIMENT / "runs"

# Worktrees live OUTSIDE the repository: an AGENTS.md in an ancestor directory
# is injected into every session (measured: 7 270 input tokens with the repo
# rules in the chain, 4 480 without). The location is persistent (never %TEMP%)
# and configurable.
WORKTREE_ROOT = Path(
    os.environ.get(
        "MSC_MICROTASK_WORKTREE_ROOT",
        str(EXPERIMENT.parents[2] / "mscodebase-microtask-runs"),
    )
)

# Hidden tests are task-scoped: P1 must not be judged by P2's tests.
TASK_HIDDEN = {
    "P1_mean": ["test_p1_hidden.py", "test_regression.py"],
    "P2_money": ["test_p2_hidden.py", "test_regression.py"],
}

SESSION_TIMEOUT = 900.0
COMMAND_TIMEOUT = 300


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_prompt(name: str, canary: str) -> str:
    text = (FROZEN / "prompts" / name).read_text(encoding="utf-8")
    return text.replace("{{CANARY}}", canary)


def repo_listing(repo: Path) -> str:
    lines = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo).as_posix()
        if "__pycache__" in rel:
            continue
        lines.append(f"- {rel} ({path.stat().st_size} bytes)")
    return "\n".join(lines)


def parse_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from an agent answer."""
    text = text.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def changed_files(pristine: Path, worktree: Path) -> list[str]:
    changed: list[str] = []
    for path in sorted(worktree.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(worktree).as_posix()
        if "__pycache__" in rel or ".pytest_cache" in rel:
            continue
        original = pristine / rel
        if not original.is_file():
            changed.append(rel)
            continue
        if original.read_bytes() != path.read_bytes():
            changed.append(rel)
    return changed


def diff_text(pristine: Path, worktree: Path) -> str:
    chunks: list[str] = []
    for rel in changed_files(pristine, worktree):
        old = (pristine / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        new = (worktree / rel).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        chunks.append(
            "".join(
                difflib.unified_diff(
                    old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3
                )
            )
        )
    return "".join(chunks)


def run_command(cmd: str, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env or os.environ.copy(),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=COMMAND_TIMEOUT,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def is_test_path(rel: str) -> bool:
    low = rel.replace("\\", "/").lower()
    return low.startswith("tests/") or "/tests/" in low or low.startswith("test_")


class Cell:
    """One arm/task cell."""

    def __init__(self, arm: str, task_name: str, out_root: Path, transport: str = "proxy") -> None:
        self.arm = arm
        self.task_name = task_name
        self.transport = transport
        self.run_id = f"{arm}-{task_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.run_dir = out_root / self.run_id
        self.worktree = self.run_dir / "worktree"
        self.pristine = self.run_dir / "pristine"
        self.canary = "CANARY_" + secrets.token_hex(6).upper()
        self.timeline: list[dict] = []
        self.sessions: list[tuple[AcpClient, str, str]] = []
        self.proxy: Proxy | None = None
        self.result: dict = {
            "run_id": self.run_id,
            "arm": arm,
            "task": task_name,
            "started_at": now(),
            "outcome": "unknown",
            "canary_token_present": None,
        }

    def log(self, phase: str, detail: dict | None = None) -> None:
        self.timeline.append({"t": now(), "phase": phase, **(detail or {})})
        print(f"[{self.arm}/{self.task_name}] {phase} {detail or ''}", flush=True)

    def setup(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        tree_root = WORKTREE_ROOT / self.run_id
        tree_root.mkdir(parents=True, exist_ok=False)
        self.worktree = tree_root / "worktree"
        self.pristine = tree_root / "pristine"
        shutil.copytree(REPO, self.worktree)
        shutil.copytree(REPO, self.pristine)
        ancestors = agents_md_in_ancestors(self.worktree)
        self.result["agents_md_in_ancestors"] = ancestors
        self.log("worktree ready", {"path": str(self.worktree), "agents_md_ancestors": ancestors})

    def start_proxy(self) -> str:
        if self.proxy is None:
            self.proxy = Proxy("https://api.tirtha.ai", read_tirtha_key())
            self.proxy.__enter__()
            self.log("proxy started", {"base": self.proxy.base_url})
        return self.proxy.base_url

    def new_session(self, role: str, proxy_base: str | None = None, canary_home: bool = False) -> str:
        config = config_for(role, proxy_base, transport=self.transport)
        env = isolated_env(
            self.run_dir / "isolated",
            role,
            config,
            canary_token=self.canary if canary_home else None,
        )
        if role == "worker" and self.transport == "direct":
            env["TIRTHA_API_KEY"] = read_tirtha_key()
        client = AcpClient(self.binary, self.worktree, env)
        client.start(timeout=120)
        result = client.new_session(self.worktree, timeout=120)
        session_id = result.get("sessionId")
        if not session_id:
            raise AcpError(f"no sessionId for role {role}: {result}")
        self.sessions.append((client, session_id, role))
        self.log("session created", {"role": role, "session": session_id})
        return session_id

    def role_of_session(self, session_id: str) -> str:
        for client, sid, role in self.sessions:
            if sid == session_id:
                return role
        return "unknown"

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
        self.log("sessions cleaned", {"count": len(self.sessions)})

    def finish(self, outcome: str, extra: dict | None = None) -> dict:
        self.result["outcome"] = outcome
        self.result["finished_at"] = now()
        if extra:
            self.result.update(extra)
        (self.run_dir / "result.json").write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.run_dir / "timeline.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.timeline),
            encoding="utf-8",
        )
        (self.run_dir / "diff.patch").write_text(diff_text(self.pristine, self.worktree), encoding="utf-8")
        return self.result


def evaluate(cell: Cell) -> dict:
    """Task-scoped acceptance, public suite, hidden tests. Hidden only here.

    The verdict uses the hidden tests of THIS task plus the regression file.
    The full hidden suite is recorded as information only: P1 must not be
    judged by P2's tests (that mistake produced a wrong verdict in the first
    A/P1 attempt).

    Both pytest invocations use the SAME config file (`-c <worktree>/pytest.ini`):
    a control must travel the exact path the measurement travels. Before the
    fix, the public run picked the worktree's `pytest.ini` as rootdir while the
    hidden run silently fell back to the repository's `pyproject.toml`.
    """
    env = os.environ.copy()
    env["TARGET_REPO"] = str(cell.worktree)
    env["PYTHONPATH"] = str(cell.worktree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pytest_cfg = str(cell.worktree / "pytest.ini")
    scoped = [str(HIDDEN / name) for name in TASK_HIDDEN.get(cell.task_name, [])]
    public_rc, public_out = run_command(
        f'{sys.executable} -m pytest -c {pytest_cfg} tests -q -p no:cacheprovider', cell.worktree, env
    )
    scoped_rc, scoped_out = run_command(
        f'{sys.executable} -m pytest -c {pytest_cfg} {" ".join(scoped)} -q -p no:cacheprovider',
        cell.worktree,
        env,
    )
    all_rc, all_out = run_command(
        f'{sys.executable} -m pytest -c {pytest_cfg} {HIDDEN} -q -p no:cacheprovider', cell.worktree, env
    )
    (cell.run_dir / "test.log").write_text(
        f"=== public suite (rc={public_rc}) ===\n{public_out}\n"
        f"=== hidden scoped (rc={scoped_rc}) ===\n{scoped_out}\n"
        f"=== hidden full suite (rc={all_rc}, informational) ===\n{all_out}\n",
        encoding="utf-8",
    )
    return {
        "public_rc": public_rc,
        "public_output": public_out[-2000:],
        "hidden_scoped_files": scoped,
        "hidden_scoped_rc": scoped_rc,
        "hidden_scoped_output": scoped_out[-3000:],
        "hidden_full_rc": all_rc,
        "hidden_pass": scoped_rc == 0,
    }


def read_session_usage(cell: Cell, session_id: str) -> dict:
    """Token usage for one session, read from the isolated OpenCode database."""
    db = cell.run_dir / "isolated" / cell.role_of_session(session_id) / "home" / ".local" / "share" / "opencode" / "opencode.db"
    if not db.is_file():
        return {"measured": False, "reason": "no isolated database"}
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        rows = con.execute(
            "select data from message where session_id = ?", (session_id,)
        ).fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}

    totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    models: set[str] = set()
    requests = 0
    max_input = 0
    for (data,) in rows:
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if obj.get("role") != "assistant":
            continue
        requests += 1
        models.add(f"{obj.get('providerID')}/{obj.get('modelID')}")
        tokens = obj.get("tokens") or {}
        totals["input"] += int(tokens.get("input") or 0)
        totals["output"] += int(tokens.get("output") or 0)
        totals["reasoning"] += int(tokens.get("reasoning") or 0)
        cache = tokens.get("cache") or {}
        totals["cache_read"] += int(cache.get("read") or 0)
        totals["cache_write"] += int(cache.get("write") or 0)
        max_input = max(max_input, int(tokens.get("input") or 0) + int(cache.get("read") or 0))
    return {
        "measured": True,
        "source": str(db),
        "requests": requests,
        "models": sorted(models),
        "totals": totals,
        "max_input_with_cache": max_input,
    }


def agents_md_in_ancestors(path: Path) -> list[str]:
    """Every AGENTS.md that OpenCode could pick up by walking up from `path`.

    Deterministic instrument: OpenCode discovers AGENTS.md by directory walk,
    so a file in the worktree or in any ancestor is part of the agent's rules.
    """
    found: list[str] = []
    current = path.resolve()
    while True:
        candidate = current / "AGENTS.md"
        if candidate.is_file():
            found.append(str(candidate))
        if current.parent == current:
            break
        current = current.parent
    return found


def task_acceptance(task_text: str) -> str:
    match = re.search(r"```text\n(.+?)\n```", task_text, re.S)
    return match.group(1).strip() if match else ""


def allowed_files_for(task_text: str) -> list[str]:
    section = re.search(r"## Scope(.*?)## Acceptance", task_text, re.S)
    if not section:
        return []
    return re.findall(r"`([\w/.\-]+\.py)`", section.group(1))


def run_arm_a(cell: Cell) -> dict:
    task_text = (FROZEN / "tasks" / f"{cell.task_name}.md").read_text(encoding="utf-8")
    acceptance = task_acceptance(task_text)
    prompt = "\n\n".join(
        [
            read_prompt("baseline.md", cell.canary),
            "## Task\n\n" + task_text,
            "## Repository files\n\n" + repo_listing(cell.worktree),
            f"## Acceptance command\n\n```text\n{acceptance}\n```",
        ]
    )
    session_id = cell.new_session("baseline")
    client = cell.sessions[-1][0]
    answer = client.prompt(session_id, prompt, timeout=SESSION_TIMEOUT)
    (cell.run_dir / "agent_output.json").write_text(
        json.dumps(
            {
                "text": answer["text"],
                "tool_calls": answer["tool_calls"],
                "result": answer["result"],
                "permission_log": client.permission_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    payload = parse_json_object(answer["text"])
    if payload is None:
        cell.log("baseline answer is not JSON", {"text": answer["text"][:300]})
        return cell.finish(
            "infra_invalid_json",
            {"canary_seen": cell.canary in answer["text"], "usage": read_session_usage(cell, session_id)},
        )
    cell.log("baseline answered", {"status": payload.get("status")})
    rc, out = run_command(acceptance, cell.worktree)
    (cell.run_dir / "acceptance.log").write_text(out, encoding="utf-8")
    changed = changed_files(cell.pristine, cell.worktree)
    allowed = allowed_files_for(task_text)
    out_of_scope = [f for f in changed if f not in allowed]
    evaluation = evaluate(cell)
    outcome = "pass" if evaluation["hidden_pass"] else "fail_quality"
    if any(is_test_path(f) for f in changed) or out_of_scope:
        outcome = "invalid_scope"
    return cell.finish(
        outcome,
        {
            "canary_seen": cell.canary in answer["text"],
            "agent_payload": payload,
            "acceptance_rc": rc,
            "acceptance_output": out[-2000:],
            "changed_files": changed,
            "out_of_scope_files": out_of_scope,
            "evaluation": evaluation,
            "usage": read_session_usage(cell, session_id),
        },
    )


def run_arm_d(cell: Cell) -> dict:
    task_text = (FROZEN / "tasks" / f"{cell.task_name}.md").read_text(encoding="utf-8")

    proxy_base = cell.start_proxy() if cell.transport == "proxy" else None
    if cell.transport == "proxy":
        cell.log("proxy started", {"base": proxy_base})
    else:
        cell.log("transport: direct (no proxy, no injected fields)")

    planner_prompt = "\n\n".join(
        [
            read_prompt("planner.md", cell.canary),
            "## Task\n\n" + task_text,
            "## Repository files\n\n" + repo_listing(cell.worktree),
            "## Public tests\n\n```python\n"
            + (cell.worktree / "tests" / "test_public.py").read_text(encoding="utf-8")
            + "\n```",
        ]
    )
    planner_session = cell.new_session("planner")
    planner_client = cell.sessions[-1][0]
    planner_answer = planner_client.prompt(planner_session, planner_prompt, timeout=SESSION_TIMEOUT)
    plan_payload = parse_json_object(planner_answer["text"])
    if plan_payload is None:
        cell.log("planner answer is not JSON", {"text": planner_answer["text"][:300]})
        return cell.finish("infra_invalid_json", {"canary_seen": cell.canary in planner_answer["text"]})

    try:
        decision = validate(plan_payload)
    except PlanError as exc:
        cell.log("plan rejected", {"error": str(exc)})
        return cell.finish("invalid_plan", {"plan_error": str(exc), "plan_raw": plan_payload})
    cell.log("plan accepted", {"tasks": decision.get("tasks")})
    (cell.run_dir / "plan.json").write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    briefs_dir = cell.run_dir / "briefs"
    briefs_dir.mkdir(exist_ok=True)
    worker_outputs = cell.run_dir / "worker_outputs"
    worker_outputs.mkdir(exist_ok=True)

    order = _topological_order(plan_payload["tasks"])
    scope_violations: list[str] = []
    for task in order:
        brief = build_brief(task, cell.worktree)
        (briefs_dir / f"{task['id']}.md").write_text(brief.text, encoding="utf-8")
        cell.log("brief built", {"task": task["id"], "bytes": brief.size, "files": brief.files_read})

        before = set(changed_files(cell.pristine, cell.worktree))
        worker_prompt = read_prompt("worker.md", cell.canary) + "\n\n" + brief.text
        session_id = cell.new_session("worker", proxy_base=proxy_base)
        client = cell.sessions[-1][0]
        answer = client.prompt(session_id, worker_prompt, timeout=SESSION_TIMEOUT)
        payload = parse_json_object(answer["text"])
        (worker_outputs / f"{task['id']}.json").write_text(
            json.dumps(
                {
                    "task": task["id"],
                    "text": answer["text"],
                    "tool_calls": answer["tool_calls"],
                    "result": answer["result"],
                    "payload": payload,
                    "permission_log": client.permission_log,
                    "canary_seen": cell.canary in answer["text"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if payload is None:
            cell.log("worker answer is not JSON", {"task": task["id"]})
            return cell.finish(
                "infra_invalid_json",
                {"canary_seen": cell.canary in answer["text"], "failed_task": task["id"]},
            )
        cell.log("worker answered", {"task": task["id"], "status": payload.get("status")})

        after = set(changed_files(cell.pristine, cell.worktree))
        touched = sorted(after - before)
        allowed = [f.replace("\\", "/") for f in task["files"]]
        for rel in touched:
            if rel not in allowed:
                scope_violations.append(f"{task['id']}:{rel}")

        rc, out = run_command(task["acceptance"], cell.worktree)
        (cell.run_dir / f"acceptance_{task['id']}.log").write_text(out, encoding="utf-8")
        cell.log("acceptance", {"task": task["id"], "rc": rc, "touched": touched})
        if rc != 0:
            cell.log("acceptance failed for task", {"task": task["id"], "rc": rc})

    evaluation = evaluate(cell)
    changed = changed_files(cell.pristine, cell.worktree)
    outcome = "pass" if evaluation["hidden_pass"] else "fail_quality"
    if scope_violations or any(is_test_path(f) for f in changed):
        outcome = "invalid_scope"

    proxy_records = []
    if cell.proxy:
        proxy_records = cell.proxy.recorder.records
    return cell.finish(
        outcome,
        {
            "plan_tasks": [t["id"] for t in plan_payload["tasks"]],
            "scope_violations": scope_violations,
            "changed_files": changed,
            "evaluation": evaluation,
            "proxy_requests": len(proxy_records),
            "planner_usage": read_session_usage(cell, planner_session),
            "worker_usage": [
                {
                    "path": r.get("path"),
                    "model": r.get("model"),
                    "tirtha": r.get("tirtha"),
                    "usage": r.get("usage"),
                    "status": r.get("status"),
                }
                for r in proxy_records
            ],
        },
    )


def _topological_order(tasks: list[dict]) -> list[dict]:
    by_id = {t["id"]: t for t in tasks}
    order: list[dict] = []
    seen: set[str] = set()

    def visit(tid: str, stack: tuple[str, ...] = ()) -> None:
        if tid in seen:
            return
        if tid in stack:
            raise PlanError(f"cycle at {tid}")
        for dep in by_id[tid]["depends_on"]:
            visit(dep, stack + (tid,))
        seen.add(tid)
        order.append(by_id[tid])

    for task in tasks:
        visit(task["id"])
    return order


CANARY_PAD = (
    "\n".join(
        f"Rule line {i}: operators must verify every measurement before reporting a number."
        for i in range(1, 41)
    )
)


def _session_tokens(db: Path, session_id: str) -> int:
    if not db.is_file():
        return -1
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        row = con.execute(
            "select tokens_input from session where id = ?", (session_id,)
        ).fetchone()
        con.close()
    except Exception:  # noqa: BLE001
        return -1
    return int(row[0]) if row and row[0] is not None else -1


def _canary_variant(run_dir: Path, worktree: Path, with_agents: bool, token: str) -> dict:
    """One canary variant: same prompt, with or without a project AGENTS.md."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if with_agents:
        (worktree / "AGENTS.md").write_text(
            f"# Project rule\n\nCANARY_TOKEN: {token}\n\n{CANARY_PAD}\n", encoding="utf-8"
        )
    config = config_for("baseline")
    env = isolated_env(run_dir / "isolated", "baseline", config)
    binary = find_opencode()
    client = AcpClient(binary, worktree, env)
    answer_text = ""
    tokens = -1
    try:
        client.start(timeout=120)
        result = client.new_session(worktree, timeout=120)
        session_id = result["sessionId"]
        answer = client.prompt(
            session_id,
            "Do not use any tool. Reply with one JSON object: "
            '{"canary": "the exact string CANARY_... if it appears anywhere in your context, otherwise null"}. '
            "Report only what is in your context.",
            timeout=300,
        )
        answer_text = answer["text"]
        db = run_dir / "isolated" / "baseline" / "home" / ".local" / "share" / "opencode" / "opencode.db"
        tokens = _session_tokens(db, session_id)
    except AcpError as exc:
        answer_text = f"ERROR: {exc}"
    finally:
        client.stop()
    return {
        "with_agents": with_agents,
        "tokens_input": tokens,
        "model_reported_token": token in answer_text,
        "answer": answer_text[:1500],
    }


def run_canary_control(out_root: Path) -> dict:
    """Positive control for the isolation detector, measured by token delta.

    The model-side copy test proved unreliable (the model answered
    `{"canary": null}` even in the control). The deterministic instrument is the
    session's own `tokens_input`: a project `AGENTS.md` with a known pad must
    raise it. The control runs the same prompt twice — with and without the
    file — and the difference is the detector's calibration.
    """
    run_id = f"canary-control-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    token = "CANARY_" + secrets.token_hex(6).upper()

    variants = []
    for with_agents in (False, True):
        worktree = WORKTREE_ROOT / run_id / ("worktree_agents" if with_agents else "worktree_plain")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPO, worktree)
        variants.append(
            _canary_variant(
                run_dir / ("with" if with_agents else "without"),
                worktree,
                with_agents,
                token,
            )
        )

    plain = next(v for v in variants if not v["with_agents"])
    with_file = next(v for v in variants if v["with_agents"])
    delta = with_file["tokens_input"] - plain["tokens_input"]
    result = {
        "run_id": run_id,
        "token": token,
        "worktree_location": str(WORKTREE_ROOT),
        "variants": variants,
        "delta_tokens": delta,
        "detector_calibrated": delta > 50,
        "model_side_detector_fired": with_file["model_reported_token"],
    }
    (run_dir / "canary_control.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"CANARY CONTROL: plain={plain['tokens_input']} with_agents={with_file['tokens_input']} "
        f"delta={delta} calibrated={result['detector_calibrated']} "
        f"model_side_fired={result['model_side_detector_fired']}"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["A", "D"])
    parser.add_argument("--transport", choices=["proxy", "direct"], default="proxy")
    parser.add_argument("--task", default="P1_mean")
    parser.add_argument("--out", default=str(RUNS))
    parser.add_argument("--canary-control", action="store_true")
    args = parser.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.canary_control:
        result = run_canary_control(out_root)
        return 0 if result["detector_calibrated"] else 1

    if not args.arm:
        parser.error("--arm is required (or use --canary-control)")

    cell = Cell(args.arm, args.task, out_root, transport=args.transport)
    cell.result["transport"] = args.transport
    cell.binary = find_opencode()
    if not cell.binary:
        print("opencode binary not found")
        return 2
    try:
        cell.setup()
        result = run_arm_a(cell) if args.arm == "A" else run_arm_d(cell)
    except AcpError as exc:
        cell.finish("infra_provider_error", {"error": str(exc)})
        result = cell.result
    except subprocess.TimeoutExpired as exc:
        cell.finish("infra_timeout", {"error": str(exc)})
        result = cell.result
    finally:
        cell.cleanup()

    print(json.dumps({k: v for k, v in result.items() if k != "agent_payload"}, ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

