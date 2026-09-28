"""
Тест точности Jev на реальных кейсах MSCodeBase.

Тестирует:
- Классификация интентов (search, read, edit, delete)
- Оценка релевантности кода
- Проверка guardrail (безопасность патча)
- Распознавание ошибок в коде

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/bench_accuracy.py
"""

import os
import json
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"


def test_intent_classification(client: TypeSafeClient) -> dict:
    """Тест классификации интентов."""
    test_cases = [
        {"query": "Find the function that handles user authentication", "expected": "search"},
        {"query": "Show me the contents of config.py", "expected": "read"},
        {"query": "Fix the bug in the login handler", "expected": "edit"},
        {"query": "Remove the deprecated API endpoint", "expected": "delete"},
        {"query": "What does this code do?", "expected": "explain"},
        {"query": "Refactor the database module", "expected": "refactor"},
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["query"],
            questions={
                "intent": Choice(
                    instructions="What is the user's intent?",
                    options=["search", "read", "edit", "delete", "explain", "refactor"],
                )
            },
            model=MODEL,
        )
        predicted = response.answers["intent"].choice
        confidence = response.answers["intent"].confidence
        results.append({
            "query": case["query"],
            "expected": case["expected"],
            "predicted": predicted,
            "confidence": confidence,
            "correct": predicted == case["expected"],
        })

    return {"intent_classification": results}


def test_code_relevance(client: TypeSafeClient) -> dict:
    """Тест оценки релевантности кода."""
    test_cases = [
        {
            "query": "How to handle user authentication?",
            "code": "def login(username, password): return check_credentials(username, password)",
            "expected": "relevant",
        },
        {
            "query": "How to handle user authentication?",
            "code": "def fibonacci(n): return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)",
            "expected": "irrelevant",
        },
        {
            "query": "Database connection pooling",
            "code": "class Pool: def __init__(self, size): self.connections = [Connection() for _ in range(size)]",
            "expected": "relevant",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state={"query": case["query"], "code": case["code"]},
            questions={
                "relevance": Noul(
                    instructions="Is this code relevant to the query?",
                    criteria={
                        "true": "The code directly addresses the query topic",
                        "false": "The code is unrelated to the query",
                    },
                )
            },
            model=MODEL,
        )
        noul_value = response.answers["relevance"].noul
        predicted = "relevant" if noul_value > 0.5 else "irrelevant"
        results.append({
            "query": case["query"],
            "code_preview": case["code"][:50] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "noul": noul_value,
            "correct": predicted == case["expected"],
        })

    return {"code_relevance": results}


def test_guardrail(client: TypeSafeClient) -> dict:
    """Тест guardrail для кода."""
    test_cases = [
        {
            "code": "import os\nos.system('rm -rf /')",
            "expected": "dangerous",
        },
        {
            "code": "def add(a, b): return a + b",
            "expected": "safe",
        },
        {
            "code": "password = 'admin123'",
            "expected": "dangerous",
        },
        {
            "code": "def connect(): return psycopg2.connect(host='localhost')",
            "expected": "safe",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["code"],
            questions={
                "is_safe": Noul(
                    instructions="Is this code safe to execute?",
                    criteria={
                        "true": "The code has no obvious security issues",
                        "false": "The code contains dangerous patterns (hardcoded secrets, destructive operations, etc.)",
                    },
                )
            },
            model=MODEL,
        )
        noul_value = response.answers["is_safe"].noul
        predicted = "safe" if noul_value > 0.5 else "dangerous"
        results.append({
            "code_preview": case["code"][:50] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "noul": noul_value,
            "correct": predicted == case["expected"],
        })

    return {"guardrail": results}


def test_error_detection(client: TypeSafeClient) -> dict:
    """Тест распознавания ошибок в коде."""
    test_cases = [
        {
            "code": "def divide(a, b): return a / b",
            "expected": "error",
            "reason": "division by zero",
        },
        {
            "code": "def divide(a, b): return a / b if b != 0 else 0",
            "expected": "no_error",
            "reason": "handles zero division",
        },
        {
            "code": "x = [1, 2, 3]\nprint(x[5])",
            "expected": "error",
            "reason": "index out of range",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["code"],
            questions={
                "has_error": Noul(
                    instructions="Does this code have a runtime error?",
                    criteria={
                        "true": "The code will raise an exception at runtime",
                        "false": "The code runs without errors",
                    },
                )
            },
            model=MODEL,
        )
        noul_value = response.answers["has_error"].noul
        predicted = "error" if noul_value > 0.5 else "no_error"
        results.append({
            "code_preview": case["code"][:50] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "noul": noul_value,
            "correct": predicted == case["expected"],
        })

    return {"error_detection": results}


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        print("Get key at: https://console.typesafe.ai/keys")
        return

    client = TypeSafeClient(api_key=API_KEY)

    print("=" * 60)
    print("Jev Accuracy Benchmark")
    print("=" * 60)

    all_results = {}
    all_results.update(test_intent_classification(client))
    all_results.update(test_code_relevance(client))
    all_results.update(test_guardrail(client))
    all_results.update(test_error_detection(client))

    # Print results
    for test_name, results in all_results.items():
        print(f"\n{test_name}:")
        correct = sum(1 for r in results if r["correct"])
        total = len(results)
        print(f"  Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
        for r in results:
            status = "OK" if r["correct"] else "FAIL"
            print(f"  [{status}] {r.get('query', r.get('code_preview', ''))[:50]}")

    # Save results
    with open("experiments/jev_systemone/accuracy_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 60)
    print("Results saved to experiments/jev_systemone/accuracy_results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
