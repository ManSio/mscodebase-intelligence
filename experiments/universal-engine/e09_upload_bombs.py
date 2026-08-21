"""E-09 — upload-bomb защита GitUrlSource (Фаза 2, ТЗ §2.1/§4 upload DoS).

Проверяет post-clone лимиты ВЖИВУЮ на локальных изолированных деревьях
(без сети — суть gate: clone уже сделан, бомба обнажается при лимите):
1. too_large     — дерево с размером > max_clone_bytes → GitUrlSourceError(kind="too_large")
2. too_many_files— дерево с числом файлов > max_file_count → kind="too_many_files"
3. OK-путь       — дерево в лимитах → не бросает (пропускает)
4. redirect-check— origin в allowlist: канонический remote.origin.url обязан
                   парситься/остаться в allowlist (иначе GitUrlSourceError).

Используем ЛИМИТЫ ПОНИЖЕННЫЕ до малых значений — тестируем механик, а не
ждём 500MB-клона. Вызываем _post_clone_checks напрямую (единица механизма)
+ _parse_url для редирект-шлейфа.

Запуск: python experiments/universal-engine/e09_upload_bombs.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="mscodebase_e09_")).resolve()


def _mk_tree(name: str, n_files: int, size_bytes: int) -> Path:
    """Создаёт локальное дерево: n_files файлов по ~size_bytes (на один)."""
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    blob = ("x" * 1024)  # ~1KB повторяемый блок
    for i in range(n_files):
        (d / f"f{i:05d}.txt").write_text(
            (blob * (max(1, size_bytes // 1024)))[: max(1, size_bytes)],
            encoding="utf-8",
        )
    return d


def _expect_kind(err_cls, call, expected_kind=None, desc=""):
    """Обёртка: вызывает call, ожидая err_cls с kind (или отсутствие)."""
    try:
        call()
        if expected_kind is None:
            return {"desc": desc, "ok": True, "detail": "no error (expected pass)"}
        return {
            "desc": desc,
            "ok": False,
            "detail": f"НЕ бросил ошибку, ожидался kind={expected_kind}",
        }
    except err_cls as e:
        ok = (expected_kind is None) or (e.kind == expected_kind)
        return {"desc": desc, "ok": ok, "detail": f"kind={e.kind} ({str(e)[:60]})"}


def main() -> int:
    from src.sources.git_url import GitUrlSource, GitUrlSourceError

    print("=" * 70)
    print("E-09: upload-bomb gate (post-clone limits) for GitUrlSource")
    print("=" * 70)

    results = []

    # Кейс 1: слишком большой по размеру (дерево ~500KB > лимит 10KB)
    too_big = _mk_tree("too_big", n_files=50, size_bytes=10_000)  # ~500KB
    src1 = GitUrlSource(
        "https://github.com/x/y.git", TMP,
        max_clone_bytes=10_000, max_file_count=1_000_000,
    )
    results.append(
        _expect_kind(
            GitUrlSourceError, lambda: src1._post_clone_checks(too_big),
            "too_large", "дерево по размеру > max_clone_bytes  → too_large",
        )
    )

    # Кейс 2: слишком много файлов (1000 файлов > лимит 100)
    too_many = _mk_tree("too_many", n_files=1000, size_bytes=100)
    src2 = GitUrlSource(
        "https://github.com/x/y.git", TMP,
        max_clone_bytes=10_000_000, max_file_count=100,
    )
    results.append(
        _expect_kind(
            GitUrlSourceError, lambda: src2._post_clone_checks(too_many),
            "too_many_files", "1000 файлов > max_file_count=100 → too_many_files",
        )
    )

    # Кейс 3: OK-дерево в лимитах — не бросает
    ok_tree = _mk_tree("ok", n_files=5, size_bytes=200)
    src3 = GitUrlSource(
        "https://github.com/x/y.git", TMP,
        max_clone_bytes=10_000_000, max_file_count=1_000_000,
    )
    results.append(
        _expect_kind(
            GitUrlSourceError, lambda: src3._post_clone_checks(ok_tree),
            None, "дерево в лимитах → pass (не бросает)",
        )
    )

    # Кейс 4: редирект-шлейф — origin вне allowlist отклоняется
    redir = _mk_tree("redir", n_files=1, size_bytes=50)
    # руками пропишем remote.origin.url в чужой домен
    subprocess.run(["git", "init", "-q"], cwd=str(redir), check=True)
    subprocess.run(
        ["git", "config", "remote.origin.url", "https://evil.example.com/x.git"],
        cwd=str(redir), check=True,
    )
    src4 = GitUrlSource(
        "https://github.com/x/y.git", TMP,
        max_clone_bytes=10_000_000, max_file_count=1_000_000,
    )
    results.append(
        _expect_kind(
            GitUrlSourceError, lambda: src4._post_clone_checks(redir),
            "domain_not_allowed", "origin вне allowlist → domain_not_allowed",
        )
    )

    # Вывод
    print(f"{'case':<8} {'result':<6} detail")
    print("-" * 70)
    fails = 0
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            fails += 1
        print(f"{'':<8} {mark:<6} {r['desc']}")
        if not r["ok"]:
            print(f"{'':<8}        → {r['detail']}")

    print("-" * 70)
    print(f"E-09: {len(results)} cases — {len(results) - fails} PASSED, {fails} FAILED")
    verdict = "PASSED" if fails == 0 else "FAILED"
    print(f"SMOKE E-09: {verdict}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
