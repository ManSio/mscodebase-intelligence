"""
Тесты экстрактора env-доступов (ported from codebase-memory-mcp, MIT DeusData 2025).

Покрывает контракт из задачи §6:
  - Позитивные случаи для всех целевых языков
  - Негативные (нет env-имени, невалидный ключ, вложенный доступ, голый pattern)
  - Не-дублирование (один доступ = одна запись)
"""
import tempfile
from pathlib import Path

import pytest

from src.core.indexing.parser import CodeParser


@pytest.fixture
def tmp_py():
    """Создать .py файл с заданным кодом, вернуть Path."""
    fd, name = tempfile.mkstemp(suffix=".py")
    p = Path(name)
    p.write_text("", encoding="utf-8")
    yield p
    p.unlink(missing_ok=True)


def _make_ext(suffix: str, content: str) -> Path:
    # На Windows mkstemp возвращает открытый handle — если не закрыть,
    # дальнейший unlink() падает с PermissionError. Используем
    # NamedTemporaryFile с явным закрытием.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        name = f.name
    return Path(name)


def _keys(accesses):
    """Множество env_key из списка доступов."""
    return {a["env_key"] for a in accesses}


def _lines(accesses, key):
    """Строки, на которых встретился env_key."""
    return sorted(a["line"] for a in accesses if a["env_key"] == key)


# ── Позитивные кейсы (контракт §6) ─────────────────────────────────────────


def test_python_os_getenv():
    src = """
import os
def get_token():
    return os.getenv("TOKEN")
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "TOKEN" in _keys(accesses)
        # enclosing_function — QN функции get_token
        tok = [a for a in accesses if a["env_key"] == "TOKEN"][0]
        assert tok["enclosing_function"] == "get_token"
        assert tok["line"] == 4
    finally:
        p.unlink(missing_ok=True)


def test_python_os_environ_subscript():
    src = """
import os
def f():
    port = os.environ["DB_PORT"]
    return port
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "DB_PORT" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_python_os_environ_get_call():
    src = """
import os
def f():
    return os.environ.get("APP_PORT")
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "APP_PORT" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_python_os_environ_dot_access():
    src = """
import os
def f():
    return os.environ.SECRET_KEY
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "SECRET_KEY" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_js_process_env_dot():
    src = """
const x = process.env.API_KEY;
function f() { return process.env.DB_HOST; }
"""
    p = _make_ext(".js", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "API_KEY" in _keys(accesses)
        assert "DB_HOST" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_js_process_env_subscript():
    src = """
const secret = process.env["MY_SECRET"];
"""
    p = _make_ext(".js", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "MY_SECRET" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_typescript_process_env_subscript():
    src = """
const x: string = process.env["TS_VAR"];
"""
    p = _make_ext(".ts", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "TS_VAR" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_go_os_getenv_and_lookupenv():
    src = """
package main
import "os"
func main() {
    home := os.Getenv("HOME")
    _, ok := os.LookupEnv("FOO")
    _ = home
    _ = ok
}
"""
    p = _make_ext(".go", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "HOME" in _keys(accesses)
        assert "FOO" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_rust_env_var():
    src = """
fn f() -> Option<String> {
    let x = std::env::var("RUST_LOG").ok();
    let y = env::var("PATH");
    (x, y)
}
"""
    p = _make_ext(".rs", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "RUST_LOG" in _keys(accesses)
        assert "PATH" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_c_getenv():
    src = """
#include <stdlib.h>
int main(void) {
    return getenv("PATH") ? 1 : 0;
}
"""
    p = _make_ext(".c", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "PATH" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_ruby_env_subscript():
    src = """
def fetch
  ENV["GEM_HOME"]
end
"""
    p = _make_ext(".rb", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "GEM_HOME" in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


# ── Негативные кейсы (контракт §6) ─────────────────────────────────────────


def test_no_env_name_for_local_var():
    """os.getenv("local_var") — нет заглавных, отбрасывается."""
    src = """
import os
def f():
    return os.getenv("local_var")
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        # local_var не пройдёт is_env_var_name (нет A-Z)
        assert "local_var" not in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_bare_os_environ_no_record():
    """Голый os.environ без . [...] после — НЕ даёт запись."""
    src = """
import os
x = os.environ
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        # Пустой pattern после . — текст 'os.environ', len(pat)=11, ch=text[11]='' (нет)
        # Алгоритм: tail_idx >= len(text) → continue
        assert accesses == []
    finally:
        p.unlink(missing_ok=True)


def test_bare_process_env_no_record():
    """Голый process.env — НЕ даёт запись."""
    src = """
const x = process.env;
"""
    p = _make_ext(".js", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert accesses == []
    finally:
        p.unlink(missing_ok=True)


def test_nested_member_not_env():
    """process.env.foo.bar — key='foo.bar' содержит точку, отбрасывается."""
    src = """
const x = process.env.foo.bar;
"""
    p = _make_ext(".js", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        # cbm: key содержит '.' → отбрасывается
        # Этот кейс покрывает: голый process.env НЕ даёт запись, и
        # process.env.foo.bar НЕ даёт запись (вложенный доступ).
        # Но process.env.foo (без .bar) тоже НЕ даст — нет заглавных.
        assert "foo.bar" not in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_single_char_key_rejected():
    """Ключ длиной 1 не проходит is_env_var_name (len < 2)."""
    # os.environ["X"] — длина 1, A-Z есть, но len < 2
    src = """
import os
def f():
    return os.environ["X"]
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "X" not in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_non_env_call_not_matched():
    """Произвольный вызов (не env-func) не матчится."""
    src = """
def f():
    return some_module.getenv("FOO")
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        # callee 'some_module.getenv' нет в ENV_FUNCS["python"] (там "os.getenv")
        assert "FOO" not in _keys(accesses)
    finally:
        p.unlink(missing_ok=True)


def test_unsupported_extension_returns_empty():
    """Файлы без грамматики — пустой список, не ошибка."""
    p = _make_ext(".md", "# Hello\n")
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert accesses == []
    finally:
        p.unlink(missing_ok=True)


# ── Не-дублирование (контракт §6) ─────────────────────────────────────────


def test_no_duplicate_records_for_single_access():
    """Один os.getenv("X") = одна запись (continue в walker'е, не спускаемся)."""
    src = """
import os
def f():
    return os.getenv("UNIQUE_KEY")
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        uniq_records = [a for a in accesses if a["env_key"] == "UNIQUE_KEY"]
        assert len(uniq_records) == 1
    finally:
        p.unlink(missing_ok=True)


def test_multiple_calls_in_different_lines_each_recorded():
    """Два разных вызова на разных строках — две записи."""
    src = """
import os
def f():
    a = os.getenv("FIRST_KEY")
    b = os.getenv("SECOND_KEY")
    return a, b
"""
    p = _make_ext(".py", src)
    try:
        accesses = CodeParser().extract_env_accesses(p)
        assert "FIRST_KEY" in _keys(accesses)
        assert "SECOND_KEY" in _keys(accesses)
        assert len(accesses) == 2
    finally:
        p.unlink(missing_ok=True)


# ── SymbolIndex storage (integration) ──────────────────────────────────────


def test_symbol_index_stores_and_retrieves():
    """SymbolIndex.add_env_accesses → get_env_accesses round-trip."""
    from src.core.indexing.symbol_index import SymbolIndex

    si = SymbolIndex()
    si.add_env_accesses("/tmp/fake.py", [
        {"env_key": "FOO", "enclosing_function": "f", "line": 1, "file": "/tmp/fake.py"},
        {"env_key": "FOO", "enclosing_function": "g", "line": 5, "file": "/tmp/fake.py"},
        # Дубликат (тот же key+line) — должен быть отброшен
        {"env_key": "FOO", "enclosing_function": "dup", "line": 1, "file": "/tmp/fake.py"},
        {"env_key": "BAR", "enclosing_function": "f", "line": 2, "file": "/tmp/fake.py"},
    ])
    rows = si.get_env_accesses("/tmp/fake.py")
    assert len(rows) == 3  # 3, не 4 — дубль отброшен
    keys = {r["env_key"] for r in rows}
    assert keys == {"FOO", "BAR"}


def test_symbol_index_remove_file_clears_env():
    """remove_file должен чистить env_accesses (нет phantom-записей)."""
    from src.core.indexing.symbol_index import SymbolIndex

    si = SymbolIndex()
    si.add_env_accesses("/tmp/fake.py", [
        {"env_key": "X", "enclosing_function": "f", "line": 1, "file": "/tmp/fake.py"},
    ])
    assert si.get_env_accesses("/tmp/fake.py")
    si.remove_file("/tmp/fake.py")
    assert si.get_env_accesses("/tmp/fake.py") == []
