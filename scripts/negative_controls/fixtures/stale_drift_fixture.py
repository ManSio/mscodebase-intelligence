#!/usr/bin/env python3
"""Negative control для stale_detector (stale_check.py): мутант version-дрейфа.

Создаёт временный проект: pyproject.toml version=3.4.0 + docs/README.md с
«v3.2.0» → stale_check.py ОБЯЗАН вернуть exit 1 (error-дрейф найден).

Exit 0 = guard доказан (умеет падать); 1 = guard сломан (не видит дрейф или crash).
Marker в выводе: «STALE NEGATIVE CONTROL: PASSED» — runner проверяет его
(«crash ≠ catch»: exit 1 с traceback без маркера — не обнаружение).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass

HERE = Path(__file__).resolve().parent  # scripts/negative_controls/fixtures
ROOT = HERE.parent.parent.parent  # корень проекта
STALE_CHECK = ROOT / "tools" / "stale_detector" / "stale_check.py"
REAL_CONFIG = ROOT / "tools" / "stale_detector" / "stale_config.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "tools" / "stale_detector").mkdir(parents=True)

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "stale-drift-fixture"\nversion = "3.4.0"\n',
            encoding="utf-8",
        )
        # Мутант дрейфа: «v3.2.0» ≠ 3.4.0 в pyproject. Не попадает в
        # version_exclude_patterns stale_config.json (3.10-3.14 исключены, 3.2 — нет).
        (tmp_path / "docs" / "README.md").write_text(
            "# Fixture\nТекущая версия: v3.2.0  <!-- мутант дрейфа: pyproject=3.4.0 -->\n",
            encoding="utf-8",
        )
        shutil.copy2(REAL_CONFIG, tmp_path / "tools" / "stale_detector" / "stale_config.json")

        p = subprocess.run(
            [sys.executable, str(STALE_CHECK), "--project-root", str(tmp_path)],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rc = p.returncode
        out = (p.stdout or b"").decode("utf-8", "replace")

    if rc != 1:
        print(f"STALE NEGATIVE CONTROL: FAILED — stale_check не упал (rc={rc}). Вывод: {out[:400]}")
        return 1
    if "3.2.0" not in out and "drift" not in out.lower():
        print(f"STALE NEGATIVE CONTROL: FAILED — exit 1 без детекции дрейфа (crash?). Вывод: {out[:400]}")
        return 1
    print("STALE NEGATIVE CONTROL: PASSED — stale_check умеет падать на version-дрейфе (rc=1, drift найден)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — диагностика: crash ≠ catch
        import traceback

        traceback.print_exc()
        sys.exit(1)
