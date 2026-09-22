"""Quiet-break gate — детерминированный детектор «тихого слома» графа.

На коммите (через `graph_query(action="isolation")` + opencode-хук) отвечает на вопрос:
вносит ли ПРАВКА узел графа в изоляцию (осиротение), о котором молчит обычный ревью?

Два ДЕЛЬТА-сигнала (абсолютная изоляция не годится: 1535/4081 функций репо имеют
0 входящих CALLS — декораторы, entry points, callbacks; это шум, не сигнал):

A. removed_last_caller — символ, ВСЁ ЕЩЁ определённый в дереве, теряет последних
   вызывающих: правка удаляет вызовы `name(`, а среди оставшихся вызывающих (по
   persisted-графу) ни один больше не зовёт `name` в рабочем дереве.
B. new_orphan — НОВАЯ функция/метод (из diff), которую никто не вызывает в изменённых
   файлах и которая не является entry point / декоратором-регистрантом.

Всё ЧТЕНИЕ (git diff + persisted PropertyGraph), индекс НЕ мутируется. При отсутствии
git/графа/изменений — status "unavailable"/"empty", findings пусты, гейт НЕ срабатывает
(fail-open, причина логируется): инфраструктурный сбой не должен блокировать коммит.

Границы (см. Red Team в .agent_task_state): rename-guard (def удалён в том же diff),
whitelist (main/run/handle/test_*/step_*/setup/teardown/dunder), decorated-skip,
comment-строки игнорируются, same-name — консервативно.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.graph import EdgeType, NodeLabel, PropertyGraph

logger = logging.getLogger("mscodebase_server.quiet_break")

__all__ = ["run_quiet_break_gate", "parse_diff", "is_whitelisted"]

# entry points и регистранты — не считаются «сиротами» (зовутся фреймворком/декоратором)
_ENTRY_POINT_NAMES = {
    "main", "run", "start", "handle", "entry", "bootstrap", "init_app",
    "setup", "teardown", "setup_module", "teardown_module", "setup_method",
    "teardown_method", "setup_class", "teardown_class",
}
_WHITELIST_PREFIXES = ("test_", "step_")

_PY_KEYWORDS = {
    "if", "elif", "else", "for", "while", "return", "yield", "with", "as",
    "in", "is", "not", "and", "or", "lambda", "def", "class", "import",
    "from", "raise", "assert", "del", "global", "nonlocal", "await", "async",
    "match", "case", "print", "super", "type", "range", "len", "str", "int",
    "float", "list", "dict", "set", "tuple", "bool", "open", "getattr",
    "setattr", "isinstance", "enumerate", "zip", "sorted", "any", "all",
}

_DEF_RE = re.compile(r"^\+\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
_REMOVED_DEF_RE = re.compile(r"^-\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

_GRAPH_LABELS = (NodeLabel.FUNCTION, NodeLabel.METHOD)


def is_whitelisted(name: str, decorated: bool = False) -> bool:
    """True — имя является entry point / тест-хелпером / регистрантом (не «сирота»)."""
    if decorated:
        return True
    if name in _ENTRY_POINT_NAMES:
        return True
    if any(name.startswith(p) for p in _WHITELIST_PREFIXES):
        return True
    return name.startswith("__") and name.endswith("__")


def parse_diff(diff_text: str) -> Dict[str, Any]:
    """Разбирает unified-diff на дельта-сигналы.

    Returns dict:
      removed_calls: {name: [file, ...]}
      removed_defs:  {name, ...}   (def-строки, УДАЛЁННЫЕ этим diff — guard A)
      new_defs:      [{name, file, decorated}, ...]
      changed_files: [rel-posix, ...]
    """
    removed_calls: Dict[str, List[str]] = {}
    removed_defs: Set[str] = set()
    new_defs: List[Dict[str, Any]] = []
    changed_files: List[str] = []
    seen_files: Set[str] = set()

    cur_file = ""
    prev_added = ""

    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            if target and target != "/dev/null":
                cur_file = target
                if cur_file not in seen_files:
                    seen_files.add(cur_file)
                    changed_files.append(cur_file)
            prev_added = ""
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git") or raw.startswith("@@"):
            continue

        if raw.startswith("+"):
            stripped = raw[1:].strip()
            m = _DEF_RE.match(raw)
            if m:
                new_defs.append({
                    "name": m.group(1),
                    "file": cur_file,
                    "decorated": prev_added.startswith("@"),
                })
            prev_added = stripped
        elif raw.startswith("-"):
            if raw.startswith("---"):
                continue
            stripped = raw[1:].strip()
            if stripped.startswith("#"):
                prev_added = ""
                continue
            md = _REMOVED_DEF_RE.match(raw)
            if md:
                removed_defs.add(md.group(1))
            for name in _CALL_RE.findall(stripped):
                if name in _PY_KEYWORDS:
                    continue
                removed_calls.setdefault(name, []).append(cur_file)
            prev_added = ""
        else:
            # контекстная строка
            if raw.startswith(" "):
                prev_added = raw[1:].strip()

    return {
        "removed_calls": removed_calls,
        "removed_defs": removed_defs,
        "new_defs": new_defs,
        "changed_files": changed_files,
    }


def _rel_posix(path: str, root: Path) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        pass
    p = Path(path)
    for parent in p.parents:
        try:
            return p.relative_to(parent).as_posix()
        except ValueError:
            continue
    return p.as_posix()


def _incoming_callers(pg: PropertyGraph, qname: str) -> List[Any]:
    callers: List[Any] = []
    for et in (EdgeType.CALLS, EdgeType.ASYNC_CALLS):
        try:
            for node, _edge, _depth in pg.get_neighbors(
                qname, edge_type=et, direction="incoming", max_depth=1
            ):
                callers.append(node)
        except Exception:  # noqa: BLE001 — узел без рёбер/битый граф: не повод падать
            continue
    return callers


def _called_in_file(name: str, content: str) -> bool:
    call_re = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    def_re = re.compile(r"\bdef\s+" + re.escape(name) + r"\s*\(")
    for m in call_re.finditer(content):
        line_start = content.rfind("\n", 0, m.start()) + 1
        if def_re.search(content[line_start:m.end()]):
            continue  # это сама def-строка, не вызов
        return True
    return False


def _git_diff(root: Path) -> Tuple[Optional[str], str]:
    """git diff: staged если непусто, иначе HEAD.

    Returns (diff|None, base): None — не git/ошибка (fail-open); "" — git есть,
    но изменений нет (status empty).
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    is_repo = False
    for base_args, base_name in ((("--cached",), "cached"), (("HEAD",), "HEAD")):
        try:
            proc = subprocess.run(
                ["git", "diff", "--no-color", "--unified=3", *base_args],
                cwd=str(root),
                capture_output=True,
                timeout=20,
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001 — git может отсутствовать/зависнуть
            logger.warning("quiet_break: git diff failed (%s): %s", base_name, exc)
            return None, ""
        if proc.returncode == 0:
            is_repo = True
            out = proc.stdout.decode("utf-8", "replace")
            if out.strip():
                return out, base_name
    if is_repo:
        return "", "none"
    return None, ""


def _empty(status: str, message: str = "") -> Dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "base": "",
        "counts": {"removed_last_caller": 0, "new_orphan": 0},
        "findings": [],
        "changed_files": [],
    }


def run_quiet_break_gate(
    project_root: Path,
    pg: Optional[PropertyGraph],
    diff_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Главная точка. Возвращает dict с findings; никогда не бросает наружу."""
    root = Path(project_root).resolve()
    if pg is None:
        return _empty("unavailable", "PropertyGraph not available")
    db_path = getattr(pg, "_db_path", None) or getattr(pg, "path", None)
    if not db_path or not Path(str(db_path)).exists():
        return _empty("unavailable", "graph db not found")

    if diff_text is None:
        diff_text, base = _git_diff(root)
        if diff_text is None:
            return _empty("unavailable", "git not available")
    else:
        base = "provided"
    if not diff_text.strip():
        return _empty("empty", "no changes")

    parsed = parse_diff(diff_text)
    changed = set(parsed["changed_files"])
    removed_defs = parsed["removed_defs"]
    findings: List[Dict[str, Any]] = []

    # ── A: removed_last_caller ──
    for name, locs in parsed["removed_calls"].items():
        if name in removed_defs or name in _PY_KEYWORDS:
            continue
        try:
            nodes = [n for n in pg.find_nodes(name_pattern=name, limit=50)
                     if n.label in _GRAPH_LABELS]
        except Exception as exc:  # noqa: BLE001 — граф недоступен по узлу
            logger.debug("quiet_break: find_nodes(%s) failed: %s", name, exc)
            continue
        for node in nodes:
            callers = _incoming_callers(pg, node.qualified_name)
            if not callers:
                continue  # уже был без вызывающих — не наш дельта-сигнал
            alive = False
            for c in callers:
                cf = getattr(c, "file_path", "") or ""
                if not cf:
                    alive = True
                    break
                rel = _rel_posix(cf, root)
                if rel not in changed:
                    alive = True
                    break
                fp = root / rel
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    alive = True  # не смогли прочитать — консервативно считаем живым
                    break
                if _called_in_file(name, content):
                    alive = True
                    break
            if not alive:
                findings.append({
                    "kind": "removed_last_caller",
                    "symbol": node.name,
                    "file": node.file_path,
                    "removed_call_lines": locs,
                })

    # ── B: new_orphan ──
    contents: Dict[str, str] = {}
    for rel in changed:
        fp = root / rel
        try:
            contents[rel] = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    for d in parsed["new_defs"]:
        if is_whitelisted(d["name"], d["decorated"]):
            continue
        in_changed = any(_called_in_file(d["name"], txt) for txt in contents.values())
        if not in_changed:
            findings.append({
                "kind": "new_orphan",
                "symbol": d["name"],
                "file": d["file"],
                "decorated": d["decorated"],
            })

    counts = {
        "removed_last_caller": sum(1 for f in findings if f["kind"] == "removed_last_caller"),
        "new_orphan": sum(1 for f in findings if f["kind"] == "new_orphan"),
    }
    return {
        "status": "ok",
        "base": base,
        "counts": counts,
        "findings": findings,
        "changed_files": parsed["changed_files"],
    }
