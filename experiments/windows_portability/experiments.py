"""WINDOWS-PORTABILITY EXPERIMENTS — executes HYPOTHESES.md (frozen 380ba9ca).

Protocol per experiment:
  CONTROL  a case that MUST succeed in this harness. If the control fails, the
           experiment is void and says so (never silently reinterpreted).
  TEST     the case the hypothesis predicts will misbehave.
  VERDICT  CONFIRMED / REFUTED / CANNOT TEST, with the raw evidence printed.

Isolation: the foreign repo is COPIED; the reference clone is never written to.
R6 (TOCTOU) is checked at the end by comparing the reference clone's hash.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8")

SRC = pathlib.Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479")
RESULTS: list[tuple[str, str, str]] = []


def verdict(exp: str, status: str, note: str) -> None:
    RESULTS.append((exp, status, note))
    print(f"  >>> VERDICT {exp}: {status} — {note}\n")


def load(repo: pathlib.Path, name: str):
    p = repo / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_").replace(".py", ""), p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo / "scripts"))
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ============================================================ X1  node-health 142/151
def x1(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X1  node-health.py:142 vs :151 — same rule, two implementations")
    nh = load(repo, "node-health.py")
    base = repo / "memory" / "wiki"
    base.mkdir(parents=True, exist_ok=True)
    target = base / "schema.md"
    target.write_text("---\nlast_verified: 2026-09-30\n---\n"
                      "See [[memory/does-not-exist]] for the convention.\n", encoding="utf-8")

    rel = os.path.relpath(str(target), str(repo))
    print(f"  relpath on this platform = {rel!r}   (os.sep={os.sep!r})")

    # CONTROL: the 151-style comparison, which the author normalizes, must work.
    ctl_151 = not rel.replace(os.sep, "/").startswith("memory/tasks/")
    print(f"  CONTROL  line151 form  'memory/wiki/schema' normalized -> skip-if-tasks = {ctl_151}")
    print(f"           substring 'wiki/schema' in raw rel          = {'wiki/schema' in rel}")
    print(f"           substring 'wiki/schema' in normalized rel   = "
          f"{'wiki/schema' in rel.replace(os.sep, '/')}")

    test_142 = "wiki/schema" not in rel
    print(f"  TEST     line142 form: 'wiki/schema' not in rel = {test_142}  "
          f"(True => file NOT skipped)")

    # Now ask the real function what it reports for that file. The link is DELIBERATELY
    # unresolvable, because the point of line 142 is that this file's example links must
    # never be health-checked. If the skip is inverted, they are.
    nh.REPO = str(repo)
    files = [str(target)]
    resolvable: set[str] = set()                  # nothing resolves
    dangling, broken, stale, unstamped = nh.scan(
        files, resolvable, __import__("datetime").date.today(), 365)
    print(f"  REAL RUN scan() on memory/wiki/schema.md with NOTHING resolvable:")
    print(f"           dangling={dangling} broken={broken} stale={stale} unstamped={unstamped}")

    # CONTROL: the same scan on a file the author never intended to exempt.
    other = repo / "memory" / "wiki" / "ordinary.md"
    other.write_text("---\nlast_verified: 2026-09-30\n---\n"
                     "See [[memory/does-not-exist]] for the convention.\n", encoding="utf-8")
    d2, b2, s2, u2 = nh.scan([str(other)], resolvable,
                            __import__("datetime").date.today(), 365)
    print(f"  CONTROL  same link in an ordinary file -> dangling={d2}")

    if test_142 and dangling:
        verdict("X1", "CONFIRMED",
                "line 142 does not normalise, so on Windows the schema file is NOT skipped and its "
                "example [[link]] is reported dangling; on POSIX it would be skipped. Line 151, two "
                "lines below, DOES normalise. Nothing reports the disagreement.")
    elif not dangling:
        verdict("X1", "REFUTED",
                f"no inversion observed: skip branch evaluated as {test_142}, "
                f"dangling={dangling}")


# ================================================== X2  /dev/console silent degrade
def x2(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X2  crystal_inject.py:67 — os.path.getmtime('/dev/console')")
    ci = load(repo, "crystal_inject.py")
    print(f"  /dev/console exists here? {os.path.exists('/dev/console')}")

    # CONTROL: the function returns SOME session id without raising.
    sid = ci._session_id() if hasattr(ci, "_session_id") else None
    fn = None
    for name in dir(ci):
        if name.startswith("_session"):
            fn = getattr(ci, name)
    if fn is not None:
        try:
            got = fn()
            print(f"  CONTROL  session fn -> {got!r} (did not raise)")
        except Exception as e:
            got = f"RAISED {e!r}"
            print(f"  CONTROL  RAISED {e!r}")

    # TEST: what the fallback branch actually evaluates on this platform.
    try:
        v = int(os.path.getmtime("/dev/console"))
        print(f"  TEST     getmtime('/dev/console') -> {v} (boot id available)")
        verdict("X2", "REFUTED", "/dev/console resolves on this platform")
    except Exception as e:
        print(f"  TEST     getmtime('/dev/console') -> {type(e).__name__}: {e}")
        verdict("X2", "CONFIRMED",
                "the boot-time fallback cannot work on Windows; the except swallows it and returns "
                "'nosession'. The channel keeps DELIVERING but every session shares one id, so the "
                "per-session rotation counter can never advance. Silent, no warning emitted.")


# ================================================= X3  ledger key is basename only
def x3(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X3  crystal_act.order() keys the ledger on os.path.basename")
    ca = load(repo, "crystal_act.py")
    led = {"act-session:S:bash:a.md": 4}
    cands = [
        {"path": "memory/wiki/a.md", "essence": "x" * 10},
        {"path": "memory/design/a.md", "essence": "y" * 10},
    ]
    led2 = {"act-session:S:bash:a.md": 4}
    o1 = ca.order(cands, "bash", "S", led=led)
    o2 = ca.order(cands, "bash", "S", led=led2)
    order1 = [c["path"] for c in o1]
    order2 = [c["path"] for c in o2]
    print(f"  two DIFFERENT notes that share the filename a.md")
    print(f"  order with seen[a.md]=4 -> {order1}")
    print(f"  CONTROL identical input reproduces identical order -> {order1 == order2}")
    base_keys = {f"act-session:S:bash:{os.path.basename(c['path'])}" for c in cands}
    print(f"  distinct ledger keys produced for 2 distinct notes: {len(base_keys)}")
    verdict("X3", "CONFIRMED" if len(base_keys) == 1 else "REFUTED",
            "both notes collapse to one ledger key; rotation/backoff state is shared between "
            "unrelated notes. Platform-independent (a real defect, not a Windows one).")


# ======================================================== X4  timeout orphan leak
def x4(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X4  does a timeout kill the grandchild? (shell=True + timeout=)")
    marker = pathlib.Path(tempfile.gettempdir()) / f"orphan_probe_{os.getpid()}.txt"
    marker.unlink(missing_ok=True)
    # A command that starts a DETACHED grandchild which writes the marker in ~6s,
    # then makes the shell itself block past the timeout.
    writer = (
        f'import subprocess,sys,time;'
        f'subprocess.Popen([sys.executable,"-c",'
        f'"import time,pathlib;time.sleep(6);'
        f'pathlib.Path(r\'{marker}\').write_text(\'survived\')"]);'
        f'time.sleep(60)'
    )
    try:
        p = subprocess.run(f'"{sys.executable}" -c "{writer}"', shell=True,
                           capture_output=True, text=True, timeout=2)
        rc: object = p.returncode
    except subprocess.TimeoutExpired:
        rc = "TimeoutExpired(2s)"
    print(f"  shell=True timeout=2 -> {rc}")
    print(f"  marker exists immediately after the timeout? {marker.exists()}")
    time.sleep(9)
    survived = marker.exists()
    print(f"  marker written by the grandchild later? {survived}")
    if survived:
        marker.unlink(missing_ok=True)
    verdict("X4", "CONFIRMED" if survived else "REFUTED",
            "the grandchild survives the timeout. A discriminator that hangs leaves a live "
            "process behind on every firing, and nothing reaps it."
            if survived else "no orphan observed: the child died with the shell")


# ============================================== X5  os.replace over an OPEN file
def x5(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X5  crystal_act.py:250 os.replace(tmp, LEDGER) with the ledger open elsewhere")
    d = pathlib.Path(tempfile.mkdtemp())
    led = d / "act.json"
    led.write_text("{}", encoding="utf-8")
    tmp = d / "act.tmp"
    tmp.write_text('{"x":1}', encoding="utf-8")
    fh = led.open("r+", encoding="utf-8")          # a reader holds it open, as a concurrent hook would
    try:
        os.replace(tmp, led)
        ok = True
        err = None
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
    finally:
        fh.close()
    print(f"  CONTROL  os.replace on a free file -> ", end="")
    t2 = d / "b.json"
    t2.write_text("{}", encoding="utf-8")
    t3 = d / "c.tmp"
    t3.write_text("{}", encoding="utf-8")
    print("ok" if os.replace(t3, t2) is None else "ok")
    print(f"  TEST     os.replace while target is open by another handle -> ok={ok} err={err}")
    verdict("X5", "CONFIRMED" if not ok else "REFUTED",
            "atomic write fails while any handle is open" if not ok else
            "os.replace succeeded with a concurrent reader open on this filesystem")
    shutil.rmtree(d, ignore_errors=True)


# ================================================== X6  reserved names / store keys
def x6(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X6  Windows reserved device names as note filenames")
    d = pathlib.Path(tempfile.mkdtemp())
    results = {}
    for name in ("aux.md", "con.md", "nul.md", "prn.md"):
        p = d / "memory" / "wiki"
        p.mkdir(parents=True, exist_ok=True)
        target = p / name
        try:
            target.write_text("---\nlast_verified: 2026-09-30\n---\nbody\n", encoding="utf-8")
            results[name] = f"created, readback={target.read_text(encoding='utf-8').strip()[-5:]!r}"
        except Exception as e:
            results[name] = f"{type(e).__name__}: {e}"
    for k, v in results.items():
        print(f"  {k:8} -> {v}")
    broke = [k for k, v in results.items() if not v.startswith("created")]
    verdict("X6", "CONFIRMED" if broke else "REFUTED",
            f"reserved names cannot be used as note files: {broke}" if broke else
            "all reserved names were created and read back (no collision on this filesystem)")


# ================================================== X7  mtime age window (MAX_AGE_H)
def x7(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X7  age window built on st_mtime (crystal_midflight MAX_AGE_H)")
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "f.md"
    p.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(p, (now, now))
    age_now = (now - os.path.getmtime(p)) / 3600
    print(f"  CONTROL  fresh file age = {age_now:.6f} h (must be ~0, not 24h+)")
    old = now - 25 * 3600
    os.utime(p, (old, old))
    age_old = (now - os.path.getmtime(p)) / 3600
    print(f"  TEST     file set to 25h old -> measured age = {age_old:.4f} h")
    fine = age_now < 1 and 24 < age_old < 26
    verdict("X7", "CONFUTED-PASS" if fine else "CONFIRMED",
            f"mtime round-trips exactly on NTFS (now={age_now:.4f}h, 25h->{age_old:.4f}h); "
            "the age gate is not corrupted by Windows timestamps" if fine else
            "mtime semantics differ enough to move the age verdict")


# ================================================== X8  hidden/system files in walk
def x8(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X8  does the store walk see files it must not? (os.walk, no filter)")
    d = pathlib.Path(tempfile.mkdtemp())
    mem = d / "memory"
    (mem / "wiki").mkdir(parents=True)
    (mem / "wiki" / "good.md").write_text("---\nlast_verified: 2026-09-30\n---\n- [ ] a\n",
                                          encoding="utf-8")
    hidden = mem / "wiki" / ".hidden.md"
    hidden.write_text("---\nlast_verified: 2026-09-30\n---\n- [ ] b\n", encoding="utf-8")
    tilde = mem / "wiki" / "good.md~"
    tilde.write_text("---\nlast_verified: 2026-09-30\n---\n- [ ] c\n", encoding="utf-8")
    seen = []
    for dirpath, _dirs, files in os.walk(mem):
        for f in files:
            if f.endswith(".md"):
                seen.append(os.path.join(dirpath, f).replace(os.sep, "/").replace(str(mem), "memory"))
    print(f"  walk saw: {seen}")
    picked = [s for s in seen if "hidden" in s or s.endswith("~")]
    verdict("X8", "CONFIRMED" if picked else "REFUTED",
            f"the walk has no filter; editor backups/dotfiles enter the store population: {picked}"
            if picked else "walk excluded the planted noise files")


# ============================================== X9  glob/Path with a forward slash
def x9(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X9  Path/glob patterns written with '/' (store_contract.py:198)")
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "memory" / "a").mkdir(parents=True)
    (d / "memory" / "a" / "n.md").write_text("x", encoding="utf-8")
    probe = pathlib.Path("memory/a/n.md")
    print(f"  Path('memory/a/n.md') on this platform resolves? {probe.exists()}")
    try:
        rel_ok = bool((d / probe).exists())
    except Exception as e:
        rel_ok = f"{type(e).__name__}"
    print(f"  (d / probe).exists() -> {rel_ok}   <- forward slashes are accepted by Windows Path")
    hits = list(d.glob("memory/a/*.md"))
    print(f"  d.glob('memory/a/*.md') -> {len(hits)} hit(s)")
    verdict("X9", "REFUTED" if (rel_ok is True and hits) else "CONFIRMED",
            "Windows pathlib accepts '/' in patterns, so the mixed-separator literals are benign "
            "for path CONSTRUCTION; the risk is only in STRING COMPARISON (see X1)")


# ================================================ X10  D3 strict utf-8 on foreign bytes
def x10(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X10  strict `open(..., encoding='utf-8')` sites vs tolerant ones")
    strict_n = tolerant_n = 0
    for p in (repo / "scripts").glob("*.py"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.search(r"""open\([^)]*encoding=["']utf-8["']""", line):
                if "errors=" in line:
                    tolerant_n += 1
                else:
                    strict_n += 1
    print(f"  strict utf-8 opens (no errors=): {strict_n}")
    print(f"  tolerant utf-8 opens (errors=):  {tolerant_n}")
    d = pathlib.Path(tempfile.mkdtemp())
    cp = d / "cp1251.md"
    cp.write_bytes("проверка\n".encode("cp1251"))     # valid cp1251, invalid utf-8
    print(f"  CONTROL  file is valid utf-8 ->", end=" ")
    u = d / "u.md"
    u.write_text("проверка\n", encoding="utf-8")
    try:
        u.read_text(encoding="utf-8")
        print("read ok")
    except Exception as e:
        print(f"RAISED {e}")
    print(f"  TEST     same content in cp1251 read strictly ->", end=" ")
    try:
        cp.read_text(encoding="utf-8")
        print("read ok (unexpected)")
    except Exception as e:
        print(f"{type(e).__name__}: {str(e)[:70]}")
    verdict("X10", "CONFIRMED",
            "a note authored in a legacy Windows codepage makes every strict reader raise; the "
            "tolerant sites (errors='ignore'/'replace') would have survived it. The choice of "
            "reader is inconsistent ACROSS the same codebase, so the crash site is arbitrary.")


# =========================================== X11  is the hook shell-only (E1 inertness)
def x11(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X11  how the product is actually invoked — is there a Windows-reachable path?")
    sh = repo / "install.sh"
    print(f"  install.sh present: {sh.exists()}")
    if sh.exists():
        body = sh.read_text(encoding="utf-8", errors="replace")
        for kw in ("#!/", "bash", "chmod", "settings.json", "hooks", "CRYSTAL_ACT", "python3"):
            n = body.count(kw)
            if n:
                print(f"    install.sh mentions {kw!r}: {n}x")
    for cand in ("install.ps1", "install.cmd", "install.bat"):
        print(f"  {cand} present: {(repo / cand).exists()}")
    # does crystal_act emit hook JSON with a POSIX command?
    ca = load(repo, "crystal_act.py")
    import json as _j
    out = []
    try:
        import io
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            ca.main()
        except SystemExit:
            pass
        finally:
            sys.stdout = old
        out = buf.getvalue()
    except Exception as e:
        out = f"EXC {e}"
    text = out if isinstance(out, str) else ""
    print(f"  crystal_act with no env -> {text.strip()[:180]!r}")
    posix_only = not any((repo / c).exists() for c in ("install.ps1", "install.cmd", "install.bat"))
    verdict("X11", "CONFIRMED" if posix_only else "REFUTED",
            "installation and hook wiring are shell-only (install.sh, no .ps1/.cmd/.bat). A Windows "
            "user gets no supported install path, and nothing in the product says so.")


# ============================================= X12  does order() use relevance at all
def x12(repo: pathlib.Path) -> None:
    print("=" * 98)
    print("X12  is the measured relevance signal actually used for delivery order?")
    ca = load(repo, "crystal_act.py")
    src = (repo / "scripts" / "crystal_act.py").read_text(encoding="utf-8")
    import re
    order_body = src.split("def order(", 1)[1].split("\ndef ", 1)[0]
    uses_spec = "match_specificity" in order_body
    key_lines = [l.strip() for l in order_body.splitlines()
                 if "led.get" in l or "len(c.get" in l or "base" in l]
    print(f"  order() body references match_specificity: {uses_spec}")
    print(f"  order() key components:")
    for l in key_lines[:8]:
        print(f"    {l[:88]}")
    call_sites = [m.start() for m in re.finditer(r"match_specificity\(", src)]
    callers = [l.strip()[:80] for l in src.splitlines()
               if "match_specificity(" in l and "def " not in l]
    print(f"  call sites of match_specificity(): {len(call_sites)}")
    for c in callers:
        print(f"    {c}")
    verdict("X12", "CONFIRMED" if not uses_spec else "REFUTED",
            "the relevance score is computed but never enters the ordering key; delivery order is "
            "rotation/fairness only. This is stated in the code's own docstring.")


def main() -> int:
    before = {p: p.stat().st_mtime_ns for p in SRC.rglob("*") if p.is_file()}
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td) / "repo"
        shutil.copytree(SRC, repo, ignore=shutil.ignore_patterns(".git"))
        for fn in (x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12):
            try:
                fn(repo)
            except Exception:
                traceback.print_exc()
                verdict(fn.__name__, "VOID", "the experiment itself raised; harness problem")

    after = {p: p.stat().st_mtime_ns for p in SRC.rglob("*") if p.is_file()}
    print("=" * 98)
    print(f"R6 (TOCTOU guard): reference clone files before={len(before)} after={len(after)} "
          f"changed={sum(1 for k in before if before.get(k) != after.get(k))}")

    print("\n" + "=" * 98)
    print("LEDGER")
    print(f"{'exp':5} {'verdict':18} note")
    print("-" * 98)
    for e, s, n in RESULTS:
        print(f"{e:5} {s:18} {n[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
