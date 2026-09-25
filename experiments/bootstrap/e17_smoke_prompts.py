# -*- coding: utf-8 -*-
"""E17 smoke prompts: dump real A/B prompts using the FIXED AST extraction.

Feeds a plain LLM (subagent) so we can observe whether B differs from A.
No LLM calls here.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code, read_tests  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def build_prompt(question: str, code: str, tests) -> str:
    prompt = (
        "You are an expert Python developer. Answer the following question about "
        f"a function in a codebase.\n\nQuestion: {question}\n\nFunction code:\n"
        f"```python\n{code}\n```\n"
    )
    bodies = read_tests(tests)
    if bodies:
        prompt += "\nRelevant tests that exercise this function:\n"
        for body in bodies:
            prompt += f"\n```python\n{body}\n```\n"
    prompt += (
        "\nProvide a clear, accurate explanation of what the function does, its "
        "purpose, inputs, outputs, and any edge cases it handles."
    )
    return prompt


def main() -> None:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    by_id = {f["id"]: f for f in data["functions"]}
    out = []
    for fid in (13, 1):
        f = by_id[fid]
        code = read_function_code(f["file_path"], f["name"])
        if not code:
            print(f"[{fid}] SKIP {f['name']}: code not found")
            continue
        for m in ("A_baseline", "B_runtime"):
            out.append({
                "id": fid,
                "name": f["name"],
                "mode": m,
                "question": f["question"],
                "prompt": build_prompt(f["question"], code, f["modes"][m]["tests"]),
            })
    (ROOT / "experiments/bootstrap/e17_smoke_prompts.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for o in out:
        has_tests = "Relevant tests" in o["prompt"]
        print(f"[{o['id']}] {o['mode']}: len={len(o['prompt']):5} tests_block={has_tests}")
    print("saved -> experiments/bootstrap/e17_smoke_prompts.json")


if __name__ == "__main__":
    main()
