"""Mutation check: each guard must fail when its fix is removed.

Run after the suite (it edits source files and restores them byte-for-byte).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\Project\MSCodeBase")
CASES = [
    (
        "set_project sets MSCODEBASE_PROJECT_PATH",
        REPO / "src/mcp/tools/indexing_tools.py",
        'os.environ["MSCODEBASE_PROJECT_PATH"] = str(target)',
        "pass  # MUTATED",
        "tests/test_mcp_audit_hardening.py::test_set_project_actually_changes_resolution",
    ),
    (
        "CRLF compare is normalized",
        REPO / "src/core/indexing/index_parser.py",
        "same = disk_text is not None and (",
        "same = False and (",
        "tests/test_mcp_audit_hardening.py::test_crlf_only_difference_does_not_create_a_shadow",
    ),
    (
        "bucket penalty demotes tests",
        REPO / "src/mcp/tools/investigate_tool.py",
        "if _TEST_PATH_RE.search(file) and not _asks_for_tests(query):",
        "if False and not _asks_for_tests(query):",
        "tests/test_mcp_audit_hardening.py::test_merge_prefers_implementation_over_tests_for_code_question",
    ),
    (
        "one grep walk counts the second identifier",
        REPO / "src/mcp/tools/grep_tool.py",
        '"extra_totals": totals[1:],',
        '"extra_totals": [],',
        "tests/test_mcp_audit_hardening.py::test_grep_search_counts_two_patterns_in_one_walk",
    ),
]


def main() -> int:
    ok = True
    for name, path, old, new, test in CASES:
        original = path.read_text(encoding="utf-8")
        before = hashlib.sha256(original.encode()).hexdigest()
        if original.count(old) != 1:
            print(f"SKIP {name}: pattern count {original.count(old)}")
            ok = False
            continue
        path.write_text(original.replace(old, new), encoding="utf-8", newline="")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test, "-q", "-p", "no:cacheprovider"],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            red = proc.returncode != 0
            print(f"{'RED (expected)' if red else 'GREEN (BAD)'} {name}")
            if not red:
                tail = (proc.stdout or "")[-400:]
                print(tail)
                ok = False
        finally:
            path.write_text(original, encoding="utf-8", newline="")
            after = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            if after != before:
                print(f"RESTORE MISMATCH {path}")
                ok = False
    print("MUTATION CHECK", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
