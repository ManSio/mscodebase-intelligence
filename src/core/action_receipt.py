"""Action Receipt (ТЗ §11) — верификация "что сделал агент" без крипто.

Принцип (ТЗ §11.1): заявление агента "я сделал X" — не доказательство.
Доказательство — детерминированная команда (`reproducible_by`), которую любой
(человек / агент / CI) может независимо перезапустить и получить тот же вердикт.
Это тот же принцип, что VOR применяет к memory claims, перенесённый на action claims.

Три вердикта (ТЗ §11.4), а не два:
- VERIFIED     — все verification_steps прошли, reproducible_by выполним.
- REFUTED      — хотя бы один шаг явно провалился.
- INCONCLUSIVE — шаг не удалось выполнить (нет окружения/таймаут/нет доступа),
                 НЕ путать с REFUTED (недостаточно наблюдений != отрицательный результат).

Хранилище (UNIVERSAL_ENGINE_PLAN §11 4): receipts — JSONL в системной папке
(data_root/projects/<hash8>/action_receipts.jsonl), тот же паттерн, что
ChangeIntentLedger. Evidence-рефы (hash + path) — в receipt, блобы — по путям;
сам receipt — маленький JSON-узел. Receipts иммутабельны: пере-верификация,
перевернувшая вердикт, = НОВЫЙ receipt, суперседящий старый (никогда не мутировать).
GC (retention): INCONCLUSIVE протухает быстро, VERIFIED/REFUTED дольше.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("action_receipt")

__all__ = [
    "ActionReceipt",
    "ActionReceiptStore",
    "build_receipt",
    "verdict_from_results",
    "reproducible_command",
    "format_receipt",
    "format_receipt_summary",
]


# ══════════════════════════════════════════════════════════════
# Вердикты
# ══════════════════════════════════════════════════════════════
VERDICT_VERIFIED = "VERIFIED"
VERDICT_REFUTED = "REFUTED"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

# error-паттерны, означающие "не удалось выполнить", а не "провалилось".
_INCONCLUSIVE_MARKERS = (
    "не найден в PATH",
    "не найден",
    "таймаут",
    "timeout",
    "превысил",
    "не инициализирован",
    "Не удалось выполнить",
    "недоступен",
    "FileNotFoundError",
    "No such file",
    "нет доступа",
)


@dataclass
class ActionReceipt:
    """Машиночитаемый receipt действия (ТЗ §11.2)."""

    action_id: str
    action_type: str
    claim: str = ""
    before_hash: str = ""
    after_hash: str = ""
    verification_steps: List[Dict[str, Any]] = field(default_factory=list)
    verdict: str = VERDICT_INCONCLUSIVE
    reproducible_by: str = ""
    supersedes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "claim": self.claim,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "verification_steps": self.verification_steps,
            "verdict": self.verdict,
            "reproducible_by": self.reproducible_by,
            "supersedes": self.supersedes,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionReceipt":
        return cls(
            action_id=d.get("action_id", ""),
            action_type=d.get("action_type", ""),
            claim=d.get("claim", ""),
            before_hash=d.get("before_hash", ""),
            after_hash=d.get("after_hash", ""),
            verification_steps=d.get("verification_steps", []),
            verdict=d.get("verdict", VERDICT_INCONCLUSIVE),
            reproducible_by=d.get("reproducible_by", ""),
            supersedes=d.get("supersedes", ""),
            timestamp=d.get("timestamp", ""),
        )


def verdict_from_results(results: List[Dict[str, Any]]) -> str:
    """Выводит вердикт из массива verification-results (ТЗ §11.4).

    Последовательность:
    1. Если хотя бы один шаг среда-заблокирован (INCONCLUSIVE-маркер) и НЕТ
       явных fail — INCONCLUSIVE.
    2. Если хотя бы один шаг failed (verified=False без inconclusive-маркера)
       — REFUTED.
    3. Иначе (все verified) — VERIFIED.
    """
    if not results:
        return VERDICT_INCONCLUSIVE

    has_fail = False
    has_inconclusive = False
    for r in results:
        # Среда-блокировка/не-реальная-проверка (index_sync) — независимо от verified.
        if _is_inconclusive_result(r):
            has_inconclusive = True
            continue
        if not r.get("verified"):
            has_fail = True

    if has_fail:
        return VERDICT_REFUTED
    if has_inconclusive:
        return VERDICT_INCONCLUSIVE
    return VERDICT_VERIFIED


def _is_inconclusive_result(result: Dict[str, Any]) -> bool:
    """Шаг не удалось выполнить (среда), а не провалился (содержимое)?"""
    for err in result.get("errors", []) or []:
        low = str(err).lower()
        for marker in _INCONCLUSIVE_MARKERS:
            if marker.lower() in low:
                return True
    # index_sync: метод не выполняет реальной проверки (ждёт внешней) → INCONCLUSIVE.
    if result.get("action") == "index_sync":
        return True
    return False


def _steps_from_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Конвертирует verification-results от ExecutionContract в шаги receipt.

    Каждый шаг: {check, result: pass|fail|inconclusive, detail}.
    """
    steps: List[Dict[str, Any]] = []
    for r in results:
        action = r.get("action", "unknown")
        detail_bits = []
        if r.get("commit_hash"):
            detail_bits.append(f"hash={r['commit_hash'][:12]}")
        if r.get("commit_message"):
            detail_bits.append(f"msg={str(r['commit_message'])[:40]}")
        if r.get("changed_files"):
            detail_bits.append(f"files={len(r['changed_files'])}")
        if r.get("actual_hash"):
            detail_bits.append(f"actual={str(r['actual_hash'])[:12]}")
        if r.get("expected_hash"):
            detail_bits.append(f"expected={str(r['expected_hash'])[:12]}")
        if r.get("status"):
            detail_bits.append(f"status={r['status']}")
        errors = r.get("errors") or []
        if errors:
            detail_bits.append("; ".join(str(e) for e in errors[:3]))
        if r.get("note"):
            detail_bits.append(str(r["note"]))

        if r.get("verified"):
            step_result = "pass"
        elif _is_inconclusive_result(r):
            step_result = "inconclusive"
        else:
            step_result = "fail"
        steps.append(
            {
                "check": f"verify_{action}",
                "result": step_result,
                "detail": " | ".join(detail_bits) if detail_bits else "",
            }
        )
    return steps


def reproducible_command(action_type: str, file_path: str = "") -> str:
    """Детерминированная команда для независимого перепрогона (ТЗ §11.3/§11.5 3).

    Команды не обязаны быть идеальными; ключевое — они не LLM-суждение и
    могут быть перезапущены в чистом окружении.
    """
    if action_type in ("file_write",):
        _p = file_path or "<file_path>"
        _cmd = "hashlib.sha256(open(r'%s','rb').read()).hexdigest()" % _p
        return 'python -c "import hashlib; print(%s)"' % _cmd
    if action_type == "git_commit":
        return "git --no-pager log -1 --pretty=%B"
    if action_type == "git_push":
        return "git --no-optional-locks status -sb"
    if action_type == "index_sync":
        return "python -m pytest tests/ -q   # либо get_index_status после notify_change"
    return f"# no deterministic reproduction for action_type={action_type}"


def build_receipt(
    action_type: str,
    results: List[Dict[str, Any]],
    *,
    claim: str = "",
    before_hash: str = "",
    after_hash: str = "",
    file_path: str = "",
    action_id: str = "",
    supersedes: str = "",
) -> ActionReceipt:
    """Собирает ActionReceipt из verification-results (этап 1 §11.5)."""
    if not action_id:
        action_id = f"REC-{uuid.uuid4().hex[:6]}"
    steps = _steps_from_results(results)
    return ActionReceipt(
        action_id=action_id,
        action_type=action_type,
        claim=claim,
        before_hash=before_hash,
        after_hash=after_hash,
        verification_steps=steps,
        verdict=verdict_from_results(results),
        reproducible_by=reproducible_command(action_type, file_path),
        supersedes=supersedes,
    )


# ══════════════════════════════════════════════════════════════
# Хранилище (JSONL в системной папке — аналог ChangeIntentLedger)
# ══════════════════════════════════════════════════════════════
class ActionReceiptStore:
    """JSONL-ledger ActionReceipt'ов в системной папке проекта.

    Путь: <data_root>/projects/<hash8>/action_receipts.jsonl — ВНЕ проекта
    (артефакты не пишутся в чужой репозиторий, Задача 4/5).
    Receipts иммутабельны: пере-верификация с новым вердиктом записывается
    как НОВЫЙ receipt (superseded_by), старый не мутируется.
    """

    def __init__(self, project_root: str | Path):
        from src.core.artifact_paths import get_project_dir

        self.path = get_project_dir(Path(project_root)) / "action_receipts.jsonl"
        self._lock = threading.Lock()

    # ── запись / чтение ───────────────────────────────────────

    def record(self, receipt: ActionReceipt) -> bool:
        """Дописывает receipt (append + flush). True при успехе."""
        try:
            line = json.dumps(receipt.to_dict(), ensure_ascii=False)
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            return True
        except OSError as e:
            logger.warning("ActionReceiptStore.record failed: %s", e)
            return False

    def _load_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        entries: List[Dict[str, Any]] = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def get(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает receipt по action_id (последний с таким id)."""
        entries = self._load_all()
        found = None
        for e in entries:
            if e.get("action_id") == action_id:
                found = e  # последнее вхождение побеждает
        return found

    def query(self, limit: int = 20, action_type: str = "") -> List[Dict[str, Any]]:
        """Последние N receipts (опционально по типу), новые в конце."""
        entries = self._load_all()
        if action_type:
            entries = [e for e in entries if e.get("action_type") == action_type]
        return entries[-limit:]

    def count(self) -> int:
        return len(self._load_all())

    # ── retention / GC (этап 4 §11.5) ──────────────────────────
    def gc(
        self,
        *,
        inconclusive_ttl_days: float = 7.0,
        verified_ttl_days: float = 60.0,
        keep_last: int = 200,
    ) -> Dict[str, Any]:
        """Retention: INCONCLUSIVE протухает быстро, VERIFIED/REFUTED дольше.

        Логика:
        - INCONCLUSIVE старше inconclusive_ttl_days — удаляется.
        - VERIFIED/REFUTED старше verified_ttl_days — удаляются.
        - Всегда держим минимум последние keep_last receipts в полном виде.
        Возвращает статистику по удалённым (не перезаписывает исходник при
        ошибке записи — записывает компактную копию).
        """
        if not self.path.exists():
            return {"removed": 0, "kept": 0}

        cutoff_inc = (datetime.now() - timedelta(days=inconclusive_ttl_days)).isoformat()
        cutoff_ok = (datetime.now() - timedelta(days=verified_ttl_days)).isoformat()

        entries = self._load_all()
        kept: List[Dict[str, Any]] = []
        removed = {"INCONCLUSIVE": 0, "VERIFIED": 0, "REFUTED": 0, "UNKNOWN": 0}

        # Всегда сохраняем последние keep_last (независимо от возраста) —
        # предотвращает потерю активных ссылок при редких действиях.
        recent = entries[-keep_last:]
        recent_ids = {e.get("action_id") for e in recent}

        for e in entries:
            ts = e.get("timestamp", "")
            verdict = e.get("verdict", VERDICT_INCONCLUSIVE)
            if e.get("action_id") in recent_ids:
                kept.append(e)
                continue
            if verdict == VERDICT_INCONCLUSIVE:
                if ts and ts <= cutoff_inc:
                    removed["INCONCLUSIVE"] += 1
                    continue
            elif ts and ts <= cutoff_ok:
                removed[verdict] = removed.get(verdict, 0) + 1
                continue
            kept.append(e)

        removed_total = len(entries) - len(kept)

        if removed_total > 0:
            try:
                with self._lock, open(self.path, "w", encoding="utf-8") as f:
                    for e in kept:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
                    f.flush()
            except OSError as e:
                logger.warning("ActionReceiptStore.gc rewrite failed: %s", e)
                return {"removed": 0, "kept": len(kept), "error": str(e)}

        # заново посчитаем exactly
        return {
            "removed": removed_total,
            "kept": len(kept),
            "by_verdict": {k: v for k, v in removed.items() if v},
            "keep_last": keep_last,
        }


def format_receipt(receipt: Dict[str, Any]) -> str:
    """Человекочитаемый вывод receipt для MCP-ответа."""
    lines = [f"🧾 Action Receipt: {receipt.get('action_id', '?')}"]
    lines.append(f"  Action: {receipt.get('action_type', '?')}")
    if receipt.get("claim"):
        lines.append(f"  Claim: {receipt.get('claim')}")
    verdict = receipt.get("verdict", VERDICT_INCONCLUSIVE)
    icon = {"VERIFIED": "✅", "REFUTED": "❌", "INCONCLUSIVE": "⚪"}.get(verdict, "❔")
    lines.append(f"  Verdict: {icon} {verdict}")
    if receipt.get("before_hash"):
        lines.append(f"  before_hash: {str(receipt['before_hash'])[:16]}...")
    if receipt.get("after_hash"):
        lines.append(f"  after_hash: {str(receipt['after_hash'])[:16]}...")
    if receipt.get("supersedes"):
        lines.append(f"  supersedes: {receipt['supersedes']}")
    if receipt.get("reproducible_by"):
        lines.append(f"  Reproducible by: {receipt['reproducible_by']}")
    steps = receipt.get("verification_steps") or []
    if steps:
        lines.append("  Verification steps:")
        for s in steps:
            icon_s = {"pass": "✅", "fail": "❌", "inconclusive": "⚪"}.get(
                s.get("result"), "❔"
            )
            detail = s.get("detail", "")
            lines.append(f"    {icon_s} {s.get('check', '?')} {detail}".rstrip())
    lines.append(f"  Timestamp: {receipt.get('timestamp', '?')}")
    return "\n".join(lines)


def format_receipt_summary(receipts: List[Dict[str, Any]]) -> str:
    """Компактная сводка списка receipts (для query/audit)."""
    if not receipts:
        return "🧾 Action Receipts: нет записей"
    lines = [f"🧾 Action Receipts ({len(receipts)}):"]
    for r in receipts:
        verdict = r.get("verdict", VERDICT_INCONCLUSIVE)
        icon = {"VERIFIED": "✅", "REFUTED": "❌", "INCONCLUSIVE": "⚪"}.get(verdict, "❔")
        ts = (r.get("timestamp") or "")[:19]
        lines.append(
            f"  {icon} {r.get('action_id', '?')} "
            f"{r.get('action_type', '?')} @ {ts}"
        )
    return "\n".join(lines)
