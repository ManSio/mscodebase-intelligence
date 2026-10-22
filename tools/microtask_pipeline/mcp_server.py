"""MCP wrapper: the whole pipeline as ONE tool for OpenCode.

OpenCode (cloud) calls `pipeline_run` once and gets a receipt list plus a short
summary; it never sees the microsteps, their observations, or the transcripts.

Protocol: MCP over stdio, line-delimited JSON-RPC, stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Executor, run_task  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RUNS = Path(
    os.environ.get("MSC_PIPELINE_RUNS", str(REPO / "tools" / "microtask_pipeline" / "runs"))
)


def make_pristine(repo: Path, dest: Path) -> Path:
    """A pristine copy of the tracked tree, taken before the run.

    The pipeline needs it for two things: restoring a tampered test file and
    telling "changed" from "not changed". `git archive HEAD` gives exactly the
    tracked files, without the working copies of other sessions.
    """
    if dest.exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    try:
        blob = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            timeout=300,
        ).stdout
        if blob:
            import io
            import tarfile

            with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
                tar.extractall(dest)
            return dest
    except (OSError, subprocess.SubprocessError):
        pass
    # fallback: copy the working tree
    import shutil

    shutil.copytree(repo, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    return dest


def respond(msg_id, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def tool_run(args: dict) -> dict:
    task = str(args.get("task", ""))
    repo = Path(str(args.get("repo", "."))).resolve()
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = RUNS / f"mcp-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    pristine = Path(str(args["pristine"])).resolve() if args.get("pristine") else make_pristine(
        repo, run_dir / "pristine"
    )
    pairs = None
    if args.get("test_files"):
        pairs = []
        for test_rel in args["test_files"]:
            src = args.get("source_file")
            pairs.append((str(src), str(test_rel)))
    executor = Executor()
    payload = run_task(task, repo, pristine, executor, pairs=pairs)
    payload["run_dir"] = str(run_dir)
    (run_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> int:
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
                    "serverInfo": {"name": "microtask-pipeline", "version": "0.2.0"},
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
                                "Run a coding task through the microtask pipeline: a code-built plan, "
                                "bounded one-tool microsteps (search / read / write), code "
                                "verification, and machine-checked receipts. Returns the receipts "
                                "and a short summary; the caller does not re-verify."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "task": {"type": "string", "description": "what must be done"},
                                    "repo": {"type": "string", "description": "repo root"},
                                    "pristine": {
                                        "type": "string",
                                        "description": "optional pristine copy; by default it is taken from git HEAD",
                                    },
                                    "test_files": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "scope: the test files this task must satisfy",
                                    },
                                    "source_file": {
                                        "type": "string",
                                        "description": "the production file to change (when test_files is given)",
                                    },
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
                payload = tool_run(args)
            except Exception as exc:  # noqa: BLE001
                payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            payload["wall_s"] = round(time.monotonic() - started, 2)
            respond(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)[:8000]}],
                    "isError": payload.get("status") == "error",
                },
            )
        elif msg_id is not None:
            respond(msg_id, {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
