"""Layer-boundary gate for the Universal Engine refactor (Фаза 1).

Enforces the three-axis split from the ТЗ (MSCODEBASE_UNIVERSAL_TOR §1):
ADAPTER → TRANSPORT → SOURCE → CORE. Core and tools must stay
platform/editor-agnostic.

Фаза 1 rules:
1. `src/mcp/tools/` must NOT import `adapters.*` / `src.sources.*` directly —
   tools are transport-agnostic.
2. `src/mcp/tools/` must NOT call `sys.platform` / `platform.system()` directly —
   use `src.core.platform_utils.is_windows()` instead.
3. `src/core/**` must NOT import `src.sources.*`, except the composition root
   (`src/core/di_container.py`), which by definition wires concrete providers.
   Цель «0 импортов из core» достигнута 2026-11-08: путь-примитив
   `to_win_long_path` переехал в `src/core/platform_utils.py`, парсер
   манифестов — в `src/core/deps/manifest/`, `Indexer` получает
   `WorkspaceSource` только инъекцией. Правило теперь ГЕЙТ (exit 1), а не WARN:
   регресс виден в CI и pre-commit.
4. `adapters.*` imported from anywhere in `src/` = ERROR, except `src/main.py`
   (adapter-dispatch entrypoint).
5. `src/utils/paths` and `src/utils/zed_config` are DEAD — any import of the old
   homes is an ERROR (grep-развёртка §5.14).
6. `src.sources.manifest` — DEAD home (2026-11-08): парсер зависимостей живёт в
   `src.core.deps.manifest`, импорт старого пути = ERROR.

Usage: python scripts/check_layer_boundaries.py   (exit 0 = clean, 1 = violation)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ENCODING SAFETY (Windows cp1251 console, §5.9 AGENTS.md)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(adapters(?:\.\w+)*|src\.utils\.paths|src\.utils\.zed_config|"
    r"src\.sources(?:\.\w+)*)"
    r"\s+import|import\s+(adapters(?:\.\w+)*|src\.utils\.paths|src\.utils\.zed_config|"
    r"src\.sources(?:\.\w+)*))",
)

PLATFORM_DIRECT_RE = re.compile(r"^\s*(?:sys\.platform|platform\.system)")

# Composition root: единственное место в src/, где можно знать реализации.
# Он связывает абстракции с провайдерами — иначе DI-контейнер не работает.
COMPOSITION_ROOT = "src/core/di_container.py"
# Мёртвые дома (после переездов). Импорт = ошибка, а не предупреждение.
DEAD_HOMES = ("src.utils.paths", "src.utils.zed_config", "src.sources.manifest")


def iter_py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def main() -> int:
    violations: list[str] = []
    transitional: list[str] = []

    for path in iter_py_files(SRC):
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        for lineno, line in enumerate(lines, start=1):
            m = IMPORT_RE.match(line)
            if not m:
                continue
            target = m.group(1)
            loc = f"{rel}:{lineno}"

            if target.startswith(tuple(DEAD_HOMES)):
                violations.append(f"[DEAD-IMPORT] {loc}: {line.strip()}")
            elif target.startswith("adapters."):
                if rel == "src/main.py":
                    continue  # entrypoint = adapter dispatch (rule 4)
                violations.append(f"[ADAPTER-LEAK] {loc}: {line.strip()} — src/ must not import adapters.*")
            elif target.startswith("src.sources."):
                if rel.startswith("src/mcp/tools/"):
                    violations.append(
                        f"[SOURCE-LEAK] {loc}: {line.strip()} — mcp/tools must not import source layer"
                    )
                elif rel == COMPOSITION_ROOT:
                    transitional.append(loc)  # allowed: composition root wires providers
                elif rel.startswith("src/core/"):
                    violations.append(
                        f"[CORE-SOURCE-LEAK] {loc}: {line.strip()} — only the composition "
                        f"root ({COMPOSITION_ROOT}) may import src.sources.*"
                    )

            # platform-direct check
            if PLATFORM_DIRECT_RE.match(line) and rel.startswith("src/mcp/tools/"):
                violations.append(
                    f"[PLATFORM-DIRECT] {loc}: {line.strip()} — use src.core.platform_utils.is_windows()"
                )

    print("🔍 Layer boundary check (Фаза 1)")
    print(f"   core→src.sources.* imports: {len(transitional)} (allowed only in {COMPOSITION_ROOT})")
    for loc in transitional:
        print(f"   ℹ️  {loc} (composition root)")

    if violations:
        print(f"\n❌ {len(violations)} violation(s):")
        for v in violations:
            print(f"   {v}")
        return 1

    print("✅ No layer-boundary violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
