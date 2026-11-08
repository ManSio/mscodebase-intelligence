"""Fetch the two pinned external repos into the audit cache (outside the repo).

Rules (AGENTS §19.10): read-only, outside the project, named
<owner>__<repo>__<ref>-<short-sha>, with a README_DO-NOT-EDIT.md next to it.
Prints `git rev-parse HEAD` so the pin is checked before anything runs.
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CACHE = Path(r"C:\Users\misha\AppData\Local\mscodebase\audit-cache\xerj-2026-11")
REPOS = [
    ("pallets", "itsdangerous", "672971d66a2e"),
    ("pytest-dev", "iniconfig", "a9e0ad14bcd0"),
]
README = """# DO NOT EDIT

Read-only reference clones for experiments/xerj_2026_11 (E2 gold sets).
Never commit, never push, never edit in place; build gold by reading, then
measure elsewhere. Re-clone if the pin check below fails.
"""


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "README_DO-NOT-EDIT.md").write_text(README, encoding="utf-8")
    for owner, repo, pin in REPOS:
        target = CACHE / f"{owner}__{repo}__HEAD-{pin[:7]}"
        if not (target / ".git").exists():
            code, out = run(["git", "clone", "--quiet", "--no-checkout",
                             f"https://github.com/{owner}/{repo}.git", str(target)])
            if code != 0:
                print(f"CLONE FAILED {owner}/{repo}: {out[:200]}")
                return 1
        code, out = run(["git", "fetch", "--quiet", "origin", pin], cwd=target)
        code, out = run(["git", "checkout", "--quiet", "--detach", pin], cwd=target)
        if code != 0:
            print(f"CHECKOUT FAILED {owner}/{repo}@{pin}: {out[:200]}")
            return 1
        code, head = run(["git", "rev-parse", "HEAD"], cwd=target)
        head = head.strip()
        ok = head.startswith(pin[:12])
        print(f"{owner}/{repo}: HEAD={head[:12]} pin={pin[:12]} {'OK' if ok else 'MISMATCH'}")
        if not ok:
            return 1
        files = sum(1 for p in target.rglob("*.py") if ".git" not in p.parts)
        print(f"  python files: {files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
