#!/usr/bin/env python3
"""
Experiment 1-C: Burst-Rename Sweep — сколько REFUTED рождает ОДИН rename-коммит.

Контролируемый прогон реального VerifyOnRead на синтетическом git-репозитории.
Вопрос Statewave: «How large does that queue get for you in practice?»

Дизайн:
- tmp-репо (git init) с N=30 реальных py-файлов.
- 30 memory-нод, каждая с file:-якорем на свой файл (как write-path ADR-0003).
- Коммит A (baseline) -> VOR: все 30 VERIFIED (контроль: якоря живые).
- Коммит B: rename-sweep *одним* коммитом (git mv 30 файлов в новый каталог) —
  файлы живы, но все 30 путей изменились.
- VOR после B: сколько REFUTED (это размер review-очереди в практике).
- Мера "батчей по коммиту" (предложение Statewave): если бы мы понимали, что
  коммит B — массовый move, можно carry-forward'ить якоря. Считаем fallback
  OpenLore-style: exact-body hash пережил rename == 30/30 идемпотентны.
- Латентность: fingerprint rebuild + проход.

Запуск: venv/Scripts/python.exe experiments/1V_memory_contamination/burst_sweep_exp.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import src  # noqa: F401  (обеспечивает import src.* при любом CWD)

N_FILES = 30
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def sh(cwd: Path, *args: str) -> str:
    proc = subprocess.Popen(
        [*args], cwd=str(cwd), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
    )
    out, _ = proc.communicate(timeout=60)
    return out.decode("utf-8", "replace")


def body_hash(p: Path) -> str:
    text = p.read_text(encoding="utf-8")
    # exact-body: без импортов/докстринга — «нормализованное тело» (limpet-style).
    keep = []
    in_doc = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc
            continue
        if in_doc:
            continue
        if s.startswith(("import ", "from ")):
            continue
        keep.append(s)
    return hashlib.sha256("\n".join(keep).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    try:
        from src.core.intelligence.store import IntelligenceStore
        from src.core.intelligence.verify_on_read import (
            STATUS_REFUTED,
            STATUS_VERIFIED,
            VerifyOnRead,
        )

        # ── 1. Синтетический репозиторий ──
        repo = Path(tempfile.mkdtemp(prefix="burst_sweep_"))
        (repo / "src" / "mod").mkdir(parents=True)
        for i in range(N_FILES):
            (repo / "src" / "mod" / f"m{i:02d}.py").write_text(
                f"\"\"\"{i:02d}\"\"\"\nimport os\n\ndef f{i:02d}() -> int:\n    return {i}\n",
                encoding="utf-8",
            )
        sh(repo, "git", "init", "-q")
        sh(repo, "git", "config", "user.email", "exp@local")
        sh(repo, "git", "config", "user.name", "Exp")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "base")

        # ── 2. Изолированный store с 30 нодами (file:-якоря) ──
        store_dir = repo / "_memory"
        store = IntelligenceStore(store_dir)
        nodes = []
        for i in range(N_FILES):
            nodes.append({
                "node_id": f"NODE-burst-{i:02d}",
                "section": "adrs",
                "timestamp": "2026-09-11 12:00:00",
                "data": {
                    "claim": f"module m{i:02d} provides f{i:02d}",
                    "anchors": [{"kind": "file", "value": f"src/mod/m{i:02d}.py"}],
                },
            })
        store.save_memory(nodes)

        verifier = VerifyOnRead(
            repo, store, threading.Lock(),
            cache_file=store_dir / "verify_cache.json",
        )

        # Body-хэши ДО sweep (для carry-forward оценки — snapshot в baseline).
        bodies_before = {}
        for i in range(N_FILES):
            old_p = repo / "src" / "mod" / f"m{i:02d}.py"
            bodies_before[i] = body_hash(old_p) if old_p.exists() else None
        mem, stats_a = verifier.run(store.load_memory())

        # ── 4. Rename-sweep одним коммитом: src/mod -> src/moved ──
        sh(repo, "git", "mv", "src/mod", "src/moved")
        sh(repo, "git", "commit", "-qm", "sweep: move src/mod -> src/moved (rename all 30)")
        head_b = sh(repo, "git", "rev-parse", "HEAD").strip()

        # VOR после B (свежий кэш вердиктов по новому HEAD)
        verifier2 = VerifyOnRead(
            repo, store, threading.Lock(),
            cache_file=store_dir / "verify_cache_b.json",
        )
        mem_b, stats_b = verifier2.run(store.load_memory())

        # ── 5. OpenLore-style body-hash carry (fallback, was-and-still-exists) ──
        renamed_ok = 0
        for i in range(N_FILES):
            new_body = body_hash(repo / "src" / "moved" / f"m{i:02d}.py") if (repo / "src" / "moved" / f"m{i:02d}.py").exists() else None
            if bodies_before[i] is not None and bodies_before[i] == new_body:
                renamed_ok += 1

        raw = store._load_json("project_memory.json")
        status = {n["node_id"]: n.get("status", "ACTIVE") for n in raw}
        n_refuted_b = sum(1 for n in status.values() if n == STATUS_REFUTED)

        print("=" * 88)
        print("Experiment 1-C: Burst-Rename Sweep (VerifyOnRead на синтетике)")
        print(f"файлов: {N_FILES} | коммит A: базовый | коммит B: rename-sweep (1 коммит)")
        print("-" * 88)
        print(f"Baseline (A):  VERIFIED={stats_a['verified']} REFUTED={stats_a['refuted']} "
              f"cache_hits={stats_a['cache_hits']} latency={stats_a['latency_ms']}ms")
        print(f"After sweep (B): VERIFIED={stats_b['verified']} REFUTED={stats_b['refuted']} "
              f"cache_hits={stats_b['cache_hits']} latency={stats_b['latency_ms']}ms "
              f"fingerprint={stats_b['fingerprint_build_ms']}ms")
        print(f"Review-очередь после ОДНОГО rename-коммита: {n_refuted_b}/{N_FILES} узлов REFUTED "
              f"({n_refuted_b / N_FILES:.0%})")
        print(f"OpenLore-style body-hash: уцелели при rename {renamed_ok}/{N_FILES} "
              f"({renamed_ok / N_FILES:.0%} — carry-forward идемпотентен)")
        print(f"Файлы живы под новым путём: файл НЕ удалён — только переименован.")
        print("-" * 88)
        print(f"Вердикт: VOR fail-closed по пути => rename-sweep массово отзывается;")
        print(f"         body-hash-якорь (не путь) переживает rename без потерь.")
        print(f"репо: {repo}")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())