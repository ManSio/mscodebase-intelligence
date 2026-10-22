"""Independently verify Tom's 2026-10-10 key-matching fix (crystal-memory@7a129db).

Runs the package's OWN functions (matches_ctx / normalize_match / match_scope)
from the raw file at two revisions:
  OLD = 491f385 (parent, before the fix)   -> must reproduce the hole (control)
  NEW = 7a129db (the fix)                  -> must close it, keep legit matches
$0, deterministic, no model.
"""
from __future__ import annotations

import sys
import types
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RAW = "https://raw.githubusercontent.com/Tirthahq/crystal-memory/{rev}/scripts/crystal_act.py"
REVS = {"OLD": "491f385", "NEW": "7a129db"}


def load(rev: str):
    src = urllib.request.urlopen(RAW.format(rev=rev), timeout=30).read().decode("utf-8")
    mod = types.ModuleType(f"crystal_act_{rev}")
    mod.__dict__["__name__"] = f"crystal_act_{rev}"  # NOT "__main__" -> no side effects
    mod.__dict__["__file__"] = str(Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479") / "scripts" / "crystal_act.py")
    exec(compile(src, f"crystal_act_{rev}.py", "exec"), mod.__dict__)
    return mod


# our audited false-fires (key, text) -> NEW: no fire, OLD: fire
FALSE_FIRES = [
    ("cargo", "escargot"),
    ("|tail", "log|tailspin"),
    ("|head", "cmd|headache"),
    ("|grep", "cmd|grepable"),
    ("<<eof", "<<EOFILE"),
]
LEGIT = [  # must match on BOTH
    ("cargo", "cargo build"),
    ("|tail", "log |tail -n 5"),
    ("<<eof", "cat <<EOF\ntext\nEOF"),
]
PREFIX_KEY = ("post-", "POST-notes.md")          # symbol-ended prefix must survive
PREFIX_NEG = ("post-", "repost-notes.md")        # ...but not as a suffix of another word
NORMALIZE = [                                     # must match only on NEW
    ("ssh", "s\u200bsh"),        # zero-width space
    ("ssh", "\u0455sh"),         # Cyrillic dze replaces s
    ("ssh", "s\uff53h"),         # fullwidth
    ("git status", "git\u00a0status"),  # nbsp
    ("git status", "git\u2009status"),  # thin space
]

mods = {k: load(v) for k, v in REVS.items()}


def fires(mod, key, text):
    return mod.matches_ctx({"match": key}, mod.match_scope(text))


print(f"{'case':<28}{'kind':<14}{'OLD':<7}{'NEW':<7}verdict")
bad = 0
for key, text in FALSE_FIRES:
    o, n = fires(mods["OLD"], key, text), fires(mods["NEW"], key, text)
    ok = (o is True) and (n is False)
    bad += (not ok)
    print(f"{key+' vs '+text!r:<28}{'false-fire':<14}{str(o):<7}{str(n):<7}{'OK' if ok else 'FAIL'}")
for key, text in LEGIT:
    o, n = fires(mods["OLD"], key, text), fires(mods["NEW"], key, text)
    ok = (o is True) and (n is True)
    bad += (not ok)
    print(f"{key+' vs '+text!r:<28}{'legit':<14}{str(o):<7}{str(n):<7}{'OK' if ok else 'FAIL'}")
for key, text, want in ((*PREFIX_KEY, True), (*PREFIX_NEG, False)):
    o, n = fires(mods["OLD"], key, text), fires(mods["NEW"], key, text)
    ok = (n is want)
    bad += (not ok)
    print(f"{key+' vs '+text!r:<28}{'prefix':<14}{str(o):<7}{str(n):<7}{'OK' if ok else 'FAIL'}")
for key, text in NORMALIZE:
    o, n = fires(mods["OLD"], key, text), fires(mods["NEW"], key, text)
    ok = (n is True)
    bad += (not ok)
    print(f"{key+' vs '+text!r:<28}{'normalize':<14}{str(o):<7}{str(n):<7}{'OK' if ok else 'FAIL'}")

print(f"\nfailures: {bad}")
print("verdict:", "TOMS-FIX-INDEPENDENTLY-CONFIRMED" if bad == 0 else "DISCREPANCY")
