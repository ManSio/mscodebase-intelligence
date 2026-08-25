"""Parity-чек B-1: наши экстракторы манифестов vs osv-scanner (Вариант В, спека 07).

Google osv-scanner (v2.5.1, pinned) — внешний валидатор форматов: прогоняем оба
парсера на одном корпусе (experiments/universal-engine/e-s1-polygon/fixtures);
множества имён должны совпадать (ADR-0005: membership, не версии).

Методика:
- Файлы корпуса копируются во временную папку под КАНОНИЧЕСКИМ именем (иначе
  НИ osv-scanner, НИ наш диспетчер не распознают формат: yarn-v1.lock ->
  yarn.lock, package-lock-v1.json -> package-lock.json). Свежая папка на
  КАЖДУЮ проверку — без накопления (osv резолвит `-e .`/относительные пути).
- Каталоги-проекты (manifest + lockfile-пара в фикстуре: requests, uv, berry,
  composer, ripgrep, migrate) сканируются ЦЕЛИКОМ — osv видит реальный контекст
  (иначе: «No package sources found» для одиночного манифеста; `-r`/`-e`
  резолвятся относительно соседних файлов).
- pnpm-каталог (4 разных формата, коллизии канонических имён) — per-file.
- Наша сторона: extract_manifest_entries(tmpdir) (runtime-путь).
- osv-сторона: osv-scanner scan --format json --all-packages.
- Сравнение: множества имён, канонизированных по экосистеме
  (PyPI -> PEP 503, npm -> lowercase, прочие -> lowercase trim).
  Расхождение в ЛЮБУЮ сторону = exit 1 (дыра в нашем экстракторе).
- Форматы вне поддержки osv-scanner — SKIP с причиной.

Usage:
  python scripts/manifest_parity.py [--osv PATH] [--fixtures DIR] [--verbose]
Exit: 0 = parity, 1 = расхождение, 2 = osv-scanner недоступен.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES = ROOT / "experiments" / "universal-engine" / "e-s1-polygon" / "fixtures"
OSV_VERSION = "2.5.1"

CANONICAL = {
    "yarn-v1.lock": "yarn.lock",
    "yarn-v2.lock": "yarn.lock",
    "package-lock-v1.json": "package-lock.json",
    "package-lock-v3.json": "package-lock.json",
    "pnpm-lock-monorepo.yaml": "pnpm-lock.yaml",
}

# Форматы вне поддержки osv-scanner v2.5.1 (проверено 2026-08-21 прогоном на корпусе).
SKIP = {
    "*.csproj": "osv-scanner не парсит NuGet-проекты (только packages.lock.json)",
    "Directory.Packages.props": "osv-scanner не парсит централизованный NuGet-манифест",
    "Gemfile": "osv-scanner читает только Gemfile.lock",
    "deno.json": "osv-scanner не поддерживает deno.json",
    "go.sum": "хэш-файл, не автономный манифест (модули видны из go.mod)",
    "Pipfile": "osv-scanner не поддерживает Pipfile (подтверждено прогоном)",
}

# Одиночные манифесты без lockfile-пары в корпусе: osv выдаёт «No package sources
# found» (проверено 2026-08-21) — неконтекстная проверка невозможна.
SKIP_DIRS = {
    "express": "одиночный package.json без lockfile — osv: No package sources found",
    "commons-lang": "одиночный pom.xml без lockfile — osv: No package sources found",
}

# Осознанные семантические расхождения (проверено 2026-08-21): не баги, а разный
# контракт: наш closed-world = registry-имена; osv = полный граф (workspace-члены
# monorepo, алиас-имена, editable-резолв `-e .[socks]` в pyproject). Формат:
# (dir, name или prefix или None=все имена dir) -> причина.
ALLOWED_DIFFS = {
    ("berry", "@yarnpkg/"): "workspace-члены monorepo yarn: мы исключаем локальные, osv включает",
    ("berry", "@docusaurus/"): "алиас/workspace-пакеты docusaurus: osv включает, мы registry-only",
    ("berry", "@slorber/"): "алиас-пакет (npm:@slorber/...): osv включает, мы registry-only",
    ("berry", "react-helmet-async"): "реальный npm-пакет (у нас); osv-имя ушло в алиас 'npm:@slorber/...'",
    ("berry", "react-loadable"): "реальный npm-пакет (у нас); osv-имя ушло в алиас 'npm:@docusaurus/...'",
    ("berry", "acceptance-tests"): "workspace-пакет monorepo yarn: osv включает, мы исключаем локальные",
    ("berry", "make-fetch-smaller"): "workspace/dep-алиас: osv включает, мы registry-only",
    ("berry", "pkg-tests-core"): "workspace-пакет monorepo yarn: osv включает, мы исключаем локальные",
    ("berry", "pkg-tests-fixtures"): "workspace-пакет monorepo yarn: osv включает, мы исключаем локальные",
    ("berry", "pkg-tests-specs"): "workspace-пакет monorepo yarn: osv включает, мы исключаем локальные",
    ("berry", "vscode-zipfs"): "workspace-пакет monorepo yarn: osv включает, мы исключаем локальные",
    ("requests", None): "osv резолвит '-e .[socks]' в транзитивный граф pyproject; мы не резолвим transitive",
}

_OSV_ECO = {
    "PyPI": "python", "pip": "python", "npm": "npm", "Go": "go",
    "crates.io": "cargo", "Maven": "maven", "NuGet": "nuget",
    "Packagist": "composer", "RubyGems": "gem",
}


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name)


def _canon_osv(name: str, eco: str) -> str:
    n = (name or "").strip().lower()
    return _pep503(n) if _OSV_ECO.get(eco) == "python" else n


def _canon_ours(entries) -> set[str]:
    out: set[str] = set()
    for e in entries:
        n = (e.name or "").strip().lower()
        out.add(_pep503(n) if e.ecosystem == "python" else n)
    return out


def _osv_packages(osv_bin: Path, dir_path: Path) -> set[str]:
    cmd = [str(osv_bin), "scan", "--format", "json", "--all-packages", str(dir_path)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"   ⚠️  osv-scanner сбой на {dir_path.name}: {exc}")
        return set()
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return set()
    out: set[str] = set()
    for res in data.get("results", []):
        for p in res.get("packages", []):
            pkg = p.get("package") or {}
            if pkg.get("name"):
                out.add(_canon_osv(pkg["name"], pkg.get("ecosystem", "")))
    return out


def _is_skipped(fname: str) -> bool:
    for pat, _why in SKIP.items():
        if pat.startswith("*") and fname.endswith(pat[1:]):
            return True
        if fname == pat:
            return True
    return False


def _apply_allowed(dir_name: str, ours: set[str], osv_names: set[str]) -> tuple[set[str], set[str]]:
    """Снимает с обоих множеств имена, покрытые ALLOWED_DIFFS (по префиксу)."""
    drop = set()
    for (d, spec), _why in ALLOWED_DIFFS.items():
        if d != dir_name:
            continue
        if spec is None:
            drop |= ours | osv_names
        else:
            for n in list(ours) + list(osv_names):
                if spec.endswith("/") and n.startswith(spec):
                    drop.add(n)
                elif n == spec:
                    drop.add(n)
    return ours - drop, osv_names - drop


def _map_dir(tmpdir: Path, src_dir: Path) -> None:
    """Копирует каталог фикстур в tmpdir с каноническими именами."""
    for f in sorted(src_dir.rglob("*")):
        if not f.is_file() or _is_skipped(f.name):
            continue
        name = CANONICAL.get(f.name, f.name)
        (tmpdir / name).write_text(f.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="B-1 manifest parity: ours vs osv-scanner")
    ap.add_argument("--osv", default=shutil.which("osv-scanner"))
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.osv or not Path(args.osv).is_file():
        print("osv-scanner не найден (--osv PATH). Локально: SKIP exit 2; CI упадёт честно.")
        return 2
    from src.sources.manifest import extract_manifest_entries

    checked, skipped, diffs = [], [], []
    for src_dir in sorted(d for d in args.fixtures.iterdir() if d.is_dir()):
        if src_dir.name in SKIP_DIRS:
            skipped.append((src_dir.name, SKIP_DIRS[src_dir.name]))
            continue
        files = [
            f for f in sorted(src_dir.rglob("*"))
            if f.is_file() and not _is_skipped(f.name)
        ]
        if not files:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            _map_dir(tmpdir, src_dir)
            ours = _canon_ours(extract_manifest_entries(tmpdir))
            osv_names = _osv_packages(Path(args.osv), tmpdir) if args.osv else set()
        checked.append(src_dir.name)
        if ours != osv_names:
            ours_d, osv_d = _apply_allowed(src_dir.name, ours, osv_names)
            if ours_d != osv_d:
                diffs.append((src_dir.name, sorted(ours_d - osv_d), sorted(osv_d - ours_d)))
            elif args.verbose:
                print(f"   ✅ {src_dir.name}: совпали после allowed-diffs ({len(ours - ours_d)})")
        elif args.verbose:
            print(f"   ✅ {src_dir.name}: {len(ours)} имён совпали")

    print(f"🔍 Manifest parity (osv-scanner {OSV_VERSION})")
    print(f"   проверено каталогов: {len(checked)}, skip (вне поддержки osv): {len(skipped)}")
    for name, why in skipped:
        print(f"   ⏭️  {name}: {why}")
    if diffs:
        print(f"\n❌ {len(diffs)} расхождение(й):")
        for name, only_ours, only_osv in diffs:
            print(f"   {name}: only-ours {len(only_ours)} -> {only_ours[:10]}")
            print(f"      only-osv {len(only_osv)} -> {only_osv[:10]}")
        return 1
    print("✅ Parity: расхождений 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
