"""Держит `AGENTS.md` честным: пути существуют, флаги и переменные есть в коде, версия совпадает.

Проектный `AGENTS.md` читается хостом в каждой сессии, поэтому он дорог и быстро
гниёт: на 2026-11-15 в нём были неверное число чанков, несуществующий
`src/core/config.py` и переехавший `docs/en/ARCHITECTURE_DEEP.md`. Guard'ы
документации (`check_docs_vs_installer.py`, `check_docs_vs_config.py`,
`check_docs_refs.py`) этот файл не покрывали.

Правила:
  R1 файл не длиннее MAX_LINES;
  R2 каждый упомянутый путь репозитория существует (проверка по индексу git,
      регистронезависимо, поэтому вердикт одинаков на Windows и Linux);
  R3 каждый `install.py --flag` существует в установщике;
  R4 каждая `MSCODEBASE_*`/`MSCB_*` переменная встречается в коде;
  R5 «версия X.Y.Z» (если упомянута) совпадает с `pyproject.toml`;
  R6 числа из `docs/FACTS.md` (чанки/файлы/тесты) не дублируются;
  R7 файл ссылается на `docs/FACTS.md` и на этот гейт.

Exit codes: 0 чисто, 1 нарушения, 3 нечитаемый вход.

Usage:
    python scripts/check_agents_md.py
    python scripts/check_agents_md.py --path AGENTS.md --root .
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_LINES = 160

# Сгенерированные/шаблонные пути, которых намеренно нет в дереве.
ALLOWED_MISSING = {"docs/generated/module_index.md"}

# Всё, что не является путём репозитория: URL, домашние каталоги, шаблоны,
# Windows-переменные и абсолютные пути вида <install-root>/...
STRIP_PATTERNS = (
    re.compile(r"https?://[^\s`)]+"),
    re.compile(r"~/[^\s`)]*"),
    re.compile(r"%[A-Za-z_]+%[^\s`)]*"),
    re.compile(r"<[^>]+>[^\s`)]*"),
    re.compile(r"\b[A-Za-z]:\\[^\s`)]*"),
    re.compile(r"(?:[\w.-]+/)*\*[\w./*-]*"),  # glob-пути: `src/*/config.py`
)

PLACEHOLDER = re.compile(r"(YYYY|\.\.\.|…|[*<>{}])")
PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:\./)?(?:[\w.@-]+/)*[\w.@-]+\.(?:md|py|toml|json|yml|yaml|bat|sh|txt|cfg|ini|marker|ts|js|csv|log|png|svg)"
)
# Каталоги, где путь осмыслен и без расширения (`.githooks/pre-commit`).
PATH_DIR = re.compile(
    r"(?<![A-Za-z0-9])(?:\./)?(?:src|scripts|tests|adapters|tools|docs|deploy|experiments|extensions|examples|locales|logo|telemetry|\.githooks|\.github|\.opencode|\.locks)/[\w./-]+",
    re.IGNORECASE
)
FLAG_RE = re.compile(r"install\.py\s+(--[a-z][a-z0-9-]*)")
ENV_RE = re.compile(r"\b(?:MSCODEBASE|MSCB)_[A-Z0-9_]+\b")
VERSION_RE = re.compile(r"версия[:\s]+`?v?(\d+\.\d+\.\d+)`?", re.IGNORECASE)
COUNT_RE = re.compile(r"\b\d[\d\s]{3,}\s*(?:чанк|файл|тест)", re.IGNORECASE)

CORPUS_GLOBS = (
    "src/**/*.py",
    "scripts/**/*.py",
    "adapters/**/*.py",
    "install.py",
    ".env.example",
    ".githooks/*",
)


def code_corpus(root: Path) -> str:
    chunks = []
    for pattern in CORPUS_GLOBS:
        for path in root.glob(pattern):
            if path.is_file():
                try:
                    chunks.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
    return "\n".join(chunks)


def installer_flags(root: Path) -> set[str]:
    text = (root / "install.py").read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r'"(--[a-z][a-z0-9-]*)"', text))


def project_version(root: Path) -> str | None:
    text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None


def repo_files(root: Path) -> tuple[set[str], set[str]] | None:
    """(точные пути, casefold-пути) отслеживаемых и новых файлов; None — git недоступен."""
    files: set[str] = set()
    for extra in ((), ("--others", "--exclude-standard")):
        proc = subprocess.run(
            ["git", "ls-files", "-z", *extra],
            cwd=str(root), capture_output=True,
        )
        if proc.returncode != 0:
            return None
        files.update(p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p)
    exact = {f.replace("\\", "/") for f in files}
    return exact, {f.casefold() for f in exact}


def normalise(text: str) -> str:
    """Убирает всё, что выглядит путём, но им не является, и приводит `\\` к `/`."""
    for pattern in STRIP_PATTERNS:
        text = pattern.sub(" ", text)
    return text.replace("\\", "/")


def check(root: Path, text: str) -> list[str]:
    problems: list[str] = []
    lines = text.splitlines()

    if len(lines) > MAX_LINES:
        problems.append(f"R1: {len(lines)} строк (лимит {MAX_LINES}) — длинный файл не читают целиком")

    corpus = code_corpus(root)
    flags = installer_flags(root)
    version = project_version(root)
    known = repo_files(root)

    body = normalise(text)
    candidates = {m.group(0) for m in PATH_TOKEN.finditer(body)}
    candidates |= {m.group(0) for m in PATH_DIR.finditer(body)}
    for raw in sorted(candidates):
        path = raw.rstrip(".,);:`").lstrip("/")
        if path.startswith("./"):
            path = path[2:]
        if path.startswith("../"):
            problems.append(f"R2: путь `{raw}` выходит за корень репозитория")
            continue
        if PLACEHOLDER.search(path) or path.casefold() in ALLOWED_MISSING:
            continue
        if known is not None:
            exact, folded = known
            if path in exact:
                continue
            # каталог: `docs/blog/` или `src/ghost_dir/` — проверяем по префиксу
            prefix = path if path.endswith("/") else path + "/"
            if any(name.startswith(prefix) for name in exact):
                continue
            if path.casefold() in folded:
                problems.append(f"R2: регистр пути `{path}` не совпадает с файлом в репозитории")
                continue
            problems.append(f"R2: путь `{path}` не существует в репозитории")
        elif not (root / path).exists():
            problems.append(f"R2: путь `{path}` не существует в репозитории")

    for flag in sorted(set(FLAG_RE.findall(text))):
        if flag == "--flag":  # плейсхолдер в тексте, не реальный флаг
            continue
        if flag not in flags:
            problems.append(f"R3: флаг `{flag}` неизвестен установщику")

    for name in sorted(set(ENV_RE.findall(text))):
        if name not in corpus:
            problems.append(f"R4: переменная `{name}` не встречается в коде")

    if version:
        for mentioned in sorted(set(VERSION_RE.findall(text))):
            if mentioned != version:
                problems.append(f"R5: версия {mentioned} != pyproject {version}")

    for match in COUNT_RE.finditer(text):
        problems.append(
            f"R6: число «{match.group(0).strip()}» дублирует docs/FACTS.md — ссылайтесь на него"
        )

    if "docs/FACTS.md" not in text:
        problems.append("R7: нет ссылки на docs/FACTS.md — источник чисел")
    if "scripts/check_agents_md.py" not in text:
        problems.append("R7: файл не называет свой гейт scripts/check_agents_md.py")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--path", default="AGENTS.md")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    target = root / args.path
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"agents-md: cannot read {target}: {exc}", file=sys.stderr)
        return 3

    if not text.strip():
        print("agents-md: file is empty — refusing to pass", file=sys.stderr)
        return 1

    problems = check(root, text)
    for problem in problems:
        print(f"  FAIL {problem}")
    print(f"agents-md: {len(text.splitlines())}/{MAX_LINES} lines, {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
