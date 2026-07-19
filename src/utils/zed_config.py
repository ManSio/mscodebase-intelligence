"""
Automatic Zed IDE configuration for MSCodeBase Intelligence.

Configures the MCP context server in Zed's settings.json across
Windows / macOS / Linux WITHOUT destroying existing user settings or
JSONC comments.

Key safety properties:
  - Only the `context_servers` and `context_servers_to_query` keys are ever
    touched. All other settings, other MCP servers and user env vars are
    preserved (merge, never replace).
  - Zed's settings.json is JSONC (// and /* */ comments, trailing commas).
    We parse it tolerantly and, on any parse error, ABORT rather than wipe
    the file.
  - When writing, we perform targeted text surgery on just the two keys we
    manage, so JSONC comments and formatting elsewhere stay byte-for-byte.

Extension install location (for reference, NOT the config dir):
  Windows : %LOCALAPPDATA%/Zed/extensions/mscodebase-intelligence
  macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
  Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Имя сервера в настройках Zed (единое для всех платформ)
SERVER_NAME = "mscodebase-intelligence"


# ─────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────

def get_zed_config_dir() -> Path:
    """Return Zed's settings directory for the current OS.

    Windows : %APPDATA%/Zed
    macOS   : ~/Library/Application Support/Zed  (fallback ~/.config/zed, ~/.zed)
    Linux   : $XDG_CONFIG_HOME/zed  (fallback ~/.config/zed)
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Zed"
        return Path.home() / "AppData" / "Roaming" / "Zed"

    if sys.platform == "darwin":
        # Zed 2.x primary location
        primary = Path.home() / "Library" / "Application Support" / "Zed"
        if primary.exists():
            return primary
        config = Path.home() / ".config" / "zed"
        if config.exists():
            return config
        legacy = Path.home() / ".zed"
        if legacy.exists():
            return legacy
        return primary  # default (will be created if needed)

    # Linux / other
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "zed"
    return Path.home() / ".config" / "zed"


def get_extension_install_dir() -> Path:
    """Directory of the installed extension (contains venv/ and src/).

    Works both from the installed extension and from the dev tree
    (PROJECT_ROOT/src/utils/zed_config.py) — both resolve 3 levels up.
    """
    return Path(__file__).resolve().parent.parent.parent


def get_python_path() -> Path:
    """Path to the extension's venv Python interpreter (fallback: sys.executable)."""
    venv = get_extension_install_dir() / "venv"
    python = (
        venv / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else venv / "bin" / "python3"
    )
    return python if python.exists() else Path(sys.executable)


# ─────────────────────────────────────────────────────────────
# JSONC-safe parsing
#
# Zed settings.json allows // and /* */ comments and trailing commas.
# We NEVER reset to {} on failure — callers abort to keep the file intact.
# ─────────────────────────────────────────────────────────────

def _strip_jsonc_comments(text: str) -> str:
    """Remove // and /* */ comments while respecting string literals."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    esc = False
    while i < n:
        c = text[i]
        if esc:
            out.append(c)
            esc = False
            i += 1
            continue
        if c == "\\" and in_str:
            out.append(c)
            esc = True
            i += 1
            continue
        if c == '"':
            in_str = not in_str
            out.append(c)
            i += 1
            continue
        if not in_str:
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def parse_jsonc(text: str) -> dict:
    """Parse Zed settings.json (JSONC) into a dict. Raises on invalid JSON."""
    cleaned = _strip_trailing_commas(_strip_jsonc_comments(text))
    return json.loads(cleaned)


# ─────────────────────────────────────────────────────────────
# Targeted text surgery — only touch the keys we manage, preserve
# everything else (comments, other servers, user settings) as-is.
# ─────────────────────────────────────────────────────────────

def _find_value_span(text: str, key: str):
    """Return (start, end) indices of the JSON value for top-level `"key": value`."""
    m = re.search(r'"' + re.escape(key) + r'"\s*:', text)
    if not m:
        return None
    i = m.end()
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text):
        return None
    val_start = i
    c = text[i]
    if c in "{[":
        close = "}" if c == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        j = i
        while j < len(text):
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif in_str:
                if ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == c:
                depth += 1
            elif ch == close and depth > 0:
                depth -= 1
                if depth == 0:
                    return (val_start, j + 1)
            j += 1
        return None
    # primitive (string / number / bool / null)
    j = i
    while j < len(text) and text[j] not in ",}\n":
        j += 1
    return (val_start, j)


def _insert_before_final_brace(text: str, snippet: str) -> str | None:
    """Insert `snippet` (a `"key": value` fragment, no leading/trailing comma)
    as a new top-level property right before the final `}`."""
    stripped = text.rstrip()
    last = stripped.rfind("}")
    if last < 0:
        return None
    prefix = stripped[:last]
    j = last - 1
    while j >= 0 and stripped[j] in " \t\r\n":
        j -= 1
    comma = "," if j >= 0 and stripped[j] not in ",}" else ""
    return prefix + comma + "\n    " + snippet + "\n" + stripped[last:]


def _set_top_level(text: str, key: str, value_json: str) -> str:
    """Replace (or insert) the top-level `"key": value` with `value_json`."""
    span = _find_value_span(text, key)
    if span:
        s, e = span
        return text[:s] + value_json + text[e:]
    inserted = _insert_before_final_brace(text, f'"{key}": {value_json}')
    if inserted is None:
        raise ValueError("cannot locate final brace in settings.json")
    return inserted


# ─────────────────────────────────────────────────────────────
# Server entry merge
# ─────────────────────────────────────────────────────────────

def _make_server_entry(existing: dict | None, executable: str, args: list, ext_dir: Path) -> dict:
    """Build the merged server entry, preserving user customizations in `env`.

    Authoritative keys (ours) are always set: enabled, command, args,
    PYTHONPATH, PROJECT_PATH. Optional keys (EMBEDDING_*) keep the user's
    value if present. Any other user-added keys are preserved.
    """
    entry = dict(existing) if existing else {}
    entry["enabled"] = True
    entry["command"] = executable
    entry["args"] = list(args)

    env = dict(existing.get("env", {})) if existing else {}
    # Authoritative (ours):
    env["PYTHONPATH"] = str(ext_dir)
    env["PROJECT_PATH"] = "$ZED_WORKTREE_ROOT"
    # Optional: keep user value if present, else default.
    env.setdefault("EMBEDDING_PROVIDER", "e5_onnx")
    env.setdefault("EMBEDDING_DIMENSION", "768")
    entry["env"] = env
    return entry


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def patch_zed_settings(
    command: str | None = None,
    mode: str = "global",
    install_path: str | None = None,
) -> bool:
    """Add/update the MSCodeBase MCP context server in Zed's settings.json.

    Safe: preserves other context servers, user env vars, JSONC comments and
    all other settings. Only `context_servers` and `context_servers_to_query`
    are touched.

    Args:
        command: Full MCP launch command. If None, auto-built from the venv python.
        mode: 'global' → Zed config dir settings.json;
              'project' → ./.zed/settings.json
        install_path: Installed extension directory (sets PYTHONPATH). If None,
                      derived from this file's location.
    """
    if command is None:
        python_exe = get_python_path()
        command = f"{python_exe} -u -m src.main"

    if mode == "project":
        zed_dir = Path.cwd() / ".zed"
        zed_dir.mkdir(parents=True, exist_ok=True)
        settings_path = zed_dir / "settings.json"
    else:
        config_dir = get_zed_config_dir()
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Не удалось создать {config_dir}: {e}")
            return False
        settings_path = config_dir / "settings.json"

    logger.info(f"Настраиваю: {settings_path}")

    parts = command.split(maxsplit=1)
    if not parts:
        logger.error("Пустая команда.")
        return False
    executable = parts[0]
    args = parts[1].split() if len(parts) > 1 else []

    ext_dir = Path(install_path).resolve() if install_path else get_extension_install_dir()

    original = settings_path.read_text(encoding="utf-8") if settings_path.exists() else "{}"

    try:
        settings = parse_jsonc(original)
    except json.JSONDecodeError as e:
        logger.error(
            f"Файл {settings_path} не является валидным JSON/JSONC "
            f"(оставляю без изменений): {e}"
        )
        return False

    existing_cs = settings.get("context_servers", {}) or {}
    existing_entry = existing_cs.get(SERVER_NAME)
    new_entry = _make_server_entry(existing_entry, executable, args, ext_dir)

    # Idempotency: nothing to change?
    if existing_entry == new_entry and SERVER_NAME in (settings.get("context_servers_to_query") or []):
        logger.info(f"✅ MCP-сервер '{SERVER_NAME}' уже настроен, изменений нет.")
        return True

    # Merge (preserve other servers and their env)
    new_cs = dict(existing_cs)
    new_cs[SERVER_NAME] = new_entry
    cs_json = json.dumps(new_cs, indent=4, ensure_ascii=False)

    to_query = list(settings.get("context_servers_to_query") or [])
    if SERVER_NAME not in to_query:
        to_query.append(SERVER_NAME)
    tq_json = json.dumps(to_query, ensure_ascii=False)

    try:
        new_content = _set_top_level(original, "context_servers", cs_json)
        new_content = _set_top_level(new_content, "context_servers_to_query", tq_json)
    except ValueError as e:
        logger.error(f"Не удалось обновить {settings_path}: {e}")
        return False

    try:
        settings_path.write_text(new_content, encoding="utf-8")
    except OSError as e:
        logger.error(f"Ошибка записи {settings_path}: {e}")
        return False

    logger.info(f"✅ MCP-сервер '{SERVER_NAME}' настроен: {settings_path}")
    return True


def remove_zed_settings() -> bool:
    """Remove the MSCodeBase MCP server from Zed's settings.json (uninstall).

    Preserves all other settings. Comments may be lost on rewrite (explicit
    uninstall action) — but the file is never wiped on parse error.
    """
    config_dir = get_zed_config_dir()
    settings_path = config_dir / "settings.json"

    if not settings_path.exists():
        logger.info("Файл настроек не найден, удаление не требуется.")
        return True

    original = settings_path.read_text(encoding="utf-8")

    try:
        settings = parse_jsonc(original)
    except json.JSONDecodeError as e:
        logger.error(f"Файл {settings_path} повреждён, не удаляю: {e}")
        return False

    changed = False

    cs = settings.get("context_servers")
    if isinstance(cs, dict) and SERVER_NAME in cs:
        del cs[SERVER_NAME]
        changed = True
        if not cs:
            del settings["context_servers"]

    tq = settings.get("context_servers_to_query")
    if isinstance(tq, list) and SERVER_NAME in tq:
        settings["context_servers_to_query"] = [s for s in tq if s != SERVER_NAME]
        changed = True
        if not settings["context_servers_to_query"]:
            del settings["context_servers_to_query"]

    if changed:
        settings_path.write_text(
            json.dumps(settings, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info(f"✅ Настройки MCP-сервера '{SERVER_NAME}' удалены.")
    else:
        logger.info("Настройки MCP-сервера не найдены.")

    return True
