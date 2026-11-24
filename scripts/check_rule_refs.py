"""Гейт ссылок на ловушки: каждый `P-NNN` в глобальных правилах обязан быть заведён в реестре.

Проверяет глобальные правила (`AGENTS.md`, `agent_docs/*.md`, `skills/*/SKILL.md`) на:
  R1 висячую ссылку: `P-NNN` упомянут, но строки `| P-NNN |` в реестре нет;
  R2 дубль определения: один ID заведён дважды (разные классы под одним номером).

Зачем: 2026-11-24 параллельная правка `AGENTS.md` дала `P-086` в трёх значениях
(поправка Holm, живость харнесса, pre-push гейт) и ссылки на `P-087`/`P-088`,
которых в реестре не было. Такой конфликт не виден ни линтеру, ни тестам проекта.

Exit codes: 0 — чисто, 1 — есть проблемы, 2 — не смог измерить (нет реестра/файлов).
Пустой набор правил — это не «всё хорошо»: rc=2.

Usage:
    python scripts/check_rule_refs.py
    python scripts/check_rule_refs.py --root ~/.config/opencode
    python scripts/check_rule_refs.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REF = re.compile(r"\bP-\d{3}\b")
DEF = re.compile(r"^\|\s*(P-\d{3})\s*\|", re.M)


def collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    agents = root / "AGENTS.md"
    if agents.is_file():
        files.append(agents)
    docs = root / "agent_docs"
    if docs.is_dir():
        files.extend(sorted(docs.glob("*.md")))
    skills = root / "skills"
    if skills.is_dir():
        files.extend(sorted(skills.glob("*/SKILL.md")))
    return files


def check(root: Path, registry: Path) -> tuple[int, dict]:
    if not registry.is_file():
        return 2, {"error": f"реестр не найден: {registry}"}
    files = [f for f in collect_files(root) if f.resolve() != registry.resolve()]
    if not files:
        return 2, {"error": f"нет файлов правил под {root}"}

    reg_text = registry.read_text(encoding="utf-8", errors="replace")
    defs = DEF.findall(reg_text)
    if not defs:
        return 2, {"error": f"в реестре 0 определений: {registry}"}

    defined = set(defs)
    dups = sorted({d for d in defs if defs.count(d) > 1})
    dangling: list[tuple[str, str, int]] = []
    refs = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for ref in REF.findall(line):
                refs += 1
                if ref not in defined:
                    dangling.append((ref, str(path.relative_to(root)), lineno))

    report = {
        "files": len(files),
        "refs": refs,
        "defs": len(defined),
        "dangling": dangling,
        "dups": dups,
    }
    return (1 if dangling or dups else 0), report


def selftest() -> int:
    """Гейт обязан уметь падать: три сценария на временном дереве."""
    cases = [
        ("clean", ["P-001", "P-002"], ["P-001", "P-002"], 0),
        ("dangling", ["P-001", "P-777"], ["P-001"], 1),
        ("duplicate", ["P-001", "P-001"], ["P-001", "P-001"], 1),
    ]
    ok = True
    for name, refs, defs, want in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent_docs").mkdir()
            (root / "agent_docs" / "rules.md").write_text(
                "\n".join(f"текст Guard: `{r}`." for r in refs), encoding="utf-8"
            )
            reg = root / "agent_docs" / "pitfalls-registry.md"
            reg.write_text(
                "\n".join(f"| {d} | ловушка | guard | источник |" for d in defs), encoding="utf-8"
            )
            rc, rep = check(root, reg)
        got = "PASS" if rc == want else "FAIL"
        ok &= rc == want
        print(f"  selftest {name}: rc={rc} (ожидался {want}) -> {got}")
    for name, want in (("нет реестра", 2), ("пустое дерево", 2)):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = root / "нет-такого.md"
            if name == "пустое дерево":
                reg = root / "reg.md"
                reg.write_text("| P-001 | x | y | z |", encoding="utf-8")
            rc, _ = check(root, reg)
        got = "PASS" if rc == want else "FAIL"
        ok &= rc == want
        print(f"  selftest {name}: rc={rc} (ожидался {want}) -> {got}")
    print("selftest:", "OK" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ссылки P-NNN в правилах против реестра ловушек.")
    ap.add_argument("--root", default=str(Path.home() / ".config" / "opencode"))
    ap.add_argument("--registry", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    root = Path(args.root).expanduser()
    registry = Path(args.registry).expanduser() if args.registry else root / "agent_docs" / "pitfalls-registry.md"
    rc, rep = check(root, registry)

    if rc == 2:
        print(f"UNMEASURED: {rep['error']}")
        return 2

    print(f"файлов правил: {rep['files']}, ссылок P-NNN: {rep['refs']}, определений в реестре: {rep['defs']}")
    for ref, path, line in rep["dangling"]:
        print(f"  ВИСЯЧАЯ ССЫЛКА: {ref} в {path}:{line}")
    for d in rep["dups"]:
        print(f"  ДУБЛЬ ID: {d} заведён дважды")
    if rc == 0:
        print("clean: все ссылки резолвятся, дублей нет")
    return rc


if __name__ == "__main__":
    sys.exit(main())
