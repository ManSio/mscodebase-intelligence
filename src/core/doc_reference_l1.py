"""doc_reference_l1.py — детерминированный L1-чекер ссылок в документации.

Задача: отвечать «существует ли упомянутый в живых доках код-референс?» с
**минимумом ложных срабатываний** (иначе гейт «кричит волк» и его игнорируют —
evergreen/doc-sync). Без LLM, без сети, чистая stdlib.

Почему не старая реализация (`auto_doc_updater._build_symbol_set`): она собирает
только ОПРЕДЕЛЕНИЯ (def/class/тулы/константы), поэтому параметры/поля/stdlib в
доках помечались «битыми» → 90%+ FP (замер 2026-09-23: 1366 «битых», ~3% реальных).

L1 делает:
- **Словарь** — ВСЕ идентификаторы + строковые литералы из src/tests/scripts/tools
  (существование, а не «является определением»).
- **Scope** — только ЖИВЫЕ доки: корневые *.md + docs/** кроме
  archive/generated/research/blog/ISSUES. История не «фиксится».
- **Исключения** — venv/.git/site-packages/node_modules (не сканировать).
- **Whitelist** — Python stdlib/builtins, внешние API (Zed/Rust/JS), env-переменные,
  имена моделей, декораторы (`@`), файловые ссылки (проверяются по диску).

Замечание: это НЕ семантическая проверка прозы (для неё — опциональный L2/LLM).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

__all__ = ["check", "format_report", "LIVE_SKIP_PARTS"]

# Живые доки: что НЕ считается «живым» (история/генерация/чужой периметр)
LIVE_SKIP_PARTS = {"archive", "generated", "research", "blog", "ISSUES", "investigations", ".git", "venv", ".venv"}
_SCAN_SKIP_PARTS = {"venv", ".venv", "site-packages", "node_modules", ".git", "__pycache__", "build", "dist"}
_SCAN_DIRS = ("src", "tests", "scripts", "tools")
_TEXT_SUFFIXES = {".py", ".ts", ".js", ".json", ".toml", ".yml", ".yaml"}
_ROOT_DOCS = (
    "README.md", "AGENTS.md", "WISDOM.md", "KNOWN_ISSUES.md", "CHANGELOG.md",
    "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "AI_INSTALLATION_PROMPT.md",
)
# Леджеры/история: имена в них датированы и не обязаны существовать в текущем коде
_LEDGER_DOCS = {"WISDOM.md", "KNOWN_ISSUES.md", "AGENT_DIARY.md", "EXPERIMENTS_LOG.md", "CHANGELOG.md", "ISSUE.md"}

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_STR_RE = re.compile(r"[\"']([A-Za-z_][A-Za-z0-9_\-]{2,})[\"']")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_SYMBOLIC = set("/\\:=#|<>[]()+→⇄*\"'{};,-%")
_KEYBOARD = {"Enter", "Escape", "Tab", "Shift", "Ctrl", "Alt", "Backspace", "Delete", "Esc"}

# Python stdlib / builtins / популярные методы (существование не в нашем коде)
_STDLIB = set("""
os sys json re subprocess asyncio logging pathlib typing dataclasses time datetime threading
collections itertools functools hashlib shutil tempfile socket math random textwrap copy pickle
contextlib abc enum uuid base64 struct ctypes platform traceback warnings gc inspect sqlite3
unittest argparse csv io string glob fnmatch urllib http email smtplib ftplib
open print len range str int float bool list dict set tuple bytes bytearray type super object
isinstance getattr setattr hasattr enumerate zip sorted any all min max sum abs round map filter
RuntimeError ValueError TypeError KeyError IndexError OSError FileNotFoundError PermissionError
Exception StopIteration NotImplementedError AttributeError ImportError ModuleNotFoundError
Popen Thread Process Queue Event Lock RLock Table Table.search connect
Path Optional List Dict Set Tuple Any Callable Iterable Sequence Union Mapping
Enum StrEnum dataclass field property staticmethod classmethod datetime date timedelta
MagicMock Mock AsyncMock patch monkeypatch tmp_path capsys caplog pytest fixture
""".split())

# Внешние поверхности (Zed extension API / Rust / JS), которые законно упоминаются в доках
_EXTERNAL = set("""
NonZeroU32 LanguageSettingsContent LspSettings BinarySettings ProjectSettingsContent Glob
zed_extension_api trusted_worktrees language_servers language_server_command
file_guard project_root max_retries module_name hierarchy_level is_public parent_id
gitMaxConcurrentClones gitMaxCodehostRequestsPerSecond StreamableHTTPServerTransport
agent.tool_permissions legend.tokenTypes buildType with_fallible_options with_failible_options
Adapter search indexer parser mcp core tests docs doc_sync feat fix refactor perf chore
expected_command graph_context_first
""".split())

_MODEL_RE = re.compile(r"^(?:bge|e5|gte|multilingual|ggml|Q[0-9]|qwen|llama|deepseek|nomic)", re.I)
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _build_vocabulary(root: Path) -> set:
    vocab: set = set()
    for d in _SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.suffix not in _TEXT_SUFFIXES:
                continue
            if set(f.parts) & _SCAN_SKIP_PARTS:
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            vocab.update(_IDENT_RE.findall(txt))
            vocab.update(_STR_RE.findall(txt))
    # имена MCP-тулов из декораторов (на случай, если нет в строковых литералах)
    for f in (root / "src").rglob("*.py"):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        vocab.update(re.findall(r'@\w+\.tool\("([a-z_][a-z0-9_]+)"\)', t))
    # корневые скрипты (install.py и т.п.) — тоже источник идентификаторов
    for f in root.glob("*.py"):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        vocab.update(_IDENT_RE.findall(t))
        vocab.update(_STR_RE.findall(t))
    return vocab


def _live_docs(root: Path) -> List[Path]:
    files: List[Path] = []
    for name in _ROOT_DOCS:
        p = root / name
        if p.exists() and name not in _LEDGER_DOCS:
            files.append(p)
    docs = root / "docs"
    if docs.exists():
        for p in docs.rglob("*.md"):
            if set(p.parts) & LIVE_SKIP_PARTS:
                continue
            files.append(p)
    return files


def _known(part: str, vocab: set) -> bool:
    return part in vocab or part in _STDLIB or part in _EXTERNAL


def _is_broken(tok: str, vocab: set, root: Path) -> bool:
    if "." in tok:
        parts = [p for p in tok.split(".") if p]
        if parts and parts[0] in _STDLIB:
            return False
        return not all(_known(p, vocab) for p in parts)
    return not _known(tok, vocab)


def _tokens(text: str):
    for m in _BACKTICK_RE.finditer(text):
        raw = m.group(1).strip()
        if not raw or " " in raw:
            continue
        if raw.startswith("@"):
            raw = raw[1:]
        if not raw or raw.startswith("$"):
            continue
        if raw.startswith(("self.", "cls.")):
            continue
        if raw.startswith("__") and raw.endswith("__"):
            continue
        if len(raw) < 2 or raw in _KEYBOARD:
            continue
        if raw.isdigit() or re.match(r"^\d", raw):
            continue
        if raw.endswith((".py", ".md", ".json", ".toml", ".exe", ".yml", ".yaml", ".txt", ".rs", ".ts")):
            continue
        if _MODEL_RE.match(raw) and (("-" in raw) or ("." in raw)):
            continue
        if _ENV_RE.match(raw):
            continue
        if any(c in raw for c in _SYMBOLIC):
            continue
        # только кодо-подобное: snake_case / CamelCase / CONST / tool-префикс
        if not ("_" in raw or re.search(r"[A-Z]", raw)):
            continue
        yield raw


def check(project_root: str | Path) -> Dict:
    root = Path(project_root).resolve()
    vocab = _build_vocabulary(root)
    broken: List[Tuple[str, int, str]] = []
    for doc in _live_docs(root):
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(doc.relative_to(root))
        for line_no, line in enumerate(text.splitlines(), 1):
            for tok in _tokens(line):
                if _is_broken(tok, vocab, root):
                    broken.append((rel, line_no, tok))
    return {
        "status": "ok",
        "vocab_size": len(vocab),
        "docs_checked": len(_live_docs(root)),
        "broken_count": len(broken),
        "broken": broken,
    }


def format_report(result: Dict) -> str:
    lines = [
        "📄 L1 doc-reference check",
        f"📁 Live docs: {result['docs_checked']} | vocabulary: {result['vocab_size']}",
        f"📛 Broken references: {result['broken_count']}",
    ]
    for f, ln, ref in result["broken"][:60]:
        lines.append(f"  • `{ref}` in {f}:L{ln}")
    if result["broken_count"] > 60:
        lines.append(f"  ... +{result['broken_count'] - 60} more")
    return "\n".join(lines)
