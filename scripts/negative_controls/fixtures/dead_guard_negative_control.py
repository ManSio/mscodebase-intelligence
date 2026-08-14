#!/usr/bin/env python3
"""Negative control для классификатора мёртвых guard-ов (ln.strip()-класс).

Запускает dead_guard.py на заведомо сломанном входе. Мёртвый guard ОБЯЗАН
молча пропустить его (exit 0) — это и есть доказательство, что инвентарь
умеет классифицировать такие guard-ы как BROKEN.

Контракт с runner-ом (manifest.json, expected_exit=1):
  exit 1 + маркер «DEAD GUARD DETECTED» = классификатор работает (PROVEN);
  exit 0 = фикстура перестала воспроизводить класс ln.strip() (INVALID —
           runner классифицирует запись как BROKEN).
"""
import subprocess
import sys
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass

HERE = Path(__file__).resolve().parent


def main() -> int:
    p = subprocess.run(
        [sys.executable, str(HERE / "dead_guard.py")],
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rc = p.returncode
    out = (p.stdout or b"").decode("utf-8", "replace")

    if rc == 0:
        # Мёртвый guard тихо пропустил сломанный вход → классификатор это видит.
        print("DEAD GUARD DETECTED: ln.strip()-класс, вход tampered пропущен (rc=0) — classified BROKEN")
        return 1
    print(f"DEAD GUARD CONTROL: INVALID — guard упал (rc={rc}), фикстура не ln.strip()-класс. Вывод: {out[:200]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — диагностика: crash ≠ catch
        import traceback

        traceback.print_exc()
        sys.exit(1)
