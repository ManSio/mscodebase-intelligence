# -*- coding: utf-8 -*-
"""E17 export: split pilot prompts into shard text files for subagent generation.

Why text shards: prompts are large; as JSON each prompt is one long line the
agent file-reader truncates. Plain-text shards with real newlines keep lines
short. Shards are packed by a LINE BUDGET (default 1500) so a subagent can read
a whole shard within its ~2000-line read limit even for large functions.

Output: experiments/bootstrap/e17_shards/shard_<k>.txt plus index.json
Each prompt block:
    === BEGIN id=<id> mode=<mode> name=<name> ===
    <prompt text>
    === END id=<id> mode=<mode> ===
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from e17_extract import read_function_code  # noqa: E402
from e17_pilot_answers import build_prompt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHARDS_DIR = ROOT / "experiments/bootstrap/e17_shards"


def main() -> None:
    data = json.loads(
        (ROOT / "experiments/bootstrap/e17_pilot_data.json").read_text(encoding="utf-8")
    )
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    SHARDS_DIR.mkdir(exist_ok=True)

    func_blocks = []
    for f in data["functions"]:
        code = read_function_code(f["file_path"], f["name"])
        if not code:
            raise SystemExit(f"no source for {f['name']}")
        lines = []
        for mode, mdata in f["modes"].items():
            prompt = build_prompt(f["question"], code, mdata["tests"])
            lines.append(f"=== BEGIN id={f['id']} mode={mode} name={f['name']} ===")
            lines.append(prompt)
            lines.append(f"=== END id={f['id']} mode={mode} ===")
            lines.append("")
        func_blocks.append((f, lines))

    def n_lines(entries: list) -> int:
        return sum(s.count("\n") + 1 for s in entries)

    shards: list = []
    current_funcs: list = []
    current_lines: list = []
    for f, lines in func_blocks:
        if current_lines and n_lines(current_lines) + n_lines(lines) > budget:
            shards.append((current_funcs, current_lines))
            current_funcs, current_lines = [], []
        current_funcs.append(f)
        current_lines.extend(lines)
    if current_lines:
        shards.append((current_funcs, current_lines))

    index = []
    for k, (funcs, lines) in enumerate(shards, 1):
        (SHARDS_DIR / f"shard_{k}.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"shard {k}: {len(funcs)} funcs, {n_lines(lines)} lines")
        for f in funcs:
            for mode in f["modes"]:
                index.append({"shard": k, "id": f["id"], "mode": mode, "name": f["name"]})

    (SHARDS_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"total prompts: {len(index)} across {len(shards)} shards (budget {budget} lines)")


if __name__ == "__main__":
    main()
