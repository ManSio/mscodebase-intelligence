"""
Stale Detector — detects documentation drift from codebase.

Usage:
    python tools/stale_detector/stale_check.py                          # human-readable report
    python tools/stale_detector/stale_check.py --report-format=json     # JSON for CI
    python tools/stale_detector/stale_check.py --config stale_config.yaml

Configurable via stale_config.yaml (exclusion lists, severity overrides).
Supports <!-- stale-ignore --> comments in markdown to skip sections.

Returns exit code 1 if critical drifts found.
"""

import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")



@dataclass
class DriftHit:
    doc_file: str
    line: int
    expected: str
    actual: str
    severity: str  # "error" | "warn"
    context: str = ""
    check_type: str = "version"


@dataclass
class DocReport:
    path: str
    mtime: str
    hits: list
    total_hits: int = 0


# ─── Config ───────────────────────────────────────────────────

@dataclass
class StaleConfig:
    exclude_files: list = None
    exclude_dirs: list = None
    version_exclude_patterns: list = None
    version_ignore_files: list = None
    severity_overrides: dict = None

    def __post_init__(self):
        self.exclude_files = self.exclude_files or []
        self.exclude_dirs = self.exclude_dirs or [
            "sandbox", "__pycache__", ".git", "node_modules"
        ]
        self.version_exclude_patterns = self.version_exclude_patterns or []
        self.version_ignore_files = self.version_ignore_files or []
        self.severity_overrides = self.severity_overrides or {}

    @classmethod
    def from_file(cls, path: Path) -> "StaleConfig":
        if not path.exists():
            return cls()
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            exclude_files=data.get("exclude_files", []),
            exclude_dirs=data.get("exclude_dirs", []),
            version_exclude_patterns=data.get("version_exclude_patterns", []),
            version_ignore_files=data.get("version_ignore_files", []),
            severity_overrides=data.get("severity_overrides", {}),
        )




# ─── Core Logic ───────────────────────────────────────────────

def get_actual_version(project_root: Path) -> str:
    """Read version from pyproject.toml — single source of truth."""
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").split("\n"):
            m = re.match(r'version\s*=\s*["\'](.+?)["\']', line)
            if m:
                return m.group(1)
    return "unknown"


def is_excluded_version(ver: str, patterns: list[str]) -> bool:
    """Check if version matches any exclusion pattern."""
    for pat in patterns:
        if re.search(pat, ver):
            return True
    return False


def should_skip_file(rel_path: str, config: StaleConfig) -> bool:
    """Check if file should be excluded from scanning."""
    name = Path(rel_path).name
    if name in config.exclude_files:
        return True
    parts = Path(rel_path).parts
    if any(d in parts for d in config.exclude_dirs):
        return True
    return False


def is_in_stale_ignore(text: str, line_num: int) -> bool:
    """Check if line is inside <!-- stale-ignore --> block."""
    lines = text.split("\n")
    in_ignore = False
    for i in range(min(line_num, len(lines))):
        line = lines[i].strip()
        if "<!-- stale-ignore -->" in line:
            in_ignore = not in_ignore
        if i == line_num - 1:
            return in_ignore
    return False


def scan_doc(doc_path: Path, project_root: Path, actual_version: str,
             config: StaleConfig) -> Optional[DocReport]:
    """Scan one doc for version drift."""
    rel = str(doc_path.relative_to(project_root))
    if should_skip_file(rel, config):
        return None

    try:
        text = doc_path.read_text(encoding="utf-8")
    except Exception:
        return None

    mtime = datetime.fromtimestamp(doc_path.stat().st_mtime)
    hits = []
    lines = text.split("\n")
    in_code_block = False

    for i, line in enumerate(lines, 1):
        # Toggle code blocks
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Skip <!-- stale-ignore --> sections
        if is_in_stale_ignore(text, i):
            continue

        # Extract version-like strings
        for m in re.finditer(r'(?:v?)(\d+\.\d+\.\d+)', line):
            ver = m.group(1)

            # Skip excluded patterns (IP, dates, Zed versions)
            if is_excluded_version(ver, config.version_exclude_patterns):
                continue

            # Skip if this file is in version_ignore_files
            if any(rel.endswith(f) for f in config.version_ignore_files):
                continue

            if ver != actual_version:
                # Determine severity
                severity = "error"
                for pat, sev in config.severity_overrides.items():
                    if re.match(pat.replace("*", ".*"), rel):
                        severity = sev

                hits.append(DriftHit(
                    doc_file=rel,
                    line=i,
                    expected=ver,
                    actual=actual_version,
                    severity=severity,
                    context=line.strip()[:100],
                ))

    if not hits:
        return None

    return DocReport(
        path=rel,
        mtime=mtime.strftime("%Y-%m-%d %H:%M"),
        hits=[asdict(h) for h in hits],
        total_hits=len(hits),
    )


def run(project_root: Path, config: StaleConfig) -> list[DocReport]:
    """Scan all docs and return reports."""
    actual_version = get_actual_version(project_root)
    results = []

    for md_file in sorted(project_root.rglob("*.md")):
        report = scan_doc(md_file, project_root, actual_version, config)
        if report:
            results.append(report)

    return results


# ─── Output Formatters ────────────────────────────────────────

def format_human(results: list[DocReport], actual_version: str) -> str:
    """Human-readable report."""
    total_hits = sum(r.total_hits for r in results)
    errors = sum(
        1 for r in results for h in r.hits if h["severity"] == "error"
    )
    warns = total_hits - errors

    lines = [
        "=" * 70,
        f"📋 STALE DETECTOR — Doc Drift Report",
        f"   Actual version: {actual_version}",
        f"   Docs with drift: {len(results)}",
        f"   Total drift instances: {total_hits}",
        f"     ❌ Errors: {errors}  ⚠️  Warnings: {warns}",
        "=" * 70,
        "",
    ]

    for r in results[:20]:
        lines.append(f"📄 {r.path}")
        lines.append(f"   Modified: {r.mtime}")
        for h in r.hits[:3]:
            icon = "❌" if h["severity"] == "error" else "⚠️"
            lines.append(
                f"   {icon} L{h['line']}: docs say '{h['expected']}' "
                f"→ actual '{h['actual']}'"
            )
            lines.append(f"      {h['context'][:70]}")
        if len(r.hits) > 3:
            lines.append(f"   ... and {len(r.hits) - 3} more")
        lines.append("")

    # Top offenders
    lines.append("=" * 70)
    lines.append("📊 TOP OFFENDERS:")
    for r in sorted(results, key=lambda x: -x.total_hits)[:10]:
        lines.append(f"  {r.total_hits:3d} drifts  {r.path}")
    lines.append("=" * 70)

    if errors:
        lines.append("\n🚨 VERDICT: Docs have VERSION DRIFT — outdated info!")
    elif warns:
        lines.append("\n⚠️  VERDICT: Docs have minor reference issues.")
    else:
        lines.append("\n✅ VERDICT: Docs appear up to date.")

    return "\n".join(lines)


def format_json(results: list[DocReport], actual_version: str) -> str:
    """JSON report for CI integration."""
    total_hits = sum(r.total_hits for r in results)
    errors = sum(
        1 for r in results for h in r.hits if h["severity"] == "error"
    )

    report = {
        "actual_version": actual_version,
        "docs_with_drift": len(results),
        "total_drifts": total_hits,
        "errors": errors,
        "warnings": total_hits - errors,
        "ok": errors == 0,
        "files": [asdict(r) for r in results],
    }
    return json.dumps(report, indent=2, ensure_ascii=False)


# ─── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Detect documentation drift from codebase"
    )
    parser.add_argument(
        "--config", default="tools/stale_detector/stale_config.json",
        help="Path to config file (JSON)"
    )
    parser.add_argument(
        "--report-format", choices=["human", "json"], default="human",
        help="Output format"
    )
    parser.add_argument(
        "--project-root", default=".",
        help="Project root directory"
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    config_path = project_root / args.config
    config = StaleConfig.from_file(config_path)

    actual_version = get_actual_version(project_root)
    results = run(project_root, config)

    if args.report_format == "json":
        print(format_json(results, actual_version))
    else:
        print(format_human(results, actual_version))

    # Exit code: 1 if critical errors
    errors = sum(
        1 for r in results
        for h in r.hits if h.get("severity") == "error"
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
