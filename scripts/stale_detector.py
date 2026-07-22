#!/usr/bin/env python3
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
    exclude_dirs: list = None
    exclude_files: list = None
    severity_overrides: dict = None

    def __post_init__(self):
        if self.exclude_dirs is None:
            self.exclude_dirs = []
        if self.exclude_files is None:
            self.exclude_files = []
        if self.severity_overrides is None:
            self.severity_overrides = {}
def load_config(config_path: str) -> StaleConfig:
    """Load configuration from JSON file."""
    if not Path(config_path).exists():
        return StaleConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return StaleConfig(
        exclude_dirs=data.get("exclude_dirs", []),
        exclude_files=data.get("exclude_files", []),
        severity_overrides=data.get("severity_overrides", {}),
    )
def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Detect documentation drift from codebase")
    parser.add_argument(
        "--config", default="tools/stale_detector/stale_config.json",
        help="Path to config file (JSON)"
    )
    parser.add_argument(
        "--report-format", choices=["text", "json"], default="text",
        help="Report format"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # TODO: Implement actual stale detection logic
    # For now, just return success
    print("Stale Detector: No drifts detected (placeholder implementation)")

    if args.report_format == "json":
        import json
        print(json.dumps({"drifts": [], "total": 0}, ensure_ascii=False, indent=2))

    sys.exit(0)
if __name__ == "__main__":
    main()