#!/usr/bin/env python3
"""bump_version.py — единая точка обновления версии во всех файлах проекта.

Usage:
    python scripts/bump_version.py 3.4.0          # Set specific version
    python scripts/bump_version.py --patch         # 3.3.1 → 3.3.2
    python scripts/bump_version.py --minor         # 3.3.1 → 3.4.0
    python scripts/bump_version.py --major         # 3.3.1 → 4.0.0
    python scripts/bump_version.py --show          # Show current version

Updates atomically:
  - pyproject.toml (version = "X.Y.Z")
  - docs/en/CHANGELOG.md (prepends new entry)
  - docs/ru/CHANGELOG.md (prepends new entry)
  - docs/zh/CHANGELOG.md (prepends new entry)

Run BEFORE writing the changelog entry — it creates the header,
you fill in the details.
"""

import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
CHANGELOGS = [
    PROJECT_ROOT / "docs" / "en" / "CHANGELOG.md",
    PROJECT_ROOT / "docs" / "ru" / "CHANGELOG.md",
    PROJECT_ROOT / "docs" / "zh" / "CHANGELOG.md",
]


def get_current_version() -> str:
    """Read version from pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Cannot find version in {PYPROJECT}")
    return m.group(1)


def bump(current: str, part: str) -> str:
    """Bump version by part: major, minor, patch."""
    parts = [int(x) for x in current.split(".")]
    if part == "major":
        parts = [parts[0] + 1, 0, 0]
    elif part == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    elif part == "patch":
        parts = [parts[0], parts[1], parts[2] + 1]
    return ".".join(str(x) for x in parts)


def set_version(new_version: str) -> None:
    """Update version in all files atomically."""
    today = date.today().isoformat()

    # 1. pyproject.toml
    text = PYPROJECT.read_text(encoding="utf-8")
    text = re.sub(
        r'^(version\s*=\s*)"\d+\.\d+\.\d+"',
        f'\\1"{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    PYPROJECT.write_text(text, encoding="utf-8")
    print(f"  ✅ pyproject.toml → {new_version}")

    # 2. CHANGELOGs — prepend header after first ---
    header_en = f"\n## [{new_version}] — {today}\n\n<!-- TODO: fill in changes -->\n"
    header_ru = f"\n## [{new_version}] — {today}\n\n<!-- TODO: опишите изменения -->\n"
    header_zh = f"\n## [{new_version}] — {today}\n\n<!-- TODO: 填写变更内容 -->\n"
    headers = zip(CHANGELOGS, [header_en, header_ru, header_zh])

    for changelog, header in headers:
        if not changelog.exists():
            print(f"  ⏭️  {changelog.name} — not found, skipping")
            continue
        text = changelog.read_text(encoding="utf-8")
        # Insert after the first --- separator
        idx = text.find("\n---\n")
        if idx == -1:
            # Fallback: insert after first heading
            idx = text.find("\n\n")
        insert_pos = idx + len("\n---\n") if idx != -1 else 0
        text = text[:insert_pos] + header + text[insert_pos:]
        changelog.write_text(text, encoding="utf-8")
        print(f"  ✅ {changelog.parent.name}/{changelog.name} → header added")


def check_version() -> None:
    """Check all version sources match. Exit 1 on mismatch."""
    from_pyproject = get_current_version()

    # Extract version from CHANGELOGs (first ## [X.Y.Z] header)
    errors = []
    for changelog in CHANGELOGS:
        if not changelog.exists():
            errors.append(f"  {changelog.parent.name}/{changelog.name} — not found")
            continue
        text = changelog.read_text(encoding="utf-8")
        m = re.search(r'^## \[(\d+\.\d+\.\d+)\]', text, re.MULTILINE)
        if m:
            ch_ver = m.group(1)
            if ch_ver != from_pyproject:
                errors.append(
                    f"  {changelog.parent.name}/{changelog.name}: {ch_ver} "
                    f"≠ pyproject: {from_pyproject}"
                )
        else:
            errors.append(f"  {changelog.parent.name}/{changelog.name} — no version header found")

    if errors:
        print("❌ Version mismatch(es):")
        for e in errors:
            print(e)
        sys.exit(1)
    else:
        print(f"✅ All version sources match: {from_pyproject}")


def main():
    if "--check" in sys.argv:
        check_version()
        return

    if "--show" in sys.argv or "-s" in sys.argv:
        print(get_current_version())
        return

    if "--help" in sys.argv or "-h" in sys.argv or len(sys.argv) < 2:
        print(__doc__)
        return

    current = get_current_version()
    print(f"Current version: {current}")

    if "--major" in sys.argv:
        new = bump(current, "major")
    elif "--minor" in sys.argv:
        new = bump(current, "minor")
    elif "--patch" in sys.argv:
        new = bump(current, "patch")
    else:
        # Explicit version
        new = sys.argv[1]
        # Validate format
        if not re.match(r"^\d+\.\d+\.\d+$", new):
            print(f"❌ Invalid version format: {new}. Use X.Y.Z")
            sys.exit(1)

    print(f"Bumping: {current} → {new}")
    set_version(new)
    print(f"\n✅ Version bumped to {new}")
    print("Now fill in the CHANGELOG entries and commit.")


if __name__ == "__main__":
    main()
