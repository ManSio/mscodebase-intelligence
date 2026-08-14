#!/usr/bin/env python3
"""
negative_controls_runner.py — Guard Inventory (протокол Тома / OWP §5.2, P3 research 2026-08-11).

Каждый продакшн-гейт проекта обязан иметь ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: заведомо
сломанный вход, на котором гейт обязан упасть. Только тогда «зелёный гейт»
что-то значит (класс ln.strip(): «проверка, структурно неспособная упасть,
неотличима от рабочей»).

Runner:
  1. manifest.json (scripts/negative_controls/) — реестр записей:
     id / desc / command / fixtures / expected_exit / output_contains / fixture_digest;
  2. для каждой записи запускает negative control и сверяет:
       exit == expected_exit  И  все output_contains-маркеры найдены
     («crash ≠ catch»: exit 1 с traceback без маркера — это НЕ обнаружение);
  3. digest-pinning (Skillselion): sha256 фикстур против fixture_digest —
     правка фикстуры сбрасывает proven → unproven (re-prove — через --pin).

Режимы:
  (default)   — проверить все записи. Exit 0 = все PROVEN; 1 = есть BROKEN/UNPROVEN.
  --self-test — негативный контроль САМОГО runner-а: синтетический guard,
                который не умеет падать, обязан быть классифицирован BROKEN
                (общий exit 1). Доказывает: runner способен упасть.
  --pin       — после успешного прогона (rc+marker ok у всех) переписать
                fixture_digest в manifest.json — явный re-prove после правки
                фикстуры. При BROKEN-записи — отказ (нельзя благословить сломанное).
  --manifest  — альтернативный путь к manifest (для тестов).

Классификация:
  PROVEN    — exit == expected_exit ∧ маркеры найдены ∧ digest совпал
  UNPROVEN  — digest не совпал (фикстура правилась после pin)
  BROKEN    — exit/маркеры не совпали (гейт больше не умеет падать)

Exit 0 = все proven; 1 = иначе. Краш runner-а = exit 1 (crash ≠ catch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = SCRIPT_DIR / "negative_controls" / "manifest.json"
MANIFEST_VERSION = 1
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUN_TIMEOUT = 120

# §5.9 ENCODING SAFETY (Windows): cp1251 не кодирует стрелки/маркеры вывода
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — переключение кодировки опционально
        pass


class InventoryError(Exception):
    """Ошибка схемы/инвентаря — краш ≠ catch, exit 1."""


def _digest_files(files: list[Path]) -> str:
    """Детерминированный дайджест набора фикстур (имя + \0 + содержимое).

    Платформо-независим: CRLF нормализуется в LF — иначе Windows (CRLF в
    рабочем дереве) и CI-checkout (LF) дают разные digest, и инвентарь
    ломается на первом кроссплатформенном прогоне (инцидент 199dbe6b)."""
    h = hashlib.sha256()
    for f in files:
        content = f.read_bytes().replace(b"\r\n", b"\n")
        h.update(f.name.encode("utf-8"))
        h.update(b"\0")
        h.update(content)
        h.update(b"\0")
    return h.hexdigest()


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        raise InventoryError(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != MANIFEST_VERSION:
        raise InventoryError(f"manifest version mismatch: {data.get('version')} (expected {MANIFEST_VERSION})")
    guards = data.get("guards")
    if not isinstance(guards, list) or not guards:
        raise InventoryError("manifest.guards пуст — инвентарь без записей")
    # TC-1: digest пинит байты, не семантику — provocation_type фиксирует намерение
    for entry in guards:
        if not isinstance(entry, dict) or not str(entry.get("provocation_type", "")).strip():
            raise InventoryError(
                f"entry '{entry.get('id', '?')}': provocation_type обязателен (нормативное поле, TC-1)"
            )
    return data


def _resolve_fixtures(entry: dict) -> list[Path]:
    """Path safety: фикстуры обязаны лежать под scripts/ или корнем проекта
    (транзитивные зависимости контроля — чекеры/конфиги в tools/, TC-8)."""
    root = SCRIPT_DIR.parent.resolve()
    files: list[Path] = []
    for rel in entry.get("fixtures", []):
        p = (SCRIPT_DIR / rel).resolve()
        if not (p.is_relative_to(SCRIPT_DIR.resolve()) or p.is_relative_to(root)):
            raise InventoryError(f"entry '{entry['id']}': fixture вне scripts/ и корня проекта: {rel}")
        files.append(p)
    if not files:
        raise InventoryError(f"entry '{entry['id']}': fixtures пуст — digest-pinning бессмыслен")
    return files


def _resolve_bash() -> str | None:
    """Windows: subprocess(['bash']) резолвит в System32\\bash.exe (WSL-шим) —
    CreateProcess ищет system32 ДО PATH, а это WSL-лаунчер без дистрибутива.
    Явно берём bash из PATH (shutil.which ищет только PATH) и отбраковываем WSL-шим."""
    w = shutil.which("bash")
    if not w:
        return None
    win_dir = os.environ.get("WINDIR")
    p = Path(w)
    if win_dir and p.resolve().is_relative_to(Path(win_dir).resolve()):
        return None  # System32\\bash.exe — WSL-шим, не GitBash
    return w


def _run_command(cmd: list[str], timeout: int = RUN_TIMEOUT) -> tuple[int, str]:
    """Запуск negative control. env PYTHON = текущий интерпретатор (для фикстур)."""
    env = dict(os.environ)
    env["PYTHON"] = sys.executable
    env["PYTHONIOENCODING"] = "utf-8"  # дочерние фикстуры печатают в utf-8 (маркеры stable)
    try:
        p = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            timeout=timeout,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (p.stdout or b"").decode("utf-8", "replace")
        return p.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001 — диагностика: crash ≠ catch
        return -1, f"CRASH: {e}"


def _classify(entry: dict, check_digest: bool = True) -> tuple[str, int, str]:
    cmd = list(entry["command"])
    if cmd and cmd[0] == "python":
        cmd[0] = sys.executable
    if cmd and cmd[0] == "bash":
        bash = _resolve_bash()
        if bash is None:
            return "BROKEN", -1, "bash недоступен (нет GitBash; System32\\bash.exe — WSL-шим)"
        cmd[0] = bash

    fixtures = _resolve_fixtures(entry)
    expected = int(entry["expected_exit"])
    markers = entry.get("output_contains", [])
    digest_ok = (not check_digest) or _digest_files(fixtures) == entry.get("fixture_digest", "")

    rc, out = _run_command(cmd)
    marker_ok = all(m in out for m in markers) if markers else True

    if not digest_ok:
        status, detail = "UNPROVEN", "fixture digest изменился после pin — re-prove через --pin"
    elif rc == expected and marker_ok:
        status, detail = "PROVEN", f"rc={rc}, markers ok, digest ok"
    else:
        status, detail = (
            "BROKEN",
            f"rc={rc} (ожидался {expected}), markers={marker_ok}, digest={digest_ok}",
        )
    return status, rc, detail


def _pin_digests(manifest_path: Path, data: dict, guards: list[dict]) -> None:
    for entry in guards:
        entry["fixture_digest"] = _digest_files(_resolve_fixtures(entry))
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_pin_log(manifest_path: Path, guards: list[dict], reason: str) -> Path:
    """TC-10: ревью-запись при --pin (кто/когда/что). Сам по себе лог —
    самоаттестация; целостность — через git-историю/co-signer (v0.5)."""
    from datetime import datetime, timezone

    log_path = manifest_path.parent / "pin_log.json"
    entries: list[dict] = []
    if log_path.exists():
        try:
            loaded = json.loads(log_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = loaded
        except Exception:  # noqa: BLE001 — битый лог не блокирует запись, а перезаписывается
            entries = []
    entry = {
        "pinned_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "digests": {g["id"]: g["fixture_digest"] for g in guards},
    }
    entries.append(entry)
    entries = entries[-50:]  # кап: последние 50 записей
    log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return log_path


def _self_test() -> int:
    """Negative control для runner-а: guard, неспособный упасть, обязан → BROKEN → exit 1."""
    entry = {
        "id": "__self_test__",
        "desc": "runner умеет классифицировать guard, который не умеет падать",
        "command": ["python", "-c", "print('fake always-green guard'); raise SystemExit(0)"],
        "fixtures": [str(DEFAULT_MANIFEST)],  # синтетическая запись — digest считается на лету
        "expected_exit": 1,
        "output_contains": ["always-green"],
        "fixture_digest": _digest_files([DEFAULT_MANIFEST]),
    }
    status, rc, detail = _classify(entry, check_digest=False)
    print(f"  [{status}] __self_test__ — {entry['desc']}\n           {detail}")
    if status != "BROKEN":
        print("SELF-TEST: FAILED — runner не классифицировал неспособный упасть guard как BROKEN")
        return 1
    print("SELF-TEST: PASSED — runner умеет падать (guard без negative control → BROKEN)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard inventory — negative controls (протокол Тома)")
    parser.add_argument("--self-test", action="store_true", help="негативный контроль самого runner-а")
    parser.add_argument("--pin", action="store_true", help="переписать fixture_digest после успешного прогона")
    parser.add_argument("--reason", default="", help="причина re-prove (обязательна для --pin; TC-10 ревью-запись)")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="путь к manifest.json")
    args = parser.parse_args()

    if args.self_test:
        if args.pin:
            print("--self-test и --pin взаимоисключающие")
            return 1
        return _self_test()

    manifest_path = Path(args.manifest).resolve()
    if args.pin and not args.reason.strip():
        print("PIN: отказано — --reason обязателен (ревью-запись: что изменилось и почему re-prove)")
        return 1

    try:
        data = _load_manifest(manifest_path)
    except InventoryError as e:
        # schema-ошибка — чистое сообщение в stdout, а не traceback (developer-facing)
        print(f"INVENTORY ERROR: {e}")
        return 1
    guards: list[dict] = data["guards"]

    print("=== GUARD INVENTORY (negative controls) ===")
    results: list[tuple[dict, str, int, str]] = []
    for entry in guards:
        status, rc, detail = _classify(entry, check_digest=not args.pin)
        results.append((entry, status, rc, detail))
        print(f"  [{status}] {entry['id']} — {entry['desc']}\n           {detail}")

    all_proven = all(status == "PROVEN" for _, status, _, _ in results)

    if args.pin:
        if not all_proven:
            print("PIN: отказано — есть BROKEN/UNPROVEN, сначала чинить (нельзя благословить сломанное)")
            return 1
        _pin_digests(manifest_path, data, guards)
        log_path = _append_pin_log(manifest_path, guards, args.reason.strip())
        print(f"PIN: fixture digests обновлены в {manifest_path.name}")
        print(f"PIN: ревью-запись добавлена в {log_path.name} (reason: {args.reason.strip()[:80]})")

    if all_proven:
        print(f"NEGATIVE CONTROLS: ALL PROVEN ({len(guards)})")
        return 0

    broken = sum(1 for _, s, _, _ in results if s == "BROKEN")
    unproven = sum(1 for _, s, _, _ in results if s == "UNPROVEN")
    print(f"NEGATIVE CONTROLS: FAILED (broken={broken}, unproven={unproven})")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — краш = exit 1 (crash ≠ catch)
        import traceback

        traceback.print_exc()
        sys.exit(1)
