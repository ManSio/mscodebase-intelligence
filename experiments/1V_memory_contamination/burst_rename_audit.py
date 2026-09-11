#!/usr/bin/env python3
"""
Experiment 1-B: Burst-Rename Audit — сколько «SILENT_ABSENCE» на деле переименования.

Гипотеза (из вопроса Statewave в dev.to): после refactor-коммита с массовыми
move/rename пачка якорей исчезает разом. Часть таких исчезновений — не удаления,
а переименования (файл жив под новым путём). Сколько из авто-REFUTED на реальной
памяти проекта — ложные отзывы по переименованным файлам?

Дизайн:
- Читаем реальный project_memory.json (bfe9644b).
- Для каждой ноды с retract_source == verify_on_read извлекаем failed-якорь из
  retract_reason ("SILENT_ABSENCE_ON_READ: file:X").
- Для X ищем в git-истории (--diff-filter=R`), переименован ли он:
    has_rename  -> файл был переименован после записи ноды (live elsewhere) -> FALSE_REFUTE
    no_rename   -> файл никогда не существовал или удалён без rename -> TRUE_REFUTE
    never_had   -> импорт/мусорный якорь (import:X, pkg:- и т.п.)
- Выход: таблица + агрегат (сколько отзывов — реальные удаления).

Запуск (GitBash/win):
  venv/Scripts/python.exe experiments/1V_memory_contamination/burst_rename_audit.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
MEM = Path(r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\intelligence\project_memory.json")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def git(*args: str, max_commit: str | None = None) -> str:
    """git <args> -- <file>, ограниченный временем до коммита (если задан)."""
    cmd = ["git", "-C", str(ROOT), *args]
    if max_commit is not None:
        cmd += [max_commit]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=_CREATE_NO_WINDOW,
    )
    out, _ = proc.communicate(timeout=20)
    return out.decode("utf-8", "replace")


RENAME_SOURCES: set[str] | None = None


def rename_sources() -> set[str]:
    """Все src-пути R*-переименований в истории (кэш на процесс)."""
    global RENAME_SOURCES
    if RENAME_SOURCES is not None:
        return RENAME_SOURCES
    s: set[str] = set()
    try:
        out = git("log", "--all", "--diff-filter=R", "--name-status", "--format=")
    except Exception:
        RENAME_SOURCES = s
        return s
    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[0].startswith("R"):
            src = parts[1].replace("\\", "/").lstrip("./")
            s.add(src)
            # basename-маппинг: якорь мог быть записан как `src/utils/paths.py`
            # или `paths.py` (нормализация в ADR-теле). Ложь только для
            # дублирующихся basename — здесь редкое исключение, принимаем.
            s.add(src.split("/")[-1])
    RENAME_SOURCES = s
    return s


def had_rename(path: str) -> bool:
    """Был ли путь целю R*-переименования где-либо в git-истории."""
    norm = path.replace("\\", "/").lstrip("./")
    return norm in rename_sources() or norm.split("/")[-1] in rename_sources()


def main() -> int:
    try:
        nodes = json.loads(MEM.read_text(encoding="utf-8"))
        if not isinstance(nodes, list):
            raise ValueError("project_memory.json: ожидался список нод")

        rows = []
        for n in nodes:
            if n.get("retract_source") != "verify_on_read":
                continue
            reason = n.get("retract_reason") or ""
            m = re.search(r"file:(\S+)", reason)
            failed = m.group(1) if m else None
            if failed is None or "://" in failed or failed.startswith("C:"):
                verdict = "anchor_junk"
                note = reason
            elif had_rename(failed):
                verdict = "FALSE_REFUTE_renamed"
                note = "файл переименован — жив под другим путём"
            else:
                verdict = "TRUE_REFUTE_deleted"
                note = "файл никогда не существовал/удалён без rename"
            rows.append({
                "node_id": n.get("node_id"),
                "status": n.get("status"),
                "failed_anchor": failed,
                "verdict": verdict,
                "note": note,
            })

        agg: dict = {}
        for r in rows:
            agg[r["verdict"]] = agg.get(r["verdict"], 0) + 1

        print("=" * 88)
        print("Experiment 1-B: Burst-Rename Audit (реальные авто-отзывы VOR)")
        print(f"авто-REFUTED нод (retract_source=verify_on_read): {len(rows)}")
        print("-" * 88)
        for r in rows:
            print(f"  {r['node_id']:<18} {r['verdict']:<22} {r['failed_anchor']}")
            print(f"    {r['note']}")
        print("-" * 88)
        print("Агрегат:")
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1]):
            print(f"  {k:<24} {v}")
        n_false = agg.get("FALSE_REFUTE_renamed", 0)
        n_true = agg.get("TRUE_REFUTE_deleted", 0)
        total_checked = n_false + n_true
        if total_checked:
            rate = n_false / total_checked
            print(f"\nЛожные отзывы по rename-якорям: {n_false}/{total_checked} = {rate:.1%}")
        print("=" * 88)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())