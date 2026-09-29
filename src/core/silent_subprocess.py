"""silent_subprocess.py — глобальный guard от мигающих консолей на Windows.

Патчит subprocess.Popen/run/check_output/check_call: на win32 всегда
добавляет CREATE_NO_WINDOW + STARTUPINFO(SW_HIDE), если вызывающий их
не задал явно. Импортировать ПЕРВЫМ в entry-point (src/main.py).

Идемпотентен: повторный import/apply() — no-op.
"""
from __future__ import annotations

import subprocess
import sys

_APPLIED = False


def apply() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    if sys.platform != "win32":
        return

    _CNW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _SW_HIDE = getattr(subprocess, "SW_HIDE", 0) or 0
    try:
        from subprocess import STARTF_USESHOWWINDOW as _SW_FLAG  # type: ignore
    except ImportError:
        _SW_FLAG = 0

    def _silent_startupinfo():
        si = None
        try:
            si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
            si.dwFlags |= _SW_FLAG
            si.wShowWindow = _SW_HIDE
        except (AttributeError, TypeError):
            pass
        return si

    _orig_popen = subprocess.Popen

    class _SilentPopen(_orig_popen):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", _CNW)
            # CREATE_NO_WINDOW может быть скомбинирован — OR, не замена
            try:
                kwargs["creationflags"] |= _CNW
            except TypeError:
                pass
            try:
                kwargs.setdefault("startupinfo", _silent_startupinfo())
            except (AttributeError, OSError, TypeError):
                pass
            super().__init__(*args, **kwargs)

    _orig_run = subprocess.run
    _orig_check_output = subprocess.check_output
    _orig_check_call = subprocess.check_call

    def _with_flags(fn):
        def wrapper(*args, **kwargs):
            kwargs.setdefault("creationflags", _CNW)
            try:
                kwargs["creationflags"] |= _CNW
            except TypeError:
                pass
            # startupinfo поддерживают Popen/run/check_* — os-уровень, безопасно
            try:
                kwargs.setdefault("startupinfo", _silent_startupinfo())
            except (AttributeError, OSError, TypeError):
                pass
            return fn(*args, **kwargs)

        return wrapper

    subprocess.Popen = _SilentPopen  # type: ignore[misc]
    subprocess.run = _with_flags(_orig_run)  # type: ignore[method-assign]
    subprocess.check_output = _with_flags(_orig_check_output)  # type: ignore[method-assign]
    subprocess.check_call = _with_flags(_orig_check_call)  # type: ignore[method-assign]


apply()
