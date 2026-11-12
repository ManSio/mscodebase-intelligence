"""Red-first tests for the installer's host-neutral CLI (G5).

Every check drives `install.py` as a subprocess with isolated roots
(`MSCODEBASE_INSTALL_ROOT`, `MSCODEBASE_DATA_DIR`) so nothing touches the real
user profile. The snippets are not just parsed: the generic snippet's command is
actually launched and must answer an MCP `initialize` request.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL_PY = REPO / "install.py"


def _install_module():
    spec = importlib.util.spec_from_file_location("mscodebase_install", INSTALL_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SNIPPET_CLIENTS = ["generic", "opencode", "zed", "claude-code", "cursor"]

TOP_LEVEL_KEY = {
    "generic": "mcpServers",
    "claude-code": "mcpServers",
    "cursor": "mcpServers",
    "opencode": "mcp",
    "zed": "context_servers",
}


def _env(install_root: Path, data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MSCODEBASE_INSTALL_ROOT": str(install_root),
            "MSCODEBASE_DATA_DIR": str(data_dir),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return env


def run_install(
    args: list[str],
    *,
    install_root: Path,
    data_dir: Path,
    cwd: Path,
    stdin_text: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INSTALL_PY), *args],
        cwd=str(cwd),
        env=_env(install_root, data_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_text if stdin_text is not None else "",
        timeout=timeout,
    )


def entry_json(client: str, payload: dict) -> dict:
    if client == "opencode":
        # V2: mcp.servers.<name>
        return payload["mcp"]["servers"]["mscodebase"]
    return payload[TOP_LEVEL_KEY[client]]["mscodebase"]


# ─── G5: --print-config ────────────────────────────────────────────────


@pytest.mark.parametrize("client", SNIPPET_CLIENTS)
def test_print_config_is_valid_json_per_client(client, tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()

    proc = run_install(
        ["--print-config", "--client", client],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    entry = entry_json(client, payload)

    if client == "opencode":
        command = entry["command"]
        assert entry["type"] == "local"
        env = entry["environment"]
        assert "servers" in payload["mcp"], "OpenCode V2 keeps servers under mcp.servers"
    elif client == "zed":
        command = [entry["command"], *entry["args"]]
        env = entry["env"]
        assert entry["enabled"] is True
    else:
        command = [entry["command"], *entry["args"]]
        env = entry["env"]

    name = Path(command[0]).name
    assert name.startswith(("python", "mscodebase-mcp")), name
    assert command[1:] == ["-u", "-m", "src.main"]
    assert Path(env["PYTHONPATH"]).resolve() == install_root.resolve()
    assert env["PYTHONUTF8"] == "1"
    assert Path(env["PROJECT_PATH"]).resolve() == project.resolve()


def test_print_config_rejects_unknown_client(tmp_path):
    proc = run_install(
        ["--print-config", "--client", "not-a-client"],
        install_root=tmp_path / "install",
        data_dir=tmp_path / "data",
        cwd=tmp_path,
    )
    assert proc.returncode == 2
    assert "not-a-client" in (proc.stdout + proc.stderr)


def test_print_config_default_client_is_generic(tmp_path):
    proc = run_install(
        ["--print-config"],
        install_root=tmp_path / "install",
        data_dir=tmp_path / "data",
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert "mcpServers" in json.loads(proc.stdout)


def test_generic_snippet_actually_starts_the_server(tmp_path):
    """The printed snippet must be copy-paste launchable (real MCP handshake)."""
    project = tmp_path / "project"
    project.mkdir()

    proc = run_install(
        ["--print-config", "--client", "generic", "--python", sys.executable],
        install_root=REPO,
        data_dir=tmp_path / "data",
        cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    entry = entry_json("generic", json.loads(proc.stdout))

    env = os.environ.copy()
    env.update(entry["env"])
    env["MSCODEBASE_DATA_DIR"] = str(tmp_path / "data")

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "snippet-probe", "version": "0"},
        },
    }
    with subprocess.Popen(
        [entry["command"], *entry["args"]],
        cwd=str(project),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proc2:
        out, err = proc2.communicate(json.dumps(request) + "\n", timeout=300)

    answer = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("id") == 1:
                answer = candidate
                break
    assert answer is not None, textwrap.shorten(out + err, 800)
    assert answer["result"]["serverInfo"]["name"], answer


# ─── G5: --yes must run the steps, not skip all of them ────────────────


def test_auto_yes_runs_each_step_once(monkeypatch):
    """Regression: `range(0 if auto_yes else ...)` ran zero steps and marked all failed.

    Found by a clean-room install (2026-11-12): `install.py --yes` printed the
    summary box while creating nothing on disk.
    """
    mod = _install_module()
    calls: list[str] = []

    def _fake_step(lines, lang):
        calls.append("ran")

    monkeypatch.setattr(mod, "STEPS", [(0, "step_fake", _fake_step)])
    monkeypatch.setattr(mod.sys, "argv", ["install.py", "--yes"])
    monkeypatch.setattr(mod, "_enable_ansi", lambda: None)
    monkeypatch.setattr(mod, "_utf8_stdout", lambda: None)
    monkeypatch.setattr(mod, "_record_install_meta", lambda: None)
    monkeypatch.setattr(mod, "_box", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_line", lambda *a, **k: None)

    mod.main()

    assert calls == ["ran"], "auto-yes marked the step failed instead of running it"

