"""ADR-0004 Propagation Engine — каскадная ретракция зависимых узлов памяти.

Проблема: ручной отзыв узла (intel_retract_memory_node) не затрагивает узлы,
которые опираются на отозванный факт (downstream). Агент продолжает читать
VERIFIED-факты, производные от уже опровергнутого — контаминация
распространяется на несколько узлов памяти.

Решение: при отзыве корневого узла все узлы, явно зависящие от него
(data.depends_on) или заменённые им (superseded_by), помечаются REFUTED
с трассируемой причиной ``PROPAGATED_FROM:<root> | <root_reason>`` и маркером
retract_source="propagation". Каскад транзитивный (BFS по зависимостям),
циклы безопасны (visited-set).

Границы v1 (см. ADR-0004 Implementation Notes):
- Каскад только на ручном отзыве (MCP-тул); авто-отзывы verify-on-read не
  каскадят — их downstream-якоря проверяются независимо.
- restore не каскадит: восстановление downstream — ручное решение агента.
- PropertyGraph-рёбра (MEMORY_*) не вводятся: хранилище памяти — JSON
  (project_memory.json, десятки узлов), обход O(n) на отзыв дёшев.
"""

from typing import Any, Dict, List

__all__ = ["PropagationEngine", "RETRACT_SOURCE_PROPAGATION"]

RETRACT_SOURCE_PROPAGATION = "propagation"
REASON_PREFIX = "PROPAGATED_FROM"


def _dependents_of(nodes: List[Dict], node_id: str) -> List[Dict]:
    """Узлы, зависящие от node_id (data.depends_on) или заменённые им (superseded_by)."""
    result: List[Dict] = []
    for n in nodes:
        if not isinstance(n, dict) or n.get("node_id") == node_id:
            continue
        data = n.get("data")
        deps = data.get("depends_on") if isinstance(data, dict) else None
        if isinstance(deps, list) and node_id in deps:
            result.append(n)
        elif n.get("superseded_by") == node_id:
            result.append(n)
    return result


class PropagationEngine:
    """Вычисление каскадных переходов при отзыве узла памяти (ADR-0004).

    Чистый класс без состояния: вход — сырые узлы из project_memory.json,
    выход — список переходов. Применение переходов — ответственность
    вызывающего (layer.intel_retract_memory_node, тот же RMW под _write_lock).
    """

    @staticmethod
    def find_dependents(nodes: List[Dict], node_id: str) -> List[Dict]:
        """Прямые зависимые узлы (диагностика/тесты, без транзитивности)."""
        return _dependents_of(nodes, node_id)

    @staticmethod
    def retract_cascade(
        nodes: List[Dict], root_id: str, root_reason: str
    ) -> List[Dict[str, Any]]:
        """Транзитивный каскад отзыва зависимых узлов.

        Args:
            nodes: сырые узлы памяти (плоский список).
            root_id: отзываемый узел (сам уже помечен REFUTED вызывающим).
            root_reason: причина отзыва корня — попадает в retract_reason
                зависимых для трассируемости.

        Returns:
            transitions: [{node_id, retract_reason, retract_source}] — узлы,
            которые ДОЛЖНЫ стать REFUTED. Уже REFUTED пропускаются
            (история не перезаписывается, ADR-0002).
        """
        transitions: List[Dict[str, Any]] = []
        visited = {root_id}
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            for n in _dependents_of(nodes, current):
                nid = n.get("node_id")
                if not isinstance(nid, str):
                    continue
                if nid in visited:
                    continue
                visited.add(nid)
                if n.get("status") == "REFUTED":
                    continue
                transitions.append(
                    {
                        "node_id": nid,
                        "retract_reason": f"{REASON_PREFIX}:{root_id} | {root_reason}",
                        "retract_source": RETRACT_SOURCE_PROPAGATION,
                    }
                )
                queue.append(nid)
        return transitions
