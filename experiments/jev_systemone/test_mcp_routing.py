"""
Тест маршрутизации MCP-инструментов с Jev.

Тестирует:
- Выбор правильного инструмента по запросу
- Оценку уверенности выбора
- Работу с параметрами инструментов

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/test_mcp_routing.py
"""

import os
import json
from typesafe_sdk import TypeSafeClient, Noul, Choice

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"

MCP_TOOLS = [
    "search_code",
    "get_symbol_info",
    "impact_analysis",
    "read_live_file",
    "get_logs",
    "intel_get_runtime_status",
    "intel_trigger_reindex",
    "notify_change",
]


def test_tool_selection(client: TypeSafeClient) -> dict:
    """Тест выбора инструмента по запросу."""
    test_cases = [
        {"query": "Find all usages of function foo", "expected": "search_code"},
        {"query": "What does function bar return?", "expected": "get_symbol_info"},
        {"query": "Who calls this function?", "expected": "impact_analysis"},
        {"query": "Show me the contents of file.py", "expected": "read_live_file"},
        {"query": "What are the recent errors?", "expected": "get_logs"},
        {"query": "Is the MCP server running?", "expected": "intel_get_runtime_status"},
        {"query": "Reindex the project", "expected": "intel_trigger_reindex"},
        {"query": "I modified file.py", "expected": "notify_change"},
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["query"],
            questions={
                "tool": Choice(
                    instructions="Which MCP tool should handle this request?",
                    options=MCP_TOOLS,
                )
            },
            model=MODEL,
        )
        predicted = response.answers["tool"].choice
        confidence = response.answers["tool"].confidence
        results.append({
            "query": case["query"],
            "expected": case["expected"],
            "predicted": predicted,
            "confidence": confidence,
            "correct": predicted == case["expected"],
        })

    return {"tool_selection": results}


def test_tool_confidence(client: TypeSafeClient) -> dict:
    """Тест оценки уверенности выбора инструмента."""
    test_cases = [
        {"query": "Find function foo", "expected_tool": "search_code"},
        {"query": "What is the capital of France?", "expected_tool": None},  # Out of scope
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["query"],
            questions={
                "tool": Choice(
                    instructions="Which MCP tool should handle this request?",
                    options=MCP_TOOLS + ["none"],
                ),
                "confident": Noul(
                    instructions="Are you confident in this tool selection?",
                ),
            },
            model=MODEL,
        )
        predicted = response.answers["tool"].choice
        confidence = response.answers["tool"].confidence
        noul_confident = response.answers["confident"].noul
        results.append({
            "query": case["query"],
            "expected_tool": case["expected_tool"],
            "predicted": predicted,
            "confidence": confidence,
            "noul_confident": noul_confident,
        })

    return {"tool_confidence": results}


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        print("Get key at: https://console.typesafe.ai/keys")
        return

    client = TypeSafeClient(api_key=API_KEY)

    print("=" * 60)
    print("Jev MCP Routing Test")
    print("=" * 60)

    all_results = {}
    all_results.update(test_tool_selection(client))
    all_results.update(test_tool_confidence(client))

    # Print results
    for test_name, results in all_results.items():
        print(f"\n{test_name}:")
        if test_name == "tool_selection":
            correct = sum(1 for r in results if r["correct"])
            total = len(results)
            print(f"  Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
        for r in results:
            if test_name == "tool_selection":
                status = "OK" if r["correct"] else "FAIL"
                print(f"  [{status}] {r['query'][:50]} -> {r['predicted']} (conf: {r['confidence']:.2f})")
            else:
                print(f"  {r['query'][:50]} -> {r['predicted']} (conf: {r['confidence']:.2f}, noul: {r['noul_confident']:.2f})")

    # Save results
    with open("experiments/jev_systemone/mcp_routing_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 60)
    print("Results saved to experiments/jev_systemone/mcp_routing_results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
