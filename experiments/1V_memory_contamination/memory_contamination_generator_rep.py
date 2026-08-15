#!/usr/bin/env python3
"""
Memory Contamination — генератор фактов-мутаций для РЕПЛИКАЦИИ Exp 1-V (facts v4, N=50).

Зачем: репликация 1-V на НЕЗАВИСИМОМ наборе данных (Правило одного бенча, §1).
v3 (seed=42) показал adoption честного 0.0 — требуется второй независимый замер:
другой TRUE-пул (субъекты/паттерны), другие absent/silent значения, другой seed.

Конструкция (контрольная группа = v3):
- TRUE_POOL_REP: 25 проверенных пар (grep-валидированы 2026-08-11):
  * file: 6 путей (существуют) -> file-якорь -> VERIFIED;
  * env:  2 ключа (1 в .env -> VERIFIED, 1 нет -> INCONCLUSIVE);
  * import: 9 реальных root-импортов (igraph/leidenalg/chardet/huggingface_hub/
    dotenv/onnxruntime/pyarrow/mcp/onnx) -> import-якорь -> VERIFIED;
  * CamelCase: 8 имён классов (PropertyGraph/FastMCP/Indexer/Watchdog/LspClient/
    ETAPredictor/LanceDBWriter/NodeLabel) -> без якоря -> INCONCLUSIVE (ACTIVE).
  => ожидание: 0 ложных REFUTED TRUE (DoD ADR-0003) при корректной типизации.
- Мутация FALSE: 16 absent (grep-0: qdrant/weaviate/typesense/vespa/meilisearch/
  chromadb/pinecone/tantivy/solr/faiss/cassandra/couchbase/dynamodb/mariadb/consul/vault)
  -> import-якорь -> REFUTED (корректный отзыв);
  6 present-trap (pathlib/threading/dataclasses/json/logging/re — реальные импорты)
  -> import-якорь -> VERIFIED (видимый ложный — слепота presence-проверки,
  воспроизводит ограничение 1-V);
  3 silent (terraform/jaeger/loki — grep-0, внешние системы) -> REFUTED
  (SILENT_ABSENCE_ON_READ) -> adoption честного 0.0.
- Смесь: 25 TRUE + 16 absent + 6 trap + 3 silent = 50 (как v3).
- Детерминированно: random.Random(SEED=7); (subject, value) уникальны.

Запуск: venv/Scripts/python.exe experiments/context_engine/memory_contamination_generator_rep.py
        -> memory_contamination_facts_v4_rep.json
        затем: venv/Scripts/python.exe experiments/context_engine/memory_contamination_verify.py
               memory_contamination_facts_v4_rep.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ── TRUE-ядро репликации: 25 пар (паттерны grep-валидированы 2026-08-11) ──
TRUE_POOL = [
    # (id, label_ru, real_value, patterns)
    # file: (6) — существуют
    ("consistency", "Движок консистентности", "Consistency Engine",
     ["file:src/core/consistency.py"]),
    ("instruction_scan", "Сканер инструкций", "InstructionScan",
     ["file:src/core/instruction_scan.py"]),
    ("verify_layer", "Слой верификации чтения", "VerifyOnRead",
     ["file:src/core/intelligence/verify_on_read.py"]),
    ("artifact_paths", "Пути артефактов", "artifact_paths",
     ["file:src/core/artifact_paths.py"]),
    ("pid_lock", "PID-лок БД", "DatabaseLock",
     ["file:src/core/indexing/database_lock.py"]),
    ("multi_project", "Кросс-проектный поиск", "MultiProjectSearcher",
     ["file:src/core/multi_project_searcher.py"]),
    # env: (2) — 1 в .env (VERIFIED), 1 нет (INCONCLUSIVE)
    ("onnx_fallback", "ONNX-fallback", "отключён", ["DISABLE_ONNX_FALLBACK"]),
    ("self_index", "Сам-индексация проекта", "запрещена", ["MSCODEBASE_ALLOW_SELF_INDEX"]),
    # import: (9) — реальные root-импорты (в fp.imports)
    ("graph_cluster", "Граф-кластеризация", "igraph", ["igraph"]),
    ("community_detect", "Детект сообществ", "leidenalg", ["leidenalg"]),
    ("encoding", "Определение кодировки", "chardet", ["chardet"]),
    ("hub_models", "Загрузка моделей с хаба", "huggingface_hub", ["huggingface_hub"]),
    ("env_loader", "Загрузка переменных окружения", "python-dotenv", ["dotenv"]),
    ("onnx_runtime", "ONNX-runtime", "onnxruntime", ["onnxruntime"]),
    ("arrow", "Arrow-таблицы", "pyarrow", ["pyarrow"]),
    ("mcp_sdk", "MCP SDK", "mcp", ["mcp"]),
    ("onnx_driver", "ONNX-движок", "onnx", ["onnx"]),
    # CamelCase (8) — без якоря -> INCONCLUSIVE (ACTIVE)
    ("graph_knowledge", "Граф знаний", "PropertyGraph", ["PropertyGraph"]),
    ("mcp_server_class", "Серверная обёртка", "FastMCP", ["FastMCP"]),
    ("indexer_core", "Индексатор", "Indexer", ["Indexer"]),
    ("watchdog_mod", "Сторожевой таймер", "Watchdog", ["Watchdog"]),
    ("lsp_client_mod", "LSP-клиент", "LspClient", ["LspClient"]),
    ("eta_predictor", "Предиктор ETA", "ETAPredictor", ["ETAPredictor"]),
    ("db_writer_mod", "Писатель в БД", "LanceDBWriter", ["LanceDBWriter"]),
    ("graph_labels", "Метки узлов графа", "NodeLabel", ["NodeLabel"]),
]

# Значения, ОТСУТСТВУЮЩИЕ в коде (grep-0, валидировано 2026-08-11) — чистая ложь.
# Другой набор, чем v3 (v3: milvus/redis/grafana/... — здесь их нет).
ABSENT_VALUES = [
    "qdrant", "weaviate", "typesense", "vespa", "meilisearch", "chromadb",
    "pinecone", "tantivy", "solr", "faiss", "cassandra", "couchbase",
    "dynamodb", "mariadb", "consul", "vault",
]

# Значения, ПРИСУТСТВУЮЩИЕ в коде как импорты, но НЕ являющиеся реальной
# технологией субъекта — «ловушки» (verify: import-якорь найден -> VERIFIED,
# visible ложный факт; ловит только честный агент contra-анализом).
PRESENT_VALUES = ["pathlib", "threading", "dataclasses", "json", "logging", "re"]

# Внешние системы — код молчит целиком (SILENT), grep-0 (не пересекаются с v3)
SILENT_FACTS = [
    ("Инфраструктура развёрнута через Terraform", ["terraform"]),
    ("Трассировка запросов выполняется в Jaeger", ["jaeger"]),
    ("Логи агрегирует Loki", ["loki"]),
]

SEED = 7
OUT = HERE / "memory_contamination_facts_v4_rep.json"


def main() -> int:
    rng = random.Random(SEED)
    facts = []

    # TRUE (kind=real)
    for idx, (subj, label, value, patterns) in enumerate(TRUE_POOL, start=1):
        facts.append({
            "id": f"R{idx:02d}", "truth": True, "section": "adrs", "kind": "real",
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
            "id": f"R{idx:02d}", "truth": False, "section": "known_issues", "kind": "mutation_absent",
            "subject": subj, "value": value,
            "claim": f"{label} использует {value}",
            "support_patterns": [value], "contra_patterns": real_by_subj[subj][2],
        })

    # FALSE: present-value «ловушки» (6)
    for idx in range(len(facts) + 1, len(facts) + 7):
        m = _mutation("present", PRESENT_VALUES)
        subj, label, value = m["subject"], m["label"], m["value"]
        facts.append({
            "id": f"R{idx:02d}", "truth": False, "section": "tech_debt", "kind": "mutation_present",
            "subject": subj, "value": value,
            "claim": f"{label} использует {value}",
            "support_patterns": [value], "contra_patterns": real_by_subj[subj][2],
        })

    # FALSE: silent (3)
    for idx, (claim, patterns) in enumerate(SILENT_FACTS, start=len(facts) + 1):
        facts.append({
            "id": f"R{idx:02d}", "truth": False, "silent": True, "section": "known_issues",
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
    assert mix["n_true"] == 25, mix
    assert mix["n_absent"] == 16 and mix["n_present_trap"] == 6 and mix["n_silent"] == 3, mix

    doc = {
        "_meta": {
            "experiment": "Experiment 1-V REPLICATION — Memory Contamination VERIFY-ON-READ, facts v4 (N=50)",
            "date": "2026-08-11",
            "seed": SEED,
            "control_group": "Exp 1-V (facts v3, seed=42)",
            "mix": mix,
            "design": "25 real (TRUE_POOL_REP: file:6 + env:2 + import:9 + CamelCase:8, "
                      "паттерны grep-валидированы) + 16 absent-mutation (другой набор grep-0) + "
                      "6 present-trap (реальные импорты) + 3 silent (другие внешние системы). "
                      "value != real_value субъекта; (subject, value) уникальны. Детерминированно (seed=7).",
        },
        "facts": facts,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated: {OUT} ({mix})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
