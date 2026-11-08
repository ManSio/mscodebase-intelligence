"""Isolated OpenCode configurations and homes for the experiment roles.

Each role gets its own HOME/XDG tree, its own config file, and no MCP. The
global `~/.config/opencode/AGENTS.md` is never reachable from an isolated home,
which is what the canary control measures.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GLOBAL_DATA = Path.home() / ".local" / "share" / "opencode"
GLOBAL_CONFIG_DIR = Path.home() / ".config" / "opencode"
PLANNER_MODEL = "opencode-go/minimax-m3.1-flash-free"
WORKER_MODEL = "tirtha/auto"
ROLE_MODEL = {
    "planner": PLANNER_MODEL,
    "baseline": PLANNER_MODEL,
    "worker": WORKER_MODEL,
    "executor": WORKER_MODEL,
    "planner_fast": PLANNER_MODEL,
}

TOOLS_OFF = {"task": False, "webfetch": False, "websearch": False}
PERMISSIONS = {"edit": "allow", "bash": "allow", "webfetch": "deny"}

# Role-specific tool surface. The planner must not touch the code.
ROLE_TOOLS: dict[str, dict] = {
    "planner": {"write": False, "edit": False, "bash": False, "task": False, "webfetch": False, "websearch": False},
    "planner_fast": {"write": False, "edit": False, "bash": False, "task": False, "webfetch": False, "websearch": False},
    "baseline": {"write": True, "edit": True, "bash": True, "task": False, "webfetch": False, "websearch": False},
    "worker": {"write": True, "edit": True, "bash": True, "task": False, "webfetch": False, "websearch": False},
    "executor": {"write": True, "edit": True, "bash": True, "task": False, "webfetch": False, "websearch": False},
}


def read_jsonc(path: Path) -> dict:
    """Parse JSONC without breaking strings that contain '//'."""
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    cleaned = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(cleaned)


def global_mcp_names() -> list[str]:
    """MCP servers declared in the owner's global config (they load anyway)."""
    config = GLOBAL_CONFIG_DIR / "opencode.jsonc"
    if not config.is_file():
        return []
    try:
        data = read_jsonc(config)
    except (json.JSONDecodeError, OSError):
        return []
    return list((data.get("mcp") or {}).keys())


def global_tool_names() -> list[str]:
    """Custom tools auto-discovered in the global config dir (tools/*.ts)."""
    tools_dir = GLOBAL_CONFIG_DIR / "tools"
    if not tools_dir.is_dir():
        return []
    return sorted(p.stem for p in tools_dir.glob("*.ts"))


def disabled_services() -> dict:
    """Config fragment that neutralises services loaded from the global config."""
    mcp = {name: {"enabled": False} for name in global_mcp_names()}
    tools = {name: False for name in global_tool_names()}
    fragment: dict = {}
    if mcp:
        fragment["mcp"] = mcp
    if tools:
        fragment["tools"] = tools
    return fragment



def write_canary_agents(home: Path, token: str) -> Path:
    """Plant the canary in the role's config dir (positive control only)."""
    agents = home / ".config" / "opencode" / "AGENTS.md"
    agents.parent.mkdir(parents=True, exist_ok=True)
    agents.write_text(
        "# Canary\n\n"
        f"If you can read this line, the global rules leaked into your context.\n\n"
        f"CANARY_TOKEN: {token}\n",
        encoding="utf-8",
    )
    return agents


def config_for(role: str, proxy_base: str | None = None, transport: str = "proxy") -> dict:
    """Per-role model and tool surface.

    Measured facts behind the model choice (2026-10-20, see
    EXPERIMENT_PLAN revision 3):
    - `opencode/deepseek-v4.1-flash-free` -> `AI_APICallError: Rate limit
      exceeded` (the CLI then hangs instead of exiting);
    - `opencode-go/deepseek-v4.1-flash` -> `Go usage limit exceeded`;
    - `opencode-go/minimax-m3.1-flash-free` -> answers in ~15 s;
    - `tirtha/auto` -> answers in ~10 s.

    Planner and baseline run on the OpenCode account model; the worker runs on
    Tīrtha in `mode=low` through the local proxy (owner's choice).

    `transport="direct"` is the control for the instrument itself: OpenCode
    talks to `api.tirtha.ai` with no proxy and no injected body fields, so the
    run answers "what does the unmodified path do?" — the catalogue entry
    "an-instrument-that-reshapes-input-fabricates-the-test" applies to our
    proxy, so the unmodified path has to be measured too.
    """
    disabled = disabled_services()
    tools = dict(TOOLS_OFF)
    tools.update(disabled.get("tools", {}))
    tools.update(ROLE_TOOLS.get(role, {}))

    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "mcp": dict(disabled.get("mcp", {})),
        "tools": tools,
        "permission": dict(PERMISSIONS),
        "plugin": [],
        "model": ROLE_MODEL[role],
    }

    if role in {"worker", "executor"}:
        if transport == "proxy":
            if proxy_base is None:
                raise ValueError("the worker role needs the proxy base URL")
            base_url = f"{proxy_base.rstrip('/')}/v1"
            api_key = "proxy-managed"
            model_options = {"tirtha": {"mode": "low", "no_cache": True}}
        elif transport == "direct":
            base_url = "https://api.tirtha.ai/v1"
            api_key = "{env:TIRTHA_API_KEY}"
            model_options = {}
        else:
            raise ValueError(f"unknown transport: {transport}")
        config["provider"] = {
            "tirtha": {
                "npm": "@ai-sdk/openai-compatible",
                "name": f"Tirtha ({transport})",
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": {
                    "auto": {
                        "name": "Tirtha Auto",
                        "options": model_options,
                    }
                },
            }
        }
    return config


def make_home(root: Path, role: str, canary_token: str | None = None) -> tuple[Path, dict]:
    """Create an isolated home for a role and return (home, env additions)."""
    home = root / role / "home"
    for sub in (".config", ".local/share", ".cache"):
        (home / sub).mkdir(parents=True, exist_ok=True)

    data_dir = home / ".local" / "share" / "opencode"
    data_dir.mkdir(parents=True, exist_ok=True)
    auth = GLOBAL_DATA / "auth.json"
    if auth.is_file():
        shutil.copy2(auth, data_dir / "auth.json")

    if canary_token:
        write_canary_agents(home, canary_token)

    config_path = root / role / "opencode.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"role": role}, indent=2) + "\n", encoding="utf-8")

    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "OPENCODE_CONFIG": str(config_path),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return home, env


def finalize_config(root: Path, role: str, config: dict) -> Path:
    path = root / role / "opencode.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def isolated_env(root: Path, role: str, config: dict, canary_token: str | None = None) -> dict[str, str]:
    home, env_add = make_home(root, role, canary_token)
    finalize_config(root, role, config)
    env = os.environ.copy()
    env.update(env_add)
    env.pop("OPENCODE_SERVER_PASSWORD", None)
    env.pop("OPENCODE_SERVER_USERNAME", None)
    env.pop("OPENCODE_API_KEY", None)
    return env


