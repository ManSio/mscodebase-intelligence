#!/usr/bin/env python3
"""check_docstrings.py — Check for public functions missing docstrings.

Usage:
    python scripts/check_docstrings.py           # Check all src/ files
    python scripts/check_docstrings.py --fix     # Show what needs fixing

Exit code 1 if missing docstrings found.
"""

import ast
import pathlib
import sys


def check_file(filepath: pathlib.Path) -> list[dict]:
    """Check a Python file for public functions missing docstrings."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        return [{"file": str(filepath), "line": 0, "name": "<parse error>", "error": str(e)}]
    
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private methods (underscore prefix)
            if node.name.startswith("_"):
                continue
            # Skip __init__ and other dunder methods
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            # Check if has docstring
            if not (node.body and isinstance(node.body[0], ast.Expr) 
                    and isinstance(node.body[0].value, ast.Constant)):
                issues.append({
                    "file": str(filepath),
                    "line": node.lineno,
                    "name": node.name,
                    "error": "missing docstring"
                })
    return issues


def main():
    root = pathlib.Path(__file__).parent.parent / "src"
    if len(sys.argv) > 1 and sys.argv[1] == "--fix":
        print("Checking src/ for public functions missing docstrings...")
    
    all_issues = []
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in str(f) or ".pyc" in str(f):
            continue
        issues = check_file(f)
        all_issues.extend(issues)
    
    if all_issues:
        print(f"\nFound {len(all_issues)} public functions missing docstrings:")
        for issue in all_issues:
            rel = issue["file"].replace(str(root.parent) + "\\", "")
            print(f"  {rel}:{issue['line']}: {issue['name']}()")
        sys.exit(1)
    else:
        print(f"OK: All public functions have docstrings")
        sys.exit(0)


if __name__ == "__main__":
    main()
