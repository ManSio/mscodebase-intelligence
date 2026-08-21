"""E-08 — live SSRF-suite для GitUrlSource (Фаза 2, R-2).

Проверяет защиту вживую (детерминированные вектора + реальная DNS):
1. Scheme allowlist — ssh/git/file/http отклоняются на парсе.
2. Domain allowlist — не-allowlisted домен отклонён.
3. Credentials в URL — отклонены.
4. Порт — отклонён.
5. DNS/SSRF — хост, резолвящийся в non-global (localhost→loopback), отклонён.
6. Happy-path: github.com резолвится в global IP и клонируется (не-UBER-блок).

НЕ меняет core; только вызывает GitUrlSource и отчитывается.
Запуск: python experiments/universal-engine/e08_ssrf_suite.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE = (Path(tempfile.gettempdir()) / "mscodebase_e08_live_cache").resolve()

CASES = [
    # (url, allowed_domains, ожидаемый kind, описание)
    ("ssh://git@github.com/x/y.git", None, "invalid_scheme", "ssh-схема"),
    ("git://github.com/x/y.git", None, "invalid_scheme", "git-схема"),
    ("file:///etc/passwd", None, "invalid_scheme", "file-схема"),
    ("http://github.com/x/y.git", None, "invalid_scheme", "http (не https)"),
    ("https://evil.example.com/x.git", None, "domain_not_allowed", "домен вне allowlist"),
    ("https://user:pass@github.com/x.git", None, "credentials_in_url", "credentials в URL"),
    ("https://github.com:8443/x.git", None, "invalid_port", "нестандартный порт"),
    ("https://localhost/x/y.git", {"localhost"}, "non_global_ip", "localhost → loopback (SSRF)"),
]

ALLOWED = {"github.com", "gitlab.com", "bitbucket.org"}


def main() -> int:
    from src.sources.git_url import GitUrlSource, GitUrlSourceError

    print("=" * 70)
    print("E-08: SSRF-defence live suite for GitUrlSource")
    print("=" * 70)
    results = []

    for url, domains, expected, desc in CASES:
        allowed = frozenset(domains) if domains else ALLOWED
        src = GitUrlSource(url, CACHE, allowed_domains=allowed, clone_timeout_sec=30)
        try:
            asyncio.run(src.resolve())
            ok, got = False, "NO_ERROR (не отклонил!)"
        except GitUrlSourceError as e:
            ok = e.kind == expected
            got = e.kind
        status = "✅" if ok else "❌"
        print(f"  {status} [{desc}] url={url!r} → got={got!r} expected={expected!r}")
        results.append(ok)

    # Happy-path: github.com — global IP, allowlisted, должен клонироваться
    print("\n  ── happy-path (не-UBER-блок): github.com должен резолвиться в global IP и клонироваться ──")
    try:
        src = GitUrlSource("https://github.com/octocat/Hello-World.git", CACHE, clone_timeout_sec=60)
        path = asyncio.run(src.resolve())
        print(f"  ✅ github.com cloned → {path}")
        results.append(True)
    except GitUrlSourceError as e:
        print(f"  ❌ github.com: {e.kind} — {e}")
        results.append(False)

    ok = all(results)
    print(f"\nE-08 VERDICT: {'PASSED' if ok else 'PARTIAL'} ({sum(results)}/{len(results)})")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — верхний guard эксперимента
        import traceback

        traceback.print_exc()
        sys.exit(1)
