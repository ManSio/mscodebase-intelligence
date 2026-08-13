#!/usr/bin/env python3
"""SMOKE MEMORY — реальный путь verify-on-read без моков (негативный контроль OWP).

Проверяет, что VOR делает то, что задумано, а не «зелёные галочки»:
  1. Positive arm: узел с живым якорем (file:src/main.py)          -> VERIFIED.
  2. Negative arm: узел с мёртвым якорем (file:src/never_exists.py) -> REFUTED
     с причиной SILENT_ABSENCE_ON_READ — верификатор умеет падать.
  3. No-anchor arm: узел без якорей -> остаётся ACTIVE (не отозван).
  4. Terminal guard: повторный прогон НЕ переписывает REFUTED обратно в VERIFIED.
  5. VOR-ресипт: stats честны (checked/nodes_seen, verified/refuted).

Exit 0 = PASSED; 1 = FAILED. Запуск: python scripts/smoke_memory.py
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# Корень проекта в sys.path — иначе import src.* падает при прямом запуске скрипта.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.intelligence.store import IntelligenceStore
from src.core.intelligence.verify_on_read import STATUS_ACTIVE, STATUS_REFUTED, STATUS_VERIFIED, VerifyOnRead

FAILURES = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "✅" if ok else "❌"
    print(f"   {mark} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    print("🧪 Smoke Memory — verify-on-read негативный контроль (реальный путь, без моков)")
    print("━" * 52)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_root = root / "data_root"
            os.environ["MSCODEBASE_DATA_DIR"] = str(data_root)
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("import os\nprint('ok')\n", encoding="utf-8")
            (root / ".env").write_text("MSCODEBASE_EXECUTE_SCRIPT_ENABLED=false\n", encoding="utf-8")

            store = IntelligenceStore(root)
            store.save_memory(
                [
                    {
                        "node_id": "N-positive",
                        "section": "adrs",
                        "timestamp": "2026-08-14 00:00:00",
                        "data": {
                            "claim": "живой якорь: src/main.py существует",
                            "anchors": [{"kind": "file", "value": "src/main.py"}],
                        },
                    },
                    {
                        "node_id": "N-negative",
                        "section": "adrs",
                        "timestamp": "2026-08-14 00:00:00",
                        "data": {
                            "claim": "мёртвый якорь: src/never_exists.py отсутствует",
                            "anchors": [{"kind": "file", "value": "src/never_exists.py"}],
                        },
                    },
                    {
                        "node_id": "N-noanchor",
                        "section": "adrs",
                        "timestamp": "2026-08-14 00:00:00",
                        "data": {"claim": "без якорей — INCONCLUSIVE-семантика"},
                    },
                ]
            )
            verifier = VerifyOnRead(root, store, threading.Lock())

            # ── Прогон 1: вердикты ──
            memory, stats = verifier.run(store.load_memory())
            raw = {n["node_id"]: n for n in store._load_json("project_memory.json")}

            pos = raw.get("N-positive", {}).get("status")
            check("Positive arm: живой якорь -> VERIFIED", pos == STATUS_VERIFIED, f"статус={pos}")

            neg = raw.get("N-negative", {})
            neg_ok = neg.get("status") == STATUS_REFUTED and "SILENT_ABSENCE_ON_READ" in str(
                neg.get("retract_reason", "")
            )
            check(
                "Negative arm: мёртвый якорь -> REFUTED с причиной",
                neg_ok,
                f"причина={str(neg.get('retract_reason', ''))[:70]}",
            )

            noa_store = raw.get("N-noanchor", {})
            noa_in_mem = any(
                n.get("node_id") == "N-noanchor" for section in memory.values() for n in section
            )
            check(
                "No-anchor arm: без якорей -> остаётся ACTIVE (не отозван)",
                noa_store.get("status", STATUS_ACTIVE) == STATUS_ACTIVE and noa_in_mem,
            )

            # ── Прогон 2: терминальный guard ──
            verifier.run(store.load_memory())
            raw2 = {n["node_id"]: n for n in store._load_json("project_memory.json")}
            check(
                "Terminal guard: повторный прогон не переписывает REFUTED",
                raw2.get("N-negative", {}).get("status") == STATUS_REFUTED,
            )

            # ── VOR-ресипт ──
            stats_ok = stats["checked"] == 3 and stats["verified"] == 1 and stats["refuted"] == 1
            check(
                "VOR-ресипт: checked/total честны",
                stats_ok,
                f"checked={stats['checked']}/nodes_seen={stats['nodes_seen']}, "
                f"verified={stats['verified']}, refuted={stats['refuted']}",
            )
    except Exception:
        import traceback

        traceback.print_exc()
        FAILURES.append("исключение при прогоне")

    print("━" * 52)
    if FAILURES:
        print(f"❌ SMOKE MEMORY: FAILED ({len(FAILURES)} проверок): {', '.join(FAILURES)}")
        return 1
    print("✅ SMOKE MEMORY: PASSED (проверок: 5)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
