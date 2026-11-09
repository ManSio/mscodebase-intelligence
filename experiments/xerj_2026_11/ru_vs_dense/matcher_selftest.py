"""Selftest for the gold-file matcher: a test file must never count as the gold.

The first version used `path.endswith(gold)` where gold is a basename, so
`tests/test_itsdangerous/test_signer.py` matched `signer.py` and the dense arm
was scored 9/12 instead of 8/12. This test can fail: it asserts the WRONG path
does not match.

Run: python experiments/xerj_2026_11/ru_vs_dense/matcher_selftest.py
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_arm import matches_gold  # noqa: E402


def main() -> int:
    cases = [
        ("src/itsdangerous/signer.py", "itsdangerous", "signer.py", True),
        ("tests/test_itsdangerous/test_signer.py", "itsdangerous", "signer.py", False),
        ("src\\itsdangerous\\signer.py", "itsdangerous", "signer.py", True),
        ("src/iniconfig/_parse.py", "iniconfig", "_parse.py", True),
        ("src/itsdangerous/_json.py", "itsdangerous", "_json.py", True),
        ("src/itsdangerous/_json.py", "itsdangerous", "json.py", False),
        ("src/itsdangerous/signer.py", "iniconfig", "signer.py", False),
    ]
    failures = 0
    for path, repo, gold, expected in cases:
        actual = matches_gold(path, repo, gold)
        status = "ok" if actual == expected else "FAIL"
        if actual != expected:
            failures += 1
        print(f"{status:<4} matches_gold({path!r}, {repo!r}, {gold!r}) = {actual}")
    print(f"\ncases={len(cases)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
