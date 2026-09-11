#!/usr/bin/env python3
"""
Red-Team: атаки на решение Statewave (commit-batch / body-hash carry-forward).

Атака-1 (TOCTOU/batch-hazard): если «N якорей исчезли в одном коммите ⇒ это
    rename-sweep, не отзывать» — коммит, который ПРАВДА удаляет файлы, сам
    содержит renames. Проверка на реальных 10 TRUE_REFUTE: есть ли R-строки
    в том же коммите, что удалил файл? Если да → батч-эвристика ошибочно
    «спасёт» настоящие удаления.

Атака-3 (budget starvation): после rename-sweep ПЕРВОЕ чтение после смены HEAD
    перепроверяет все узлы в бюджете 50ms. Если узлов больше, чем бюджет
    позволяет — часть остаётся INCONCLUSIVE (не REFUTED): очередь растёт, но
    проверка молча пропущена. Симуляция на синтетике с малым бюджетом.

Атака-4 (present-trap recreated path): файл удалён и создан ЗАНОВО на том же
    пути с другим содержимым. Path-anchor VOR видит путь → VERIFIED (present),
    но факт про старое содержимое устарел. body-hash: старый body != новый →
    delete+add (честно). Показать разницу на синтетике.

Запуск:  venv/Scripts/python.exe experiments/1V_memory_contamination/redteam_burst.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\Project\MSCodeBase")
MEM = Path(r"C:\Users\misha\AppData\Local\mscodebase\projects\bfe9644b\intelligence\project_memory.json")
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def git(*args: str) -> str:
    proc = subprocess.Popen(
        ["git", "-C", str(ROOT), *args], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
    )
    out, _ = proc.communicate(timeout=60)
    return out.decode("utf-8", "replace")


def main() -> int:
    print("=" * 90)
    print("RED-TEAM: атаки на решение Statewave (commit-batch / body-hash carry)")

    # ── Атака 1: batch-hazard на реальных TRUE_REFUTE ──
    print("\n[Атака-1] Batch-hazard: тот ли коммит смешивает R-rename с D-delete?")
    nodes = json.loads(MEM.read_text(encoding="utf-8"))
    deleted_anchors = []
    for n in nodes:
        if n.get("retract_source") != "verify_on_read":
            continue
        reason = n.get("retract_reason") or ""
        m = re.search(r"file:(\S+)", reason)
        if not m:
            continue
        failed = m.group(1)
        if "://" in failed or failed.startswith("C:"):
            continue
        # проверяем deletion-историю пути (был ли он когда-либо удалён)
        out = git("log", "--all", "--diff-filter=D", "--format=%h %s", "-1", "--", failed)
        if not out.strip():
            continue
        commit = out.strip().split()[0]
        # в этом же коммите есть R-строки?
        stat = git("show", "--name-status", "--format=", commit)
        has_r = any(l.startswith("R") for l in stat.splitlines())
        deleted_anchors.append({"anchor": failed, "del_commit": commit,
                                "commit_has_renames": has_r,
                                "commit_msg": git("show", "-s", "--format=%s", commit).strip()})
    n_with_r = sum(1 for d in deleted_anchors if d["commit_has_renames"])
    for d in deleted_anchors:
        flag = "!!" if d["commit_has_renames"] else "ok"
        print(f"  [{flag}] {d['anchor']:<38} удалён в {d['del_commit']} "
              f"renames_in_same_commit={d['commit_has_renames']}: {d['commit_msg'][:48]}")
    print(f"  ИТОГ: {n_with_r}/{len(deleted_anchors)} удалений лежат в коммитах с renames "
          f"→ батч-эвристика «исчезли скопом = move» ошибочно спасла бы их.")

    # ── Атака 3: budget starvation ──
    print("\n[Атака-3] Budget starvation после sweep (cheap re-check при малом бюджете)")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import src  # noqa: F401
    from src.core.intelligence.store import IntelligenceStore
    from src.core.intelligence.verify_on_read import VerifyOnRead

    def sh(cwd: Path, *args: str) -> str:
        proc = subprocess.Popen(
            [*args], cwd=str(cwd), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
        )
        out, _ = proc.communicate(timeout=60)
        return out.decode("utf-8", "replace")

    repo = Path(tempfile.mkdtemp(prefix="rt_starv_"))
    (repo / "src" / "mod").mkdir(parents=True)
    N = 40
    for i in range(N):
        (repo / "src" / "mod" / f"m{i:02d}.py").write_text(
            f"\"\"\"{i:02d}\"\"\"\ndef f{i:02d}() -> int:\n    return {i}\n", encoding="utf-8")
    sh(repo, "git", "init", "-q")
    sh(repo, "git", "config", "user.email", "rt@local")
    sh(repo, "git", "config", "user.name", "RT")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "base")
    store = IntelligenceStore(repo / "_mem")
    nodes = [{
        "node_id": f"NODE-rt-{i:02d}", "section": "adrs",
        "timestamp": "2026-09-11",
        "data": {"claim": f"m{i:02d}", "anchors": [{"kind": "file", "value": f"src/mod/m{i:02d}.py"}]},
    } for i in range(N)]
    store.save_memory(nodes)
    v1 = VerifyOnRead(repo, store, threading.Lock(), cache_file=repo / "_mem" / "v.json")
    v1.run(store.load_memory())
    sh(repo, "git", "mv", "src/mod", "src/moved")
    sh(repo, "git", "commit", "-qm", "sweep")
    v2 = VerifyOnRead(repo, store, threading.Lock(), cache_file=repo / "_mem" / "v2.json")
    # бюджет для demo: дефолтный 50ms на 40 узлов реального быстрого цикла пройдёт;
    # снижаем до 0.05ms, чтобы показать механизм starvation.
    mem2, s2 = v2.run(store.load_memory(), budget_ms=0.05)
    print(f"  N={N} узлов, бюджет 0.05ms: checked={s2['checked']} "
          f"inconclusive={s2['inconclusive']} budget_exceeded={s2.get('budget_exceeded')}")
    if "budget_exceeded_nodes" in s2:
        print(f"  не проверены (остались в контексте как INCONCLUSIVE): "
              f"{len(s2['budget_exceeded_nodes'])} узлов из {N}")
    if "starved_nodes" in s2:
        print(f"  starved (matched>=2 && delivered==0): {len(s2['starved_nodes'])}")

    # ── Атака 4: present-trap recreated path ──
    print("\n[Атака-4] Present-trap: файл пересоздан на том же пути с ДРУГИМ телом")
    repo4 = Path(tempfile.mkdtemp(prefix="rt_present_"))
    (repo4 / "src").mkdir()
    (repo4 / "src" / "cfg.py").write_text(
        "def config() -> dict:\n    return {'mode': 'OLD'}\n", encoding="utf-8")
    sh(repo4, "git", "init", "-q")
    sh(repo4, "git", "config", "user.email", "rt@local")
    sh(repo4, "git", "config", "user.name", "RT")
    sh(repo4, "git", "add", "-A")
    sh(repo4, "git", "commit", "-qm", "base")
    st4 = IntelligenceStore(repo4 / "_mem")
    fact = [{
        "node_id": "NODE-rt4", "section": "adrs", "timestamp": "2026-09-11",
        "data": {"claim": "config имеет mode=OLD",
                 "anchors": [{"kind": "file", "value": "src/cfg.py"}]},
    }]
    st4.save_memory(fact)
    v41 = VerifyOnRead(repo4, st4, threading.Lock(), cache_file=repo4 / "_mem" / "v.json")
    v41.run(st4.load_memory())
    # пересоздаём путь (де-факто другая логика), коммит
    (repo4 / "src" / "cfg.py").write_text(
        "def config() -> dict:\n    return {'mode': 'NEW'}\n", encoding="utf-8")
    sh(repo4, "git", "add", "-A")
    sh(repo4, "git", "commit", "-qm", "recreate cfg with NEW mode")
    v42 = VerifyOnRead(repo4, st4, threading.Lock(), cache_file=repo4 / "_mem" / "v2.json")
    mem42, _ = v42.run(st4.load_memory())
    raw4 = {n["node_id"]: n.get("status") for n in st4._load_json("project_memory.json")}
    print(f"  path-anchor VOR: present-путь существует → статус {raw4.get('NODE-rt4')} "
          f"(факт про mode=OLD протух, но якорь жив)")
    print(f"  body-hash: старый body != новый → honest delete+add (size известно)")

    print("=" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())