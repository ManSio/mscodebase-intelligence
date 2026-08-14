#!/usr/bin/env python3
"""revision_gate.py — consumer-side validator: min_accepted_revision (TC-9, RFC §3.3).

Проблема: verification-отчёт (smoke/verify) привязан к git HEAD (revision
binding), но потребитель обязан проверить, что ревизия отчёта >=
min_accepted_revision политики. Иначе — replay старой ревизии после ужесточения
политики (TC-9: «bounded» != «acceptable for new claims»).

Логика: git merge-base --is-ancestor <min> <current>.
  Exit 0 = VALID     — current — потомок min (или равен ему): отчёт актуален.
  Exit 1 = INVALID   — current старше min (связанные истории): replay отвергнут.
  Exit 2 = UNKNOWN   — истории несвязаны / нет git: честный UNKNOWN, НЕ accept
                       (в духе §5.24: непроверенное не проходит молча).

Источники min: --min-revision <sha> или --from-manifest (top-level поле
min_accepted_revision в scripts/negative_controls/manifest.json, пишется --pin).
Отсутствие min в manifest = grace-период (v0.3-совместимость): VALID с warning.

Оговорка: gate проверяет РЕВИЗИЮ, не чистоту дерева (dirty-отчёт воспроизводим
не полностью — это отдельная проблема, вне TC-9).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_MANIFEST = SCRIPT_DIR / "negative_controls" / "manifest.json"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# §5.9 ENCODING SAFETY (Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    """git через subprocess (main-поток, §5.16 не применим)."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        return p.returncode, out
    except Exception as e:  # noqa: BLE001 — диагностика: краш = UNKNOWN
        return -1, f"CRASH: {e}"


def _head(project: Path) -> str:
    rc, out = _git(["rev-parse", "HEAD"], project)
    return out if rc == 0 and out else ""


def _is_ancestor(min_sha: str, current_sha: str, project: Path) -> str:
    """'valid' | 'invalid' | 'unknown'."""
    if min_sha == current_sha:
        return "valid"
    rc, _ = _git(["merge-base", "--is-ancestor", min_sha, current_sha], project)
    if rc == 0:
        return "valid"
    if rc == 1:
        # Не предок — связаны ли истории вообще?
        rc2, _ = _git(["merge-base", min_sha, current_sha], project)
        return "invalid" if rc2 == 0 else "unknown"
    return "unknown"  # git-ошибка / краш


def _min_from_manifest(manifest_path: Path) -> str:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(data.get("min_accepted_revision", "") or "").strip()
    except Exception:  # noqa: BLE001 — диагностика
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Revision gate — min_accepted_revision (TC-9)")
    parser.add_argument("--min-revision", default="", help="минимальная принятая ревизия (sha)")
    parser.add_argument("--from-manifest", action="store_true", help="взять min из manifest.json")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="путь к manifest.json")
    parser.add_argument("--current", default="", help="ревизия отчёта (по умолч. git HEAD)")
    parser.add_argument("--project", default=str(PROJECT_ROOT), help="корень проекта (git)")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    min_sha = args.min_revision.strip()
    if args.from_manifest:
        min_sha = _min_from_manifest(Path(args.manifest).resolve())

    if not min_sha:
        print("REVISION GATE: min_accepted_revision не запинен — grace-период (v0.3-совместимость), VALID")
        return 0

    current = args.current.strip() or _head(project)
    if not current:
        print("REVISION GATE: UNKNOWN — нет git HEAD (ревизию отчёта определить нельзя)")
        return 2

    verdict = _is_ancestor(min_sha, current, project)
    if verdict == "valid":
        print(f"REVISION GATE: VALID (report {current[:12]} >= min {min_sha[:12]})")
        return 0
    if verdict == "invalid":
        print(f"REVISION GATE: INVALID — ревизия отчёта {current[:12]} старше min_accepted_revision {min_sha[:12]} (replay, TC-9)")
        return 1
    print(f"REVISION GATE: UNKNOWN — {min_sha[:12]} и {current[:12]} несвязаны или git-ошибка (не accept)")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — краш = UNKNOWN (exit 2), не молчаливый accept
        import traceback

        traceback.print_exc()
        sys.exit(2)
