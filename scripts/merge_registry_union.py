"""Union-merge для реестров (AGENT_DIARY / KNOWN_ISSUES / WISDOM / архивы).

Зачем: когда две агент-сессии пишут один и тот же реестр, git разрешает
конфликт «ours или theirs» — и одна сторона молча теряется. Для дневника
это худший исход: обе секции выглядят целыми, и агент потом не знает,
что половина记录 потеряна.

Стратегия: разобрать все три версии (base/ours/theirs) на секции по
заголовкам и собрать объединение, сохраняя порядок ours → theirs-only.
Порядок внутри файла не важен для реестра (это хронологический журнал,
а не исполняемый код), а потеря записи — необратима и незаметна.

Использование:
    git merge origin/main --no-commit
    python scripts/merge_registry_union.py KNOWN_ISSUES.md WISDOM.md ...
    git add KNOWN_ISSUES.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SECTION_RE = re.compile(r"^##\s+\S")


def _read_stage(path: str, stage: int) -> str:
    proc = subprocess.run(
        ["git", "show", f":{stage}:{path}"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout if proc.returncode == 0 else ""


def split_sections(text: str) -> list[tuple[str, str]]:
    """[(heading, body)]; контент до первого '##' идёт под заголовком ''."""
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_head = None
    current: list[str] = []
    for line in lines:
        if SECTION_RE.match(line):
            if current_head is not None:
                sections.append((current_head, "\n".join(current).rstrip()))
            current_head = line
            current = []
        else:
            if current_head is None:
                current_head = ""
            current.append(line)
    if current_head is not None:
        sections.append((current_head, "\n".join(current).rstrip()))
    return sections


def _key(head: str) -> str:
    return re.sub(r"\s+", " ", head).strip().lower()


def union(ours_text: str, theirs_text: str) -> tuple[str, list[str], list[str]]:
    """Объединение построчно внутри общих заголовков.

    Объединение только по заголовкам НЕДОСТАТОЧНО: две сессии чаще всего
    дописывают в один и тот же последний раздел, и тогда теряется весь
    хвост второй стороны (проверено 2026-10-03: 6 содержательных строк
    в WISDOM.md исчезли молча). Поэтому для заголовка, присутствующего
    у обеих сторон, тело собирается как ours + строки theirs, которых
    ещё нет в ours.
    """
    ours = {(_key(h) if h else ""): (h, b) for h, b in split_sections(ours_text)}
    theirs = {(_key(h) if h else ""): (h, b) for h, b in split_sections(theirs_text)}

    order = [k for k in ours if k]
    added: list[str] = []
    parts: list[str] = []

    preamble = ours.get("", ("", ""))[1]
    if preamble.strip():
        parts.extend([preamble.rstrip(), ""])

    for key in order:
        head, body = ours[key]
        if key in theirs:
            _, their_body = theirs[key]
            ours_lines = body.splitlines()
            have = {line.rstrip() for line in ours_lines}
            extra = [line for line in their_body.splitlines()
                     if line.strip() and line.rstrip() not in have]
            body = "\n".join(ours_lines + extra)
        parts.append(head)
        if body.strip():
            parts.append(body)
        parts.append("")

    for key, (head, body) in theirs.items():
        if not key or key in ours:
            continue
        added.append(head)
        parts.append(head)
        if body.strip():
            parts.append(body)
        parts.append("")

    return "\n".join(parts).rstrip() + "\n", added, [h for k, (h, _) in ours.items() if k]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: merge_registry_union.py <file> [<file> ...]")
        return 2

    failures: list[str] = []
    for path in sys.argv[1:]:
        ours_text = _read_stage(path, 2)
        theirs_text = _read_stage(path, 3)
        if not ours_text or not theirs_text:
            print(f"  ⏭️  {path}: нет конфликта в индексе, пропускаю")
            continue

        merged, added_from_theirs, ours_heads = union(ours_text, theirs_text)
        Path(path).write_text(merged, encoding="utf-8")

        def _sig(text: str) -> set[str]:
            return {line.rstrip() for line in text.splitlines() if len(line.strip()) > 25}

        merged_sig = _sig(merged)
        ours_sig = _sig(ours_text)
        theirs_sig = _sig(theirs_text)
        lost_ours = [line for line in ours_sig - merged_sig if line not in theirs_sig]
        lost_theirs = [line for line in theirs_sig - merged_sig if line not in ours_sig]

        if lost_ours or lost_theirs:
            failures.append(
                f"{path}: потеряно ours={len(lost_ours)} theirs={len(lost_theirs)}"
            )
            for line in lost_ours[:3]:
                print(f"       ПОТЕРЯНО (ours): {line.strip()[:78]}")
            for line in lost_theirs[:3]:
                print(f"       ПОТЕРЯНО (theirs): {line.strip()[:78]}")
        print(f"  ✅ {path}: ours-потерь={len(lost_ours)}, theirs-потерь={len(lost_theirs)}, "
              f"секций из theirs добавлено={len(added_from_theirs)}")
        for head in added_from_theirs[:6]:
            print(f"       + {head.strip()[:78]}")
        if len(added_from_theirs) > 6:
            print(f"       … ещё {len(added_from_theirs) - 6}")

    if failures:
        print("❌ union-merge провалил проверку полноты:")
        for failure in failures:
            print(f"   - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
