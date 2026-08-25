#!/usr/bin/env python
"""
change_preview.py — «внести изменение и точно знать, что будет» (тонкий CLI).

Логика — в src/core/change_preview.py (Тумблер: core = логика, этот файл =
обёртка, как scripts/stale_detector.py поверх tools/stale_detector/).

Вердикты (трёхзначная модель action_receipt):
  VERIFIED     — CHANGE WOULD PASS
  REFUTED      — CHANGE WOULD FAIL (список упавших тестов/гейтов)
  INCONCLUSIVE — не удалось выполнить (нет git/таймаут/изменений нет)

Использование:
    python scripts/change_preview.py              # diff HEAD..рабочее дерево
    python scripts/change_preview.py --base main   # diff main..рабочее дерево
    python scripts/change_preview.py --static       # только blast radius (без прогона)

Exit code: 0 = VERIFIED, 1 = REFUTED, 2 = INCONCLUSIVE.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from src.core.change_preview import ChangePreview, static_predict  # noqa: F401 (реэкспорт)

# ENCODING SAFETY (Windows §5.9): cp1251-консоль падает на юникод-выводе
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _git_root(repo: Path) -> Path | None:
    import subprocess

    proc = subprocess.run(
        ["git", "--no-pager", "rev-parse", "--show-toplevel"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip()).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD", help="база диффа (по умолчанию HEAD)")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--static", action="store_true",
                        help="только Фаза 1 (blast radius), без прогона в worktree")
    parser.add_argument("--repo", default=None, help="корень репозитория (авто-детект)")
    args = parser.parse_args()

    try:
        repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
        root = _git_root(repo)
        if root is None:
            print("INCONCLUSIVE: не git-репозиторий")
            return 2

        if args.static:

            info = static_predict(root, args.base)
            print(f"Changed files ({len(info['changed'])}): {', '.join(info['changed']) or '—'}")
            print(f"Risk: {info['risk']}")
            print(f"Affected tests ({len(info['affected_tests'])}): "
                  f"{', '.join(info['affected_tests']) or '—'}")
            print(f"Gates: {', '.join(info['gates']) or '—'}")
            return 0

        verdict, message = ChangePreview(root, args.base, timeout=args.timeout).run()
        print(f"\n=== CHANGE PREVIEW VERDICT: {verdict} ===\n{message}")
        return {"VERIFIED": 0, "REFUTED": 1, "INCONCLUSIVE": 2}[verdict]
    except Exception:  # noqa: BLE001 — вершина CLI: traceback + INCONCLUSIVE
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
