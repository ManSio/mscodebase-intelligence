#!/usr/bin/env python3
"""check_write_bytes.py — проверка БАЙТОВ файла ПОСЛЕ записи.

Зачем (замер 2026-11-07): три инцидента одного класса за 36 дней —
`AGENT_DIARY.md:786` (перезапись чужого файла), `:875` (PowerShell `Set-Content`
записал cp1251 → смешанная кодировка), `:1287` (полная перезапись потеряла CRLF).
Каждый раз лечили той же операцией, которая ломала. Гейт проверяет результат,
а не намерение.

Проверки:
  * файл декодируется как UTF-8 (strict);
  * нет UTF-8 BOM (PowerShell 5.1 `-Encoding utf8` его пишет — измерено);
  * переводы строк однородны внутри файла;
  * бинарные файлы (NUL в первых 8000 байт) пропускаются.

Коды возврата: 0 — чисто; 1 — нарушения; 2 — пустая популяция (нечего проверять).

§19.6: пустой вход — падение, не «0 нарушений».
§19.3: --selftest обязан уметь падать (positive) и молчать (negative).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOM = b"\xef\xbb\xbf"
BINARY_PROBE = 8000


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_PROBE]


def inspect(path: Path) -> list[str]:
    """Возвращает список нарушений. Пустой список = файл чист."""
    data = path.read_bytes()
    if not data:
        return []  # пустой файл — валидное состояние, не нарушение
    if is_binary(data):
        return []

    problems: list[str] = []
    if data.startswith(BOM):
        problems.append("UTF-8 BOM в начале файла")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        problems.append(f"не UTF-8: {exc.reason} на байте {exc.start}")
        return problems

    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    cr_only = text.count("\r") - crlf
    if cr_only:
        problems.append(f"одиночный CR ({cr_only})")
    if crlf and lf_only:
        problems.append(f"смешанные переводы строк: CRLF={crlf}, LF={lf_only}")
    return problems


def run(paths: list[Path]) -> int:
    if not paths:
        print("FATAL: не передано ни одного файла — проверять нечего (§19.6)", file=sys.stderr)
        return 2

    checked = skipped = 0
    bad: list[tuple[Path, list[str]]] = []
    for p in paths:
        if not p.is_file():
            continue
        data = p.read_bytes()
        if is_binary(data):
            skipped += 1
            continue
        checked += 1
        probs = inspect(p)
        if probs:
            bad.append((p, probs))

    if checked == 0:
        print("FATAL: все файлы бинарные или отсутствуют — популяция пуста (§19.6)", file=sys.stderr)
        return 2

    print(f"checked={checked} skipped_binary={skipped} violations={len(bad)}")
    for p, probs in bad:
        for prob in probs:
            print(f"FAIL {p}: {prob}")
    return 1 if bad else 0


def selftest() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def write(name: str, data: bytes) -> Path:
            p = root / name
            p.write_bytes(data)
            return p

        cases = [
            ("clean_lf", "строка 1\nстрока 2\n".encode("utf-8"), []),
            ("bom", BOM + "строка\n".encode("utf-8"), ["BOM"]),
            ("mixed", "a\r\nb\n".encode("utf-8"), ["смешанные"]),
            ("cp1251", "строка".encode("cp1251"), ["не UTF-8"]),
            ("binary", b"\x00\x01\x02\xff", []),
            ("empty", b"", []),
            ("clean_crlf", "a\r\nb\r\n".encode("utf-8"), []),
        ]
        for name, data, expect in cases:
            p = write(name, data)
            probs = inspect(p)
            got = " ".join(probs)
            if expect:
                hit = all(e in got for e in expect)
            else:
                hit = not probs
            print(f"selftest {name}: {'OK' if hit else 'FAIL'} — {got or 'clean'}")
            ok &= hit

        # positive: run() обязан вернуть 1 на грязном файле
        rc = run([write("dirty", BOM + b"x\n")])
        print(f"selftest run(dirty) rc={rc} (ожидается 1)")
        ok &= rc == 1

        # negative: run() обязан вернуть 0 на чистом
        rc = run([write("fine", "ok\n".encode("utf-8"))])
        print(f"selftest run(clean) rc={rc} (ожидается 0)")
        ok &= rc == 0

        # empty population → 2
        rc = run([])
        print(f"selftest run(empty) rc={rc} (ожидается 2)")
        ok &= rc == 2

    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--all" in argv:
        root = Path(__file__).resolve().parents[1]
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".ruff_cache", ".pytest_cache"}
        paths = [
            p
            for p in root.rglob("*")
            if p.is_file() and not (set(p.relative_to(root).parts) & skip)
        ]
        return run(paths)
    if "--tracked" in argv:
        # Гейт обязан смотреть только на то, что мы пишем и поддерживаем.
        # Generated-артефакты (experiments/**/results/**) — это данные, а не файлы репозитория:
        # на них 658 из 738 «нарушений» (замер 2026-11-07, FP = 89%).
        import subprocess

        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
        rel = [p for p in out.decode("utf-8").split("\0") if p]
        # Generated-артефакты экспериментов — данные, а не авторские файлы.
        # Замер 2026-11-07: без этого фильтра 658 из 712 нарушений — чужие CR
        # внутри ответов моделей (FP 93% по классу «одиночный CR»).
        def generated(p: str) -> bool:
            parts = p.lower().split("/")
            return "experiments" in parts and ("results" in parts or "runs" in parts)

        return run([root / p for p in rel if not generated(p)])
    return run([Path(a) for a in argv if not a.startswith("-")])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
