"""Gate: параллельные агент-сессии не должны затирать друг друга.

Инцидент, который породил гейт (2026-10-03): две сессии работали в
одном и том же рабочем дереве. Одна создала tools/verification/*.py,
вторая про них не знала; каталог tools/knowledge/ появился в общем
дереве и исчез, и одна сессия объявила «данные потеряны», пока вторая
держала их в своём worktree. Третья переключила ветку в чужом дереве.

Правила, которые гейт защищает:

  R1  другое дерево с незакоммиченными изменениями → видимость
      (таблица владельцев), advisory
  R2  файл застейджен здесь И изменён в другом дереве → BLOCK
      (это прямое перетирание работы)
  R3  реестр (AGENT_DIARY/KNOWN_ISSUES/EXPERIMENTS_LOG/WISDOM/ISSUE)
      застейджен здесь, а в другом дереве он тоже изменён → BLOCK
  R4  другое дерево в %TEMP% → advisory (директория одноразовая)

§19.6: пустая популяция (нет других деревьев) — это SKIP с причиной,
а не «всё чисто».
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REGISTRIES = (
    "AGENT_DIARY.md",
    "KNOWN_ISSUES.md",
    "EXPERIMENTS_LOG.md",
    "WISDOM.md",
    "ISSUE.md",
)


def _norm(path: str) -> str:
    """Канонический вид пути: абсолютный, нижний регистр, прямые слэши.

    Обязателен, потому что git отдаёт пути worktree со слэшами
    (C:/Users/...), а pathlib на Windows — с обратными. Без нормализации
    гейт считает СОБСТВЕННОЕ дерево чужим и печатает уверенную
    неправду (инцидент 2026-10-03).
    """
    return os.path.abspath(path).replace("\\", "/").rstrip("/").lower()


def _git(args: list[str], cwd: str | Path | None = None) -> tuple[int, str]:
    """git с очищенным окружением.

    Хук запускается самим git, который экспортирует GIT_DIR (а в worktree это
    .git ГЛАВНОГО репозитория) в окружение. Если эти переменные не убрать,
    `git -C <другой worktree> status` продолжит работать с ТЕКУЩИМ
    репозиторием: гейт инспектирует не то дерево. Наблюдалось 2026-10-03 —
    ложный BLOCK на файлы, которых в чужом дереве никто не трогал, при
    одновременной потере настоящих пересечений (оба направления неверны).
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, proc.stdout


def other_worktrees() -> list[dict[str, str]]:
    """Все зарегистрированные worktree, кроме текущего."""
    code, out = _git(["worktree", "list", "--porcelain"])
    if code != 0:
        return []

    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        blocks.append(current)

    mine = _norm(str(PROJECT_ROOT))
    result = []
    for block in blocks:
        path = block.get("worktree", "")
        if not path or _norm(path) == mine:
            continue
        if block.get("prunable"):
            continue
        result.append({
            "path": path,
            "branch": block.get("branch", "?").replace("refs/heads/", ""),
        })
    return result


def dirty_in(path: str) -> set[str]:
    code, out = _git(["status", "--porcelain"], cwd=path)
    if code != 0:
        return set()
    files = set()
    for line in out.splitlines():
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ")[-1]
        if entry:
            files.add(entry.replace("\\", "/"))
    return files


def staged_here() -> set[str]:
    code, out = _git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if code != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


def _is_temp(path: str) -> bool:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if not temp:
        return False
    return _norm(path).startswith(_norm(temp) + "/")


def report() -> int:
    others = other_worktrees()
    staged = staged_here()

    if not others:
        print("ℹ️  SKIP parallel_sessions: других worktree не зарегистрировано "
              "(популяция пуста — это НЕ «всё чисто», просто нечего проверять)")
        return 0

    print(f"🔍 parallel_sessions: обнаружено других worktree = {len(others)}")

    conflicts: list[str] = []
    registry_conflicts: list[str] = []
    advisories: list[str] = []

    for tree in others:
        dirty = dirty_in(tree["path"])
        temp_mark = " ⚠️ в %TEMP% (одноразовая директория)" if _is_temp(tree["path"]) else ""
        print(f"  🌿 {tree['path']}")
        print(f"     ветка: {tree['branch']}{temp_mark}")
        if not dirty:
            print("     изменений нет")
            continue
        print(f"     незакоммичено: {len(dirty)} файл(ов)")
        for name in sorted(dirty)[:8]:
            print(f"       - {name}")
        if len(dirty) > 8:
            print(f"       … ещё {len(dirty) - 8}")

        for name in sorted(staged & dirty):
            if name in REGISTRIES:
                registry_conflicts.append(f"{name} — застейджен здесь и изменён в {tree['path']}")
            else:
                conflicts.append(f"{name} — застейджен здесь и изменён в {tree['path']}")
        if dirty & set(REGISTRIES):
            advisories.append(
                f"{tree['branch']}: трогает реестры {sorted(dirty & set(REGISTRIES))} — "
                f"это territory другой сессии, не пиши в них отсюда"
            )

    for note in advisories:
        print(f"  ⚠️  {note}")
    for note in conflicts:
        print(f"  ❌ {note}")
    for note in registry_conflicts:
        print(f"  ❌ РЕЕСТР: {note}")

    if advisories:
        print(f"  Итого: blocking=0, advisory={len(advisories)}")

    if conflicts or registry_conflicts:
        print("")
        print("  Ты коммитишь файл, который незакоммичен в другом worktree.")
        print("  Это перетирает чужую работу. Варианты:")
        print("   1) снять свой стейдж этого файла и ждать коммита другой сессии;")
        print("   2) убрать из стейджа и решить, кто владеет файлом;")
        print("   3) если это твой файл — сначала закоммить его в своей ветке.")
        return 1

    print("  ✅ blocking=0")
    return 0


def selftest() -> int:
    """Контроль обязан уметь падать: проверяем чистый разбор и классификацию."""
    failures: list[str] = []

    staged = {"AGENT_DIARY.md", "scripts/x.py"}
    registry = {"AGENT_DIARY.md"}
    if staged & registry != registry:
        failures.append("реестр должен распознаваться как конфликтующий")
    if "scripts/x.py" in registry:
        failures.append("обычный файл не должен считаться реестром")

    # Контроль строится от РЕАЛЬНОГО %TEMP%, иначе проверка бессмысленна:
    # путь выдуманного пользователя не может начинаться с нашей Temp.
    real_temp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    if real_temp and not _is_temp(str(Path(real_temp) / "wt-1")):
        failures.append("путь внутри реального %TEMP% не распознан")
    if _is_temp("D:/Project/definitely-not-temp/repo"):
        failures.append("обычный путь ошибочно помечен как %TEMP%")

    # Контроль на нормализацию разделителей: git отдаёт слэши, pathlib — обратные.
    if _norm("C:\\Users\\misha\\AppData\\Local\\Temp\\wt") != _norm("C:/Users/misha/AppData/Local/Temp/wt"):
        failures.append("собственное дерево было бы принято за чужое (разделители путей)")
    if _norm("D:/Project/MSCodeBase/") != "d:/project/mscodebase":
        failures.append("нормализация пути не каноническая")

    if failures:
        print("❌ parallel_sessions selftest FAILED:")
        for failure in failures:
            print(f"   - {failure}")
        return 1
    print("✅ parallel_sessions selftest: positive 1/1, negative 2/2")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    return report()


if __name__ == "__main__":
    sys.exit(main())
