"""Ответ на один вопрос: менялся ли в этом изменении код (а не только текст).

Нужен `changes`-job'у: тяжёлые job'ы (clean-state, docker-build,
transport-equiv-e2e, manifest-parity) стоят ~4.7 из 12.6 runner-минут на прогон
(замер 2026-11-15), а docs-only PR их не требует. Логика в Python, а не в
inline-shell, чтобы её можно было проверить тестами и чтобы она одинаково
работала на ubuntu и windows.

Печатает `true` или `false`. Пустая/неизвестная база — `true` (fail-open:
лучше прогнать лишнее, чем пропустить проверку).

Usage:
    python scripts/ci_changed_code.py <base-sha> [--root .]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Текст, который кодом не является: документация, реестры, артефакты прогонов.
TEXT_PATHS = re.compile(
    r"""^(
        docs/                  # канонические страницы и архив
      | experiments/           # артефакты прогонов (вне индексации)
      | logo/                  # картинки репозитория
      | [^/]+\.(md|txt|rst)$   # корневые README/AGENTS/реестры
      | .*/[^/]+\.(md|txt|rst)$ # markdown в любой папке (включая docs/*/…)
    )""",
    re.VERBOSE,
)

EMPTY_TREE = "0000000000000000000000000000000000000000"


def changed_files(root: Path, base: str) -> list[str] | None:
    """Файлы, изменённые от base до HEAD; None — база неизвестна."""
    if not base or set(base) == {"0"}:
        return None
    for candidate in (base, f"origin/{base}"):
        proc = subprocess.run(
            ["git", "diff", "--name-only", candidate, "HEAD"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if proc.returncode == 0:
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return None


def has_code(files: list[str]) -> bool:
    return any(not TEXT_PATHS.match(f.replace("\\", "/")) for f in files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    files = changed_files(Path(args.root).resolve(), args.base)
    if files is None:
        print("true")
        print("ci-changed-code: base unknown — treating as code change", file=sys.stderr)
        return 0
    verdict = "true" if has_code(files) else "false"
    print(verdict)
    print(f"ci-changed-code: {len(files)} file(s), code={verdict}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
