"""Gate: персональные данные и сырые чужие дампы не попадают в репозиторий.

Проверяет staged-файлы (или все tracked при --all) на три сигнатуры,
наблюдённые в реальном инциденте 2026-10-03:

  R1  личный email (gmail/yahoo/proton/...) в файле, который не вендоренная
      метаданные зависимостей. Личные адреса третьих лиц — самая частая
      форма утечки при работе с чужими публикациями.
  R2  сигнатура scraped-профиля: >=3 маркеров карточки профиля
      (Location/Joined/Education/Profile image). Такой блок не пишут
      руками — он приходит из выгрузки.
  R3  объёмный дословный чужой текст: >=40KB текста с >=5 разными
      внешними доменами. Advisory: печатает, но не блокирует.

Почему не наивный email-сканер: замер 2026-10-03 на 1893 tracked-файлах
дал 767 совпадений, из которых 686 (89%) — ложные (`модуль@символ.py`
в трассировках вызовов, `n@mcp.tool` в сниппетах). Гейт на таком
регулярном выражении бесполезен и умирает от FP-усталости, как уже
умирал один guard в этом репозитории.

§19.6: пустая популяция обязана быть видна. При отсутствии staged-файлов
печатается SKIP с причиной, а не «0 нарушений».
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PERSONAL_DOMAINS = (
    "gmail.com", "googlemail.com", "proton.me", "protonmail.com",
    "icloud.com", "me.com", "yahoo.com", "yahoo.co.uk", "outlook.com",
    "hotmail.com", "live.com", "mail.ru", "yandex.ru", "yandex.com",
    "gmx.de", "gmx.com", "web.de", "fastmail.com",
)

OWNER_ALLOWLIST = {
    "mansio0602@gmail.com",
    "looky.msc@gmail.com",
}

# Файлы самого детектора. R2 на них НЕ применяется: список маркеров профиля
# (PROFILE_MARKERS) физически лежит в этих файлах, поэтому сканер ловит сам
# себя — 11 «чужих маркеров» в самом себе. Сузили allowlist до одного правила
# и ровно двух файлов: R1 (реальные email) на них продолжает работать, поэтому
# спрятать выгрузку в файл гейта по-прежнему нельзя.
DETECTOR_SELF_FILES = {
    "scripts/check_third_party_data.py",
    "tests/test_check_third_party_data.py",
}

# Домен, зарезервированный RFC 2606: зарегистрировать его невозможно, поэтому
# адрес на нём не может принадлежать живому человеку. Фикстуры используют его,
# чтобы проверять правило R1 без единого реального чужого адреса в публичном
# репозитории. В production-набор PERSONAL_DOMAINS он НЕ входит — иначе гард
# ловит собственные фикстуры; selftest и тесты передают его явно.
RESERVED_TEST_DOMAIN = "personal.invalid"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

PROFILE_MARKERS = (
    "- Location:",
    "Joined",
    "- Education:",
    "Profile image",
    "Work:",
)

VENDORED_MARKERS = (
    "fixtures/",
    "composer.lock",
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "poetry.lock",
    "pyproject.toml",
    "package.json",
    "pom.xml",
    "requirements",
)

DUMP_EXTS = {".md", ".html", ".htm", ".txt"}
DUMP_MIN_BYTES = 40_000
DUMP_MIN_DOMAINS = 5
DOMAIN_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _is_vendored(path: str) -> bool:
    return any(marker in path for marker in VENDORED_MARKERS)


def _personal_emails(text: str, personal_domains: frozenset[str] | set[str] | None = None) -> set[str]:
    """Адреса на личных доменах.

    `personal_domains` инъецируется только в тестах: им нужен домен, на котором
    адрес заведомо не существует (RFC 2606), чтобы доказать срабатывание R1,
    не кладя в репозиторий адрес живого человека.
    """
    domains = PERSONAL_DOMAINS if personal_domains is None else personal_domains
    found: set[str] = set()
    for match in EMAIL_RE.finditer(text):
        address = match.group(0).lower()
        domain = address.rsplit("@", 1)[1]
        if domain in domains and address not in OWNER_ALLOWLIST:
            found.add(address)
    return found
    return found


def _profile_markers(text: str) -> int:
    return sum(text.count(marker) for marker in PROFILE_MARKERS)


def _external_domains(text: str) -> set[str]:
    return {m.group(1).lower() for m in DOMAIN_RE.finditer(text)}


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def check_file(rel_path: str, personal_domains: frozenset[str] | set[str] | None = None) -> list[str]:
    findings: list[str] = []
    path = PROJECT_ROOT / rel_path
    if not path.is_file() or path.stat().st_size > 5_000_000:
        return findings

    text = _read(path)
    if text is None:
        return findings

    vendored = _is_vendored(rel_path)

    if not vendored:
        emails = _personal_emails(text, personal_domains)
        if emails:
            findings.append(
                f"R1 {rel_path}: личный email третьего лица: {', '.join(sorted(emails))}"
            )

    markers = _profile_markers(text)
    if markers >= 3 and rel_path not in DETECTOR_SELF_FILES:
        findings.append(
            f"R2 {rel_path}: сигнатура выгруженного профиля ({markers} маркеров "
            f"карточки) — выгрузка чужой страницы"
        )

    if path.suffix.lower() in DUMP_EXTS and path.stat().st_size >= DUMP_MIN_BYTES:
        domains = _external_domains(text)
        if len(domains) >= DUMP_MIN_DOMAINS:
            findings.append(
                f"R3 {rel_path}: {path.stat().st_size // 1024}KB текста с "
                f"{len(domains)} внешними доменами — возможен дословный чужой дамп "
                f"(advisory, не блокирует)"
            )

    return findings


def _staged_files() -> list[str] | None:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _report(targets: list[str], population_label: str) -> int:
    findings: list[str] = []
    skipped = 0
    for rel_path in targets:
        if not (PROJECT_ROOT / rel_path).is_file():
            skipped += 1
            continue
        findings.extend(check_file(rel_path))

    blocking = [f for f in findings if not f.startswith("R3 ")]
    advisory = [f for f in findings if f.startswith("R3 ")]

    if not targets:
        print(f"⚠️  SKIP third_party_data: {population_label} пуста — проверять нечего")
        print("   (это НЕ «0 нарушений»: популяция не измерена)")
        return 0

    print(f"🔍 third_party_data: {population_label}={len(targets)} файлов, "
          f"пропущено нечитаемых={skipped}")

    for finding in advisory:
        print(f"  ⚠️  {finding}")
    for finding in blocking:
        print(f"  ❌ {finding}")

    if blocking:
        print("")
        print("  Чужие персональные данные и выгруженные профили не коммитятся.")
        print("  Что делать: оставить выгрузку ВНЕ репозитория "
              "(напр. %LOCALAPPDATA%/mscodebase/audit-cache/),")
        print("  а в репозиторий положить только свой вывод + sha256 + URL источника.")
        print("  Вендоренные метаданные зависимостей лежат в allowlist (fixtures/, lock-файлы).")
        return 1

    if advisory:
        print(f"  Итого: blocking=0, advisory={len(advisory)}")
    else:
        print("  ✅ blocking=0, advisory=0")
    return 0


def selftest() -> int:
    """Контроль обязан уметь падать: без этого гейт не проверен (§7.1)."""
    tmp = PROJECT_ROOT / ".third_party_gate_selftest"
    cases = [
        ("R1_должен_поймать.txt",
         f"contact: reserved.person@{RESERVED_TEST_DOMAIN}\n", True, "R1"),
        ("R2_должен_поймать.txt",
         "- Location: France\nJoined\n- Education: X\nProfile image\n", True, "R2"),
        ("R3_чистый_наш_текст.txt",
         "обычный документ без чужих данных\n" * 10, False, None),
        ("R4_модуль@символ.py",
         "inc@monitoring.py\nsnapshot@observability.py\n", False, None),
    ]
    failures: list[str] = []
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        for name, content, should_flag, expect_rule in cases:
            target = tmp / name
            target.write_text(content, encoding="utf-8")
            rel = str(target.relative_to(PROJECT_ROOT)).replace("\\", "/")
            domains = set(PERSONAL_DOMAINS) | {RESERVED_TEST_DOMAIN}
            hits = check_file(rel, domains)
            flagged = [h for h in hits if not h.startswith("R3 ")]
            if should_flag and not any(expect_rule in h for h in hits):
                failures.append(f"{name}: ожидался {expect_rule}, получено {hits}")
            if not should_flag and flagged:
                failures.append(f"{name}: ложное срабатывание {flagged}")
            if should_flag and expect_rule == "R2" and not flagged:
                failures.append(f"{name}: R2 ушёл в advisory вместо blocking")
    finally:
        for leftover in tmp.glob("*"):
            leftover.unlink()
        tmp.rmdir()

    if failures:
        print("❌ third_party_data selftest FAILED:")
        for failure in failures:
            print(f"   - {failure}")
        return 1
    print("✅ third_party_data selftest: positive 2/2, negative 2/2")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="сканировать все tracked-файлы")
    parser.add_argument("--selftest", action="store_true", help="negative+positive control")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if args.all:
        return _report(_tracked_files(), "tracked")

    staged = _staged_files()
    if staged is None:
        print("❌ third_party_data: не удалось получить staged-файлы (git failed)")
        return 1
    return _report(staged, "staged")


if __name__ == "__main__":
    sys.exit(main())
