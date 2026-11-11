"""Red-first tests for the installer's host-neutral CLI (G5/G6).

Every check drives `install.py` as a subprocess with isolated roots
(`MSCODEBASE_INSTALL_ROOT`, `MSCODEBASE_DATA_DIR`) so nothing touches the real
user profile. The snippets are not just parsed: the generic snippet's command is
actually launched and must answer an MCP `initialize` request.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL_PY = REPO / "install.py"

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
    elif client == "zed":
        command = [entry["command"], *entry["args"]]
        env = entry["env"]
        assert entry["enabled"] is True
    else:
        command = [entry["command"], *entry["args"]]
        env = entry["env"]

    assert command[0].endswith(("mscodebase-mcp.exe", "mscodebase-mcp", "python.exe", "python3"))
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


# ─── G6: --doctor ──────────────────────────────────────────────────────


def make_install_artifacts(install_root: Path, data_dir: Path, project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (install_root / "venv" / "Scripts").mkdir(parents=True)
    (install_root / "venv" / "Scripts" / "python.exe").write_bytes(b"x" * 100)
    (install_root / "src").mkdir()
    (install_root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (data_dir / "projects" / "deadbeef").mkdir(parents=True)
    (data_dir / "projects" / "deadbeef" / "graph.db").write_bytes(b"g" * 200)
    (data_dir / "logs").mkdir()
    (data_dir / "logs" / "server.log").write_text("line\n" * 5, encoding="utf-8")
    (project / ".mscodebase").mkdir()
    conn = sqlite3.connect(project / ".mscodebase" / "chunks.db")
    conn.execute("CREATE TABLE chunks (id TEXT, text TEXT)")
    conn.executemany("INSERT INTO chunks VALUES (?, ?)", [("1", "a"), ("2", "b"), ("3", "c")])
    conn.commit()
    conn.close()


def test_doctor_reports_layers_and_index(tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    make_install_artifacts(install_root, data_dir, project)

    proc = run_install(
        ["--doctor", "--json"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)

    layers = {layer["name"]: layer for layer in report["layers"]}
    assert layers["install_root"]["bytes"] > 0
    assert layers["data_root"]["bytes"] > 0
    assert layers["project_chunks"]["bytes"] > 0
    assert report["index"]["chunks"] == 3
    assert report["total_bytes"] >= 500


def test_doctor_human_output_has_paths(tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    make_install_artifacts(install_root, data_dir, project)

    proc = run_install(
        ["--doctor"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    assert str(install_root) in proc.stdout
    assert str(data_dir) in proc.stdout
    assert "chunks" in proc.stdout.lower()


# ─── G6: --clean ───────────────────────────────────────────────────────


def test_clean_dry_run_removes_nothing(tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    make_install_artifacts(install_root, data_dir, project)

    proc = run_install(
        ["--clean", "--dry-run"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert proc.returncode == 0, proc.stderr
    assert str(install_root) in proc.stdout
    assert str(data_dir) in proc.stdout
    assert install_root.exists() and data_dir.exists()
    assert (project / ".mscodebase" / "chunks.db").exists()


def test_clean_without_confirmation_refuses(tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    make_install_artifacts(install_root, data_dir, project)

    proc = run_install(
        ["--clean"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
        stdin_text="",
    )
    assert proc.returncode == 2
    assert "--yes" in (proc.stdout + proc.stderr)
    assert install_root.exists() and data_dir.exists()


def test_clean_yes_leaves_zero_residue(tmp_path):
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    make_install_artifacts(install_root, data_dir, project)

    proc = run_install(
        ["--clean", "--yes", "--json"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["removed_bytes"] > 0
    assert report["remaining_bytes"] == 0
    assert not install_root.exists()
    assert not (project / ".mscodebase").exists()
    assert not (data_dir / "projects").exists()

    after = run_install(
        ["--doctor", "--json"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
    )
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout)["total_bytes"] == 0


# ─── G6: models are opt-in (text-first default) ────────────────────────


def _install_module():
    spec = importlib.util.spec_from_file_location("mscodebase_install", INSTALL_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_models_are_opt_in():
    mod = _install_module()
    assert mod.models_enabled([]) is False
    assert mod.models_enabled(["--sync-only"]) is False
    assert mod.models_enabled(["--with-models"]) is True


def test_real_sync_install_then_doctor_then_clean_leaves_zero(tmp_path):
    """DoD G6: a real install (--sync-only), doctor sees it, clean leaves nothing."""
    install_root = tmp_path / "install"
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()

    install = run_install(
        ["--sync-only"],
        install_root=install_root,
        data_dir=data_dir,
        cwd=project,
        timeout=300,
    )
    assert install.returncode == 0, install.stderr
    assert (install_root / "install.py").is_file()
    assert (install_root / "src" / "main.py").is_file()

    doctor = run_install(["--doctor", "--json"], install_root=install_root, data_dir=data_dir, cwd=project)
    assert doctor.returncode == 0, doctor.stderr
    report = json.loads(doctor.stdout)
    layers = {layer["name"]: layer for layer in report["layers"]}
    assert layers["install_root"]["files"] > 100, layers["install_root"]
    assert report["total_bytes"] > 1_000_000

    clean = run_install(
        ["--clean", "--yes", "--json"], install_root=install_root, data_dir=data_dir, cwd=project
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean.stdout)["remaining_bytes"] == 0
    assert not install_root.exists()


@pytest.mark.parametrize("step_name", ["step_gguf", "step_models"])
def test_text_first_default_skips_downloads(step_name, monkeypatch):
    mod = _install_module()
    step = getattr(mod, step_name)

    def _boom(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("download attempted without --with-models")

    monkeypatch.setattr(mod.sys, "argv", ["install.py"])
    if step_name == "step_models":
        monkeypatch.setattr(mod, "_download_onnx_models", _boom, raising=False)

    lines: list[tuple[str, str]] = []
    step(lines, "en")
    joined = " ".join(text for _c, text in lines).lower()
    assert "skip" in joined, lines
    assert "--with-models" in joined, lines
