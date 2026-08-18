"""Layer-boundary gate for the Universal Engine refactor (Фаза 1).

Enforces the three-axis split from the ТЗ (MSCODEBASE_UNIVERSAL_TOR §1):
ADAPTER → TRANSPORT → SOURCE → CORE. Core and tools must stay
platform/editor-agnostic.

Фаза 1 rules:
1. `src/mcp/tools/` must NOT import `adapters.*` / `src.sources.*` directly —
   tools are transport-agnostic.
2. `src/mcp/tools/` must NOT call `sys.platform` / `platform.system()` directly —
   use `src.core.platform_utils.is_windows()` instead.
3. TRANSITIONAL (WARN + count, must reach 0 by end of Фаза 2): `src/core/**`
   may still import `src.sources.local_fs.windows` (db_manager, tools_reg).
   indexer.py уже получает path_manager от LocalFsSource (Фаза 1).
4. `adapters.*` imported from anywhere in `src/` = ERROR, except `src/main.py`
   (adapter-dispatch entrypoint). Windows/Zed-примитивы живут в source-слое
   (src/sources/local_fs/windows.py), НЕ в adapters.
5. `src/utils/paths` and `src/utils/zed_config` are DEAD — any import of the old
   homes is an ERROR (grep-развёртка §5.14).

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

            if target in ("src.utils.paths", "src.utils.zed_config"):
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
                elif rel.startswith("src/core/"):
                    # TRANSITIONAL: дефолтная реализация (Indexer) + хелперы путей
                    # (db_manager/tools_reg); цель — 0 к концу Фазы 2, когда DI
                    # инжектит WorkspaceSource в Indexer/ProjectIndexerRegistry.
                    transitional.append(loc)

            # platform-direct check
            if PLATFORM_DIRECT_RE.match(line) and rel.startswith("src/mcp/tools/"):
                violations.append(
                    f"[PLATFORM-DIRECT] {loc}: {line.strip()} — use src.core.platform_utils.is_windows()"
                )

    print("🔍 Layer boundary check (Фаза 1)")
    print(f"   transitional core→src.sources.* imports: {len(transitional)} "
          f"(must reach 0 by end of Фаза 2)")
    for loc in transitional:
        print(f"   ⚠️  {loc}")

    if violations:
        print(f"\n❌ {len(violations)} violation(s):")
        for v in violations:
            print(f"   {v}")
        return 1

    print("✅ No layer-boundary violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
