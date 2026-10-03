"""Ротация KNOWN_ISSUES.md по §4.8 R4 / §8: перенос закрытых записей в архив.

Правило отбора жёсткое: переносится ТОЛЬКО запись, в СОБСТВЕННОМ
заголовке которой нет слова Open. Записи вида «(Fixed) + … (open)»
остаются в живом файле — у них есть незакрытая часть.

Скрипт обязан быть идемпотентным и проверяемым: если переносить нечего,
он сообщает об этом и ничего не меняет (тихий ноль на пустой входе —
запрещённый результат, §19.6).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_registry_union import split_sections  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "KNOWN_ISSUES.md"
ARCHIVE = ROOT / "docs" / "archive" / "KNOWN_ISSUES_2026_10.md"
LIMIT = 300

ARCHIVE_HEADER = """# Архив KNOWN_ISSUES — 2026-10

> Вынесено при ротации §4.8 R4: живой файл превысил лимит 300 строк после
> union-merge двух параллельных сессий (ours=289, theirs=249, union=367).
> Перенесены ТОЛЬКО записи без слова Open в собственном заголовке.
> Ни одна Open/P1 не перемещена.
"""


CLOSED_MARKERS = ("fixed", "closed", "refuted", "superseded")


def is_closed(head: str) -> bool:
    """Закрыта ли запись.

    Требуется ПОЗИТИВНЫЙ признак закрытия в собственном заголовке.
    Наивное правило «нет слова Open» пропускает заголовки вообще без
    статуса — а это открытая работа, а не закрытая (поймано на dry-run
    2026-10-03: в перенос попадали P2, PRE-EXISTING и [FEATURE]).
    Отсутствие статуса — это «неизвестно», а неизвестное не повод
    архивировать. Тот же класс, что §19.6: неизмеренное ≠ нулевое.
    """
    if not head:
        return False
    lowered = head.lower()
    if "open" in lowered:
        return False
    return any(marker in lowered for marker in CLOSED_MARKERS)


def rotate(dry_run: bool = False) -> int:
    if not LIVE.is_file():
        print(f"❌ нет {LIVE.name} — нечего ротировать")
        return 2

    text = LIVE.read_text(encoding="utf-8")
    sections = split_sections(text)
    keep = [(h, b) for h, b in sections if not is_closed(h)]
    move = [(h, b) for h, b in sections if is_closed(h)]

    if not move:
        print(f"ℹ️  SKIP rotate_known_issues: переносить нечего "
              f"(живой файл {len(text.splitlines())} строк)")
        return 0

    parts: list[str] = []
    for head, body in keep:
        if not head:
            if body.strip():
                parts.append(body.strip())
            continue
        parts.append(head)
        if body.strip():
            parts.append(body.strip())
        parts.append("")

    new_text = "\n".join(parts).rstrip() + "\n"
    payload = []
    for head, body in move:
        payload.append(head)
        if body.strip():
            payload.append(body.strip())
        payload.append("")
    block = "\n".join(payload).rstrip() + "\n"

    print(f"📦 rotate_known_issues: переношу {len(move)} закрытых секций, "
          f"оставляю {len(keep)}")
    print(f"   строк: {len(text.splitlines())} -> {len(new_text.splitlines())} "
          f"(лимит {LIMIT})")
    for head, _ in move[:5]:
        print(f"   − {head.strip()[:74]}")
    if len(move) > 5:
        print(f"   … ещё {len(move) - 5}")

    open_sections = [h for h, _ in keep if h]
    still_open = [h for h in open_sections if "open" in h.lower()]
    print(f"   проверка: Open/P1 остаются в живом файле = {len(still_open)}")

    if dry_run:
        print("   (dry-run, файлы не изменены)")
        return 0

    if len(new_text.splitlines()) > LIMIT:
        print(f"❌ после ротации всё ещё {len(new_text.splitlines())} > {LIMIT} — "
              f"нужна ручная ревизия; файлы не изменены")
        return 1

    LIVE.write_text(new_text, encoding="utf-8")
    prefix = ARCHIVE.read_text(encoding="utf-8") if ARCHIVE.is_file() else ARCHIVE_HEADER
    if ARCHIVE.is_file() and "Вынесено при ротации" not in prefix:
        prefix = prefix.rstrip() + "\n\n" + ARCHIVE_HEADER
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(prefix.rstrip() + "\n\n" + block, encoding="utf-8")
    print(f"   запись перенесена в {ARCHIVE.relative_to(ROOT)}")
    return 0


def selftest() -> int:
    cases = [
        ("## 2026-01-01 — Fixed (Fixed)", True),
        ("## 2026-01-02 — Closed/REFUTED", True),
        ("## 2026-01-03 — partial (Fixed) + rest (open)", False),
        ("## 2026-01-04 — unresolved (Open, P1)", False),
        ("## 2026-01-05 — работа без статуса вовсе", False),
        ("## 2026-01-06 — [FEATURE] незавершено", False),
        ("", False),
    ]
    failures = [
        head for head, want in cases if is_closed(head) is not want
    ]
    if failures:
        print("❌ rotate selftest FAILED:")
        for head in failures:
            print(f"   - неверная классификация: {head!r}")
        return 1
    print(f"✅ rotate selftest: positive {sum(1 for _, w in cases if w)}/{sum(1 for _, w in cases if w)}, "
          f"negative {sum(1 for _, w in cases if not w)}/{sum(1 for _, w in cases if not w)}")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    return rotate(dry_run="--dry-run" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
