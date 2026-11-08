"""factory — task in, tree of one-action operators, journal, replay check.

    python tools/factory/cli.py ops
    python tools/factory/cli.py plan --task "найди ActionReceipt затем запусти тесты tests/test_write_tools.py"
    python tools/factory/cli.py run  --task "..." --repo D:\\Project\\MSCodeBase
    python tools/factory/cli.py llm  --task "..." --endpoint http://192.168.2.5:1234/v1 --model google/gemma-4-26b-a4b-qat
    python tools/factory/cli.py verify --journal <path> --repo D:\\Project\\MSCodeBase

`run` is the whole loop: brain (rule-based or LLM) → gate → executor → journal.
`verify` is the independent check: hash chain, replayed read-only steps, artifact hashes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ops import describe  # noqa: E402
from plan import from_dict, gate_summary, llm_plan, rule_plan, validate  # noqa: E402
from runtime import Budget, plan_preview, run_plan, verify  # noqa: E402


def _print_tree(root) -> None:
    for line in plan_preview(root):
        print(line)
    summary = gate_summary(root)
    print(f"\ngate: {'PASS' if not summary['errors'] else 'FAIL'} "
          f"nodes={summary['nodes']} primitives={summary['primitives']} ops={summary['ops']}")
    if summary["shell"]:
        print("shell:", "; ".join(str(s) for s in summary["shell"]))
    for err in summary["errors"]:
        print("  !", err)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ops", help="print the operator catalogue")

    p_plan = sub.add_parser("plan", help="decompose the task and show the tree (no execution)")
    p_plan.add_argument("--task", required=True)
    p_plan.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="decompose, execute, write the journal")
    p_run.add_argument("--task", default=None)
    p_run.add_argument("--plan", default=None, help="JSON plan produced elsewhere (brain output)")
    p_run.add_argument("--repo", default=".")
    p_run.add_argument("--journal", default=None)
    p_run.add_argument("--max-steps", type=int, default=25)
    p_run.add_argument("--max-tokens", type=int, default=60000)
    p_run.add_argument("--quiet", action="store_true")
    p_run.add_argument("--decide", action="store_true",
                       help="empty-args primitives are filled by ONE stateless model call each")
    p_run.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL for --decide")
    p_run.add_argument("--model", default=None, help="model id for --decide")

    p_prompt = sub.add_parser("prompt", help="show the exact single-action prompt and its size, offline")
    p_prompt.add_argument("--op", default="grep")
    p_prompt.add_argument("--goal", default="найди ActionReceipt")

    p_llm = sub.add_parser("llm", help="let an OpenAI-compatible model produce the plan, then gate+run")
    p_llm.add_argument("--task", required=True)
    p_llm.add_argument("--endpoint", required=True)
    p_llm.add_argument("--model", required=True)
    p_llm.add_argument("--repo", default=".")
    p_llm.add_argument("--journal", default=None)
    p_llm.add_argument("--dry-run", action="store_true", help="print the gated plan only")

    p_ver = sub.add_parser("verify", help="replay the journal and check artifacts")
    p_ver.add_argument("--journal", required=True)
    p_ver.add_argument("--repo", default=".")
    p_ver.add_argument("--no-rerun", action="store_true", help="do not re-run read-only operators")

    args = parser.parse_args(argv)

    if args.cmd == "ops":
        print(json.dumps(describe(), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "prompt":
        from brain import probe_offline

        print(json.dumps(probe_offline(op=args.op, goal=args.goal), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "plan":
        root = rule_plan(args.task)
        if args.json:
            print(json.dumps(root.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"task: {args.task}\n")
            _print_tree(root)
        return 0 if not validate(root) else 2

    if args.cmd in {"run", "llm"}:
        repo = Path(args.repo).resolve()
        if not (repo / "pyproject.toml").exists() and not (repo / ".git").exists():
            print(f"not a repository: {repo}", file=sys.stderr)
            return 2

        if args.cmd == "llm":
            try:
                root = llm_plan(args.task, args.endpoint, args.model)
            except Exception as exc:  # noqa: BLE001
                print(f"planner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 3
            print(f"task: {args.task}\nplanner: {args.model}\n")
            _print_tree(root)
            if args.dry_run:
                return 0
        elif args.plan:
            data = json.loads(Path(args.plan).read_text(encoding="utf-8-sig"))
            root = from_dict(data.get("root", data))
            if not args.quiet:
                print(f"task: {args.plan}\nplanner: file\n")
                _print_tree(root)
                print()
        else:
            if not args.task:
                print("give --task or --plan", file=sys.stderr)
                return 2
            root = rule_plan(args.task)
            if not args.quiet:
                print(f"task: {args.task}\nplanner: rules\n")
                _print_tree(root)
                print()

        errors = validate(root)
        if errors:
            print("gate refused the plan:", "; ".join(errors), file=sys.stderr)
            return 2

        journal = Path(args.journal) if args.journal else (
            repo / ".factory" / "journal.jsonl")
        budget = Budget(max_steps=getattr(args, "max_steps", 25),
                        max_tokens_est=getattr(args, "max_tokens", 60000))

        def on_step(rec, result):
            if args.quiet:
                return
            head = rec["digest"].splitlines()[0] if rec["digest"] else ""
            print(f"[{rec['seq']:02d}] {rec['node']} {rec['op']:<7} ok  {rec['duration_ms']:>6} ms  "
                  f"sha={str(rec['sha256'])[:12]}  {head[:90]}")

        decider = None
        if getattr(args, "decide", False):
            if not (args.endpoint and args.model):
                print("--decide needs --endpoint and --model", file=sys.stderr)
                return 2
            from brain import decide as brain_decide

            def decider(node, last_digest):
                return brain_decide(endpoint=args.endpoint, model=args.model, node_id=node.id,
                                    op=node.op, goal=root.goal or "", last_digest=last_digest)

        out = run_plan(root, repo, journal, budget, on_step=on_step, decider=decider)
        if not args.quiet:
            print(f"\nstatus: {out['status']}  steps: {out['steps']}  "
                  f"tokens~{out['tokens_est']}  wall: {out['wall_s']}s")
            print(f"journal: {out['journal']}\nhead: {out['journal_hash'][:16]}")
            if out.get("brain_calls"):
                print("\nephemeral calls (one call = one action):")
                for c in out["brain_calls"]:
                    print(f"  {c['node']:<4} {c['op']:<7} prompt~{c['prompt_tokens_est']:>4} tok  "
                          f"out={c['completion_tokens']}  {c['latency_s']:>5}s  err={c['error']}")
            if out["failure"]:
                print("failure:", json.dumps(out["failure"], ensure_ascii=False))
        else:
            print(json.dumps({k: out[k] for k in ("status", "steps", "tokens_est", "wall_s",
                                                  "journal", "journal_hash", "failure")},
                             ensure_ascii=False))
        return 0 if out["status"] == "ok" else 1

    if args.cmd == "verify":
        report = verify(Path(args.journal), Path(args.repo), rerun_readonly=not args.no_rerun)
        if not args.no_rerun:
            pass
        print(json.dumps({k: report[k] for k in ("verdict", "chain_ok", "records", "last_hash")},
                         indent=2, ensure_ascii=False))
        for node in report["nodes"]:
            print(f"  [{node['seq']:02d}] {node['node']:<4} {node['op']:<7} {node['verdict']:<20} "
                  f"{node['detail'][:80]}")
        return 0 if report["verdict"] == "PASS" else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
