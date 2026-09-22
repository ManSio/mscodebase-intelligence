# -*- coding: utf-8 -*-
"""E17 smoke check: verify the pilot pipeline is not broken.

Reproduces exactly what e17_pilot_answers.py does (read_function_code /
read_test_code / build_prompt) and reports, per mode, whether the prompt
actually contains test code or a "# Test not found" placeholder.
No LLM calls.
"""
import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]


def read_function_code(file_path: str, function_name: str) -> str:
    local = file_path.replace("D:/Project/MSCodeBase/", "")
    p = ROOT / local
    if not p.exists():
        return "# FILE NOT FOUND"
    lines = p.read_text(encoding="utf-8", errors="ignore").split("\n")
    out, inf, ind = [], False, None
    for line in lines:
        if f"def {function_name}" in line or f"async def {function_name}" in line:
            inf, ind = True, len(line) - len(line.lstrip())
            out.append(line)
        elif inf:
            ci = len(line) - len(line.lstrip()) if line.strip() else ind + 1
            if line.strip() and ci <= ind:
                break
            out.append(line)
    return "\n".join(out) if out else "# FUNC NOT FOUND"


def read_test_code(n: str) -> str:
    for tf in (ROOT / "tests").glob("*.py"):
        c = tf.read_text(encoding="utf-8", errors="ignore")
        if f"def {n}" in c or f"class {n}" in c:
            return f"# FOUND {tf.name}"
    return f"# Test not found: {n}"


def main() -> None:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    by_id = {f["id"]: f for f in data["functions"]}
    for fid in (13, 1):
        f = by_id[fid]
        print("=" * 72)
        print(f"[{fid}] {f['name']}  ({f['file_path']})")
        code = read_function_code(f["file_path"], f["name"])
        print(f"  code bytes={len(code)}  head={code[:70].replace(chr(10), ' ')!r}")
        for m in ("A_baseline", "B_runtime", "C_static", "D_shuffled"):
            tests = f["modes"][m]["tests"]
            section = "".join(read_test_code(t) + "\n" for t in tests)
            verdict = "EMPTY(=A)" if not tests else (
                "ALL-NOT-FOUND(=A)" if "not found" in section and "FOUND" not in section
                else "HAS-REAL-TESTS"
            )
            print(f"  {m:12} tests={len(tests)} -> {verdict}  {section[:90]!r}")


if __name__ == "__main__":
    main()
