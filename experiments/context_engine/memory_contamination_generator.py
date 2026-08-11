#!/usr/bin/env python3
"""
Memory Contamination — генератор фактов-мутаций (facts v3, N=50).

Зачем: измерить РЕАЛЬНОЕ распределение «голоса кода» (SUPPORT/CONTRADICT/SILENT)
на сгенерированных фактах о кодовой базе + воспроизвести метрики контаминации
на большем N с контролируемой смесью (вместо ручной курации v1/v2).

Конструкция:
- TRUE_POOL: 25 проверенных пар (субъект → реальная технология + паттерны,
  валидированы grep-ом 2026-08-11).
- Мутация FALSE: берём субъект из пула, подставляем ЧУЖОЕ значение:
  * absent-value (нет в коде — grep-0): чистая ложь, код молчит о значении,
    но содержит реальный паттерн субъекта → ожидается CONTRADICT;
  * present-value (встречается в коде, но не у этого субъекта): «ловушка» —
    код содержит токен ложного значения → ожидается SUPPORT-трап, но
    CONTRADICT (реальный паттерн) перевешивает;
  * silent: внешние системы (Grafana/GitLab/Kubernetes) — код молчит целиком.
- Смесь (контролируемая): 25 TRUE + 16 absent + 6 present-trap + 3 silent = 50.
- Детерминированно: random.Random(seed=42); (subject, value) уникальны.

Запуск: venv/Scripts/python.exe experiments/context_engine/memory_contamination_generator.py
        → memory_contamination_facts_v3_generated.json
        затем: venv/Scripts/python.exe experiments/context_engine/memory_contamination.py
               memory_contamination_facts_v3_generated.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ── TRUE-ядро: 25 пар (паттерны валидированы 2026-08-11) ──
TRUE_POOL = [
    # (id, label_ru, real_value, patterns)
    ("embedder", "Векторный embedder", "llama.cpp", ["LLAMA_CPP"]),
    ("embedding_model", "Модель эмбеддингов", "multilingual-e5-small", ["multilingual-e5-small"]),
    ("embedder_fallback", "Fallback embedder", "ONNX", ["OnnxEmbedderClient"]),
    ("reranker", "Реренкер", "BGE-M3", ["bge-m3"]),
    ("reranker_model", "Модель реранкера", "bge-reranker-v2-m3", ["bge-reranker-v2-m3"]),
    ("index", "Индекс чанков", "LanceDB", ["lancedb"]),
    ("index_version", "Версия LanceDB", "v2", ["lancedb_version"]),
    ("graph", "Граф знаний", "SQLite", ["sqlite3"]),
    ("graph_db", "Файл графа", "graph.db", ["graph.db"]),
    ("cypher", "Cypher-запросы", "in-process движок", ["file:src/core/search/cypher_engine.py"]),
    ("transport", "MCP-транспорт", "fastmcp", ["fastmcp"]),
    ("pid_lock", "PID-lock", "CreateMutexW", ["CreateMutexW"]),
    ("mutex_wait", "Ожидание mutex", "WaitForSingleObject", ["WaitForSingleObject"]),
    ("memory_store", "Хранилище памяти", "project_memory.json", ["project_memory.json"]),
    ("incidents_store", "Хранилище инцидентов", "incidents.json", ["incidents.json"]),
    ("artifacts", "Артефакты", "вне проекта", ["MSCODEBASE_DATA_DIR"]),
    ("execute_script", "execute_script", "отключён", ["MSCODEBASE_EXECUTE_SCRIPT_ENABLED"]),
    ("bm25", "BM25-ранжирование", "bm25_weight", ["bm25_weight"]),
    ("bm25_batch", "Реиндексация BM25", "DebounceBatch", ["DebounceBatch"]),
    ("edge_types", "Типы рёбер графа", "ASSIGNED_FROM", ["ASSIGNED_FROM"]),
    ("lsp", "LSP-диагностика", "basedpyright", ["basedpyright"]),
    ("parser", "Парсер кода", "tree-sitter", ["tree_sitter"]),
    ("incidents_log", "Запись инцидентов", "intel_log_incident", ["intel_log_incident"]),
    ("adr_collect", "Сбор ADR", "intel_auto_collect_adrs", ["intel_auto_collect_adrs"]),
    ("telemetry", "Телеметрия", "intel_get_telemetry", ["intel_get_telemetry"]),
]

# Значения, ОТСУТСТВУЮЩИЕ в коде (grep-0, валидировано 2026-08-11) — чистая ложь
ABSENT_VALUES = [
    "milvus", "zeromq", "zmq", "nose", "gremlin", "prometheus", "elasticsearch",
    "rabbitmq", "memcached", "nginx", "minio", "sentry", "spring", "kafka",
    "redis", "celery", "mysql", "grafana", "gitlab", "kubernetes", "k8s",
    "timeseries", "jenkins", "neo4j", "postgres", "docker", "fcntl", "mongo",
    "jina", "graph.json",
]

# Значения, ПРИСУТСТВУЮЩИЕ в коде, но НЕ являющиеся реальной технологией субъекта —
# «ловушки» (код содержит токен ложного значения)
PRESENT_VALUES = ["ollama", "lm_studio", "onnx", "fts5", "sqlite3", "git", "httpx", "numpy", "asyncio"]

# Внешние системы — код молчит целиком (SILENT)
SILENT_FACTS = [
    ("Дашборды мониторинга построены в Grafana", ["grafana"]),
    ("CI-пайплайн развёрнут в GitLab CI", ["gitlab"]),
    ("Деплой выполняется в Kubernetes", ["kubernetes", "k8s"]),
]

SEED = 42
OUT = HERE / "memory_contamination_facts_v3_generated.json"


def main() -> int:
    rng = random.Random(SEED)
    facts = []

    # TRUE (kind=real)
    for idx, (subj, label, value, patterns) in enumerate(TRUE_POOL, start=1):
        facts.append({
            "id": f"G{idx:02d}", "truth": True, "section": "adrs", "kind": "real",
            "subject": subj, "value": value,
            "claim": f"{label} использует {value}",
            "support_patterns": patterns, "contra_patterns": [],
        })

    real_by_subj = {s: (label, val, pats) for s, label, val, pats in TRUE_POOL}

    def _mutation(kind: str, value_pool: list) -> dict:
        # Уникальная (subject, value) пара, value != реальная технология субъекта
        while True:
            subj, label, real_val, _pats = rng.choice(TRUE_POOL)
            value = rng.choice(value_pool)
            if value == real_val.lower():
                continue
            key = (subj, value)
            if key in used:
                continue
            used.add(key)
            return {
                "subject": subj, "label": label, "value": value, "real": real_val,
            }

    used: set = set()

    # FALSE: absent-value мутации (16)
    for idx in range(len(facts) + 1, len(facts) + 17):
        m = _mutation("absent", ABSENT_VALUES)
        subj, label, value = m["subject"], m["label"], m["value"]
        facts.append({
            "id": f"G{idx:02d}", "truth": False, "section": "known_issues", "kind": "mutation_absent",
            "subject": subj, "value": value,
            "claim": f"{label} использует {value}",
            "support_patterns": [value], "contra_patterns": real_by_subj[subj][2],
        })

    # FALSE: present-value «ловушки» (6)
    for idx in range(len(facts) + 1, len(facts) + 7):
        m = _mutation("present", PRESENT_VALUES)
        subj, label, value = m["subject"], m["label"], m["value"]
        facts.append({
            "id": f"G{idx:02d}", "truth": False, "section": "tech_debt", "kind": "mutation_present",
            "subject": subj, "value": value,
            "claim": f"{label} использует {value}",
            "support_patterns": [value], "contra_patterns": real_by_subj[subj][2],
        })

    # FALSE: silent (3)
    for idx, (claim, patterns) in enumerate(SILENT_FACTS, start=len(facts) + 1):
        facts.append({
            "id": f"G{idx:02d}", "truth": False, "silent": True, "section": "known_issues",
            "kind": "silent", "subject": None, "value": None,
            "claim": claim, "support_patterns": patterns, "contra_patterns": [],
        })

    mix = {
        "n_true": sum(1 for f in facts if f["truth"]),
        "n_absent": sum(1 for f in facts if f["kind"] == "mutation_absent"),
        "n_present_trap": sum(1 for f in facts if f["kind"] == "mutation_present"),
        "n_silent": sum(1 for f in facts if f["kind"] == "silent"),
        "n_total": len(facts),
    }
    assert mix["n_total"] == 50, mix

    doc = {
        "_meta": {
            "experiment": "Experiment 1 — Memory Contamination, facts v3 (mutation generator, N=50)",
            "date": "2026-08-11",
            "seed": SEED,
            "mix": mix,
            "design": "25 real (TRUE_POOL, паттерны валидированы grep-ом) + 16 absent-mutation + "
                      "6 present-trap + 3 silent. value != real_value субъекта; (subject, value) уникальны. "
                      "Детерминированно (seed=42).",
        },
        "facts": facts,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated: {OUT} ({mix})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
