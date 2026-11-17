"""Ссылки память ↔ символ: вытащить символы проекта из записи памяти.

Зачем: у памяти проекта был только текст. Engraphis держит отдельную таблицу
`code_memory_links`, у нас — поле `symbols` в самом узле: `impact_analysis` и
`intel_get_project_memory` видят, что факт относится к реальному символу.

Точность важнее полноты: символ попадает в ссылки только если он реально
объявлен в файле **внутри проекта** (для Python — по AST, а не регуляркой:
строка `class X:` внутри docstring объявлением не является).
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

__all__ = ["extract_symbol_links", "MAX_LINKS"]

MAX_LINKS = 5
# Символы короче 8 символов не линкуются: короткое имя слишком часто
# встречается в обычном тексте, а ссылка должна быть точной, а не частой.
_MIN_NAME = 8
_IDENT = re.compile(r"\b[A-Za-z_]\w{%d,}\b" % (_MIN_NAME - 1))
_DECL = r"^\s*(?:async\s+)?(?:def|class)\s+"


def _graph_symbols(project_root: Path) -> Dict[str, Dict[str, Any]]:
    """Символы проекта из graph.db: name -> {file, kind}. Пусто — графа нет."""
    try:
        from src.core.artifact_paths import get_graph_db_path

        db = Path(str(get_graph_db_path(project_root)))
        if not db.exists():
            return {}
        # Путь в URI: `?` и `#` — разделители, поэтому экранируем их, иначе
        # имя каталога с таким символом молча даёт пустой граф.
        uri_path = db.as_posix().replace("%", "%25").replace("?", "%3F").replace("#", "%23")
        con = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select name, label, file_path from nodes where label in "
                "('Function','Method','Class','Interface','Type') "
                "order by name, label, file_path"
            ).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — ссылки не обязательны для записи
        return {}

    root = Path(project_root).resolve()
    out: Dict[str, Dict[str, Any]] = {}
    for name, label, file_path in rows:
        if not isinstance(name, str) or len(name) < _MIN_NAME:
            continue
        if not isinstance(file_path, str):
            continue
        try:
            # Relative paths in graph.db are relative to the project, not to
            # the server's cwd (which differs per client).
            candidate = Path(file_path)
            resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        except OSError:
            continue
        # Контейнмент по разрешённому пути, а не по подстроке: префикс
        # `.../proj` пропускал файлы из соседнего `.../projx` (ревью 2026-11-17).
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        out.setdefault(name, {"name": name, "file": str(resolved), "kind": label})
    return out


def _python_declarations(text: str) -> set[str]:
    """Имена `def`/`class` из AST: docstring и строки объявлением не считаются."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _declares(path: Path, name: str) -> bool:
    """Символ объявлен в файле, а не просто упомянут.

    Python — по AST (`class X:` внутри docstring не объявление). Для остальных
    языков — регулярка по началу строки: дерево разбора там не гарантировано,
    и это осознанная граница точности, а не забытый случай. Известная
    неточность: объявление внутри блочного комментария C-подобного файла
    регулярка считает объявлением — цена регулярки, зафиксирована явно.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if path.suffix.lower() == ".py":
        return name in _python_declarations(text)
    return re.search(_DECL + re.escape(name) + r"\b", text, re.M) is not None


def extract_symbol_links(data: Any, project_root: Path) -> List[Dict[str, Any]]:
    """Ссылки [{name, file, kind}] на реально объявленные символы проекта."""
    symbols = _graph_symbols(project_root)
    if not symbols:
        return []
    try:
        blob = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(data)

    links: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for name in _IDENT.findall(blob):
        if name in seen or name not in symbols:
            continue
        seen.add(name)
        meta = symbols[name]
        if not _declares(Path(meta["file"]), name):
            continue
        links.append(meta)
        if len(links) >= MAX_LINKS:
            break
    return links
