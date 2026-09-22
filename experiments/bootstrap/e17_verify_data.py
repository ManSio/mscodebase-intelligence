# -*- coding: utf-8 -*-
"""E17 data verification: every panel function and every B/D test must resolve.

Fails loudly if any function source or test body cannot be extracted, so the
pilot never silently falls back to "# FUNC NOT FOUND" placeholders.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code, read_test_code  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    funcs = data["functions"]
    print(f"functions: {len(funcs)} | modes: {data['metadata']['modes']}")

    missing_code = []
    missing_tests = []
    bDup = 0
    for f in funcs:
        code = read_function_code(f["file_path"], f["name"])
        if not code:
            missing_code.append(f["name"])
        b = f["modes"]["B_runtime"]["tests"]
        d = f["modes"]["D_shuffled"]["tests"]
        if set(b) & set(d):
            bDup += 1
        for t in b:
            if read_test_code(t) is None:
                missing_tests.append((f["name"], "B", t))
        for t in d:
            if read_test_code(t) is None:
                missing_tests.append((f["name"], "D", t))

    print(f"missing function code: {len(missing_code)} {missing_code[:5]}")
    print(f"missing test bodies:   {len(missing_tests)} {missing_tests[:5]}")
    print(f"B/D overlap functions: {bDup}")

    ok = not missing_code and not missing_tests and bDup == 0
    print("VERIFY DATA:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
