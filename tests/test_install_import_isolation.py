"""Шаг 7 установщика обязан работать в голом интерпретаторе.

`python install.py` запускается тем Python, который есть в PATH (у владельца —
`C:\\Python314\\python.exe`), а зависимости проекта живут в venv расширения
(шаги 5–6 ставят `requirements-lock.txt` туда). Значит модули, которые шаги
установщика импортируют, обязаны импортироваться без third-party пакетов.

Регресс 2026-11-14: `Step 7/12: llama.cpp engine .. No module named 'httpx'`.
`src/providers/reranker/llama_runner.py` импортировал httpx на верхнем уровне,
хотя скачиванию бинаря httpx не нужен. Второй дефект того же пути импорта:
`llama_install._detect_platform()` на импорте вызывал `wmic` (удалён в
Windows 11 24H2) и печатал трейсбек в консоль установки ещё до шага 7.

Интерпретатор «как у владельца» моделируется флагом `-S`: site-packages не
подключаются, PYTHONPATH снимается. Контрольный тест доказывает, что `-S`
действительно прячет зависимости (иначе зелёный результат ничего не значит).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def bare(code: str) -> subprocess.CompletedProcess:
    """Python без site-packages и без PYTHONPATH: «голый» интерпретатор."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    return subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def test_bare_interpreter_really_hides_project_dependencies():
    """Контроль: если `-S` не прячет пакеты, все остальные тесты бесполезны."""
    proc = bare("import httpx")
    assert proc.returncode != 0
    assert "ModuleNotFoundError" in proc.stderr


def test_installer_module_imports_without_third_party_packages():
    proc = bare("import install; print(len(install.STEPS))")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert int(proc.stdout.strip().splitlines()[-1]) >= 12


def _modules_the_installer_imports() -> list[str]:
    """Каждый локальный пакет внутри репозитория, который тянет install.py.

    Не только `src…`: установщик импортирует и `adapters.*` (Zed, сниппеты
    клиентов), и регресс там должен ловиться тем же тестом. Третья сторона сюда
    не попадает: для неё `REPO/<module>.py` не существует.
    """
    import ast

    tree = ast.parse((REPO / "install.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        rel = node.module.replace(".", "/")
        if (REPO / f"{rel}.py").exists() or (REPO / rel / "__init__.py").exists():
            found.add(node.module)
    return sorted(found)


@pytest.mark.parametrize("module", _modules_the_installer_imports())
def test_every_module_the_installer_imports_is_dependency_free(module):
    """Общий случай: не только llama_runner, а всё, что тянут шаги установщика."""
    proc = bare(f"import {module}; print('ok')")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stderr.strip() == "", proc.stderr[-2000:]


def test_llama_runner_imports_without_httpx():
    """Шаг 7 берёт отсюда download_llama_binary/is_installed — им httpx не нужен."""
    proc = bare(
        "from src.providers.reranker.llama_runner import "
        "download_llama_binary, is_installed; print('ok')"
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ok" in proc.stdout


def test_llama_runner_keeps_its_network_api_when_httpx_is_present():
    """Ленивый импорт не должен ломать рантайм: httpx доступен в venv."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import src.providers.reranker.llama_runner as m; "
            "assert callable(m._httpx().AsyncClient); print('ok')",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ok" in proc.stdout


def test_importing_the_llama_install_module_is_silent():
    """Ни одной строки в stderr: `wmic`-трейсбек шёл именно отсюда."""
    proc = bare("import src.providers.reranker.llama_install as m; print(len(m.__all__))")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stderr.strip() == "", proc.stderr[-2000:]


@pytest.mark.skipif(sys.platform != "win32", reason="WinAPI/реестр — только Windows")
def test_cpu_detection_does_not_shell_out():
    """RAM и имя CPU берутся из WinAPI/реестра, не из `wmic`."""
    import src.providers.reranker.llama_install as llama_install

    def boom(*_args, **_kwargs):
        raise AssertionError("CPU detection must not spawn processes")

    original = subprocess.check_output
    subprocess.check_output = boom
    try:
        info = llama_install._detect_cpu()
    finally:
        subprocess.check_output = original

    # На урезанном раннере реестр/WinAPI могут быть недоступны при верном коде;
    # деградация покрыта отдельным тестом ниже, здесь важен сам факт отсутствия спавна.
    assert isinstance(info.get("name"), str) and info["name"]
    assert isinstance(info.get("ram_gb"), int) and info["ram_gb"] >= 0


@pytest.mark.skipif(sys.platform != "win32", reason="WinAPI/реестр — только Windows")
def test_cpu_detection_degrades_when_os_probes_fail(monkeypatch):
    """Если WinAPI/реестр недоступны — словарь остаётся валидным, без исключения."""
    import src.providers.reranker.llama_install as llama_install

    monkeypatch.setattr(llama_install, "_windows_cpu_name", lambda: "")
    monkeypatch.setattr(llama_install, "_windows_ram_gb", lambda: None)
    info = llama_install._detect_cpu()
    assert info["name"] == "unknown"
    assert isinstance(info["cores"], int) and info["cores"] >= 1

def test_the_guard_covers_the_modules_the_installer_actually_imports():
    """Если список опустеет, parametrize даст skip, а не красный тест."""
    found = set(_modules_the_installer_imports())
    assert {
        "adapters.zed.zed_config",
        "adapters.clients.snippets",
        "src.providers.reranker.llama_runner",
    } <= found, found
