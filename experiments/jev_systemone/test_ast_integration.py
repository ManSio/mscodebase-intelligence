"""
Тест интеграции Jev с AST-графом MSCodeBase.

Тестирует:
- Классификация типов узлов AST
- Оценка сложности функций
- Поиск связанных узлов
- Проверка связей между файлами

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/test_ast_integration.py
"""

import os
import json
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"


def test_node_classification(client: TypeSafeClient) -> dict:
    """Тест классификации типов узлов AST."""
    test_cases = [
        {
            "code": "def calculate_total(items): return sum(items)",
            "expected": "function",
        },
        {
            "code": "class UserManager: pass",
            "expected": "class",
        },
        {
            "code": "import os\nimport sys",
            "expected": "import",
        },
        {
            "code": "x = 42",
            "expected": "assignment",
        },
        {
            "code": "if x > 0: print('positive')",
            "expected": "condition",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["code"],
            questions={
                "node_type": Choice(
                    instructions="What type of AST node is this?",
                    options=["function", "class", "import", "assignment", "condition", "loop"],
                )
            },
            model=MODEL,
        )
        predicted = response.answers["node_type"].choice
        confidence = response.answers["node_type"].confidence
        results.append({
            "code": case["code"][:50] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "confidence": confidence,
            "correct": predicted == case["expected"],
        })

    return {"node_classification": results}


def test_function_complexity(client: TypeSafeClient) -> dict:
    """Тест оценки сложности функций."""
    test_cases = [
        {
            "code": "def add(a, b): return a + b",
            "expected": "low",
        },
        {
            "code": "def process(data): return [x*2 for x in data if x > 0]",
            "expected": "medium",
        },
        {
            "code": "def fibonacci(n): return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)",
            "expected": "high",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state=case["code"],
            questions={
                "complexity": Score(
                    instructions="How complex is this function?",
                    levels=["low", "medium", "high"],
                )
            },
            model=MODEL,
        )
        score = response.answers["complexity"].score
        predicted = "low" if score < 1.5 else "medium" if score < 2.5 else "high"
        results.append({
            "code": case["code"][:50] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "score": score,
            "correct": predicted == case["expected"],
        })

    return {"function_complexity": results}


def test_code_relation(client: TypeSafeClient) -> dict:
    """Тест определения связи между кодом."""
    test_cases = [
        {
            "code1": "def login(user): return authenticate(user)",
            "code2": "def authenticate(user): return check_password(user)",
            "expected": "related",
        },
        {
            "code1": "def login(user): return authenticate(user)",
            "code2": "def fibonacci(n): return n",
            "expected": "unrelated",
        },
    ]

    results = []
    for case in test_cases:
        response = client.system_one(
            state={"code1": case["code1"], "code2": case["code2"]},
            questions={
                "related": Noul(
                    instructions="Are these two code snippets related?",
                    criteria={
                        "true": "The code snippets are functionally related",
                        "false": "The code snippets are unrelated",
                    },
                )
            },
            model=MODEL,
        )
        noul_value = response.answers["related"].noul
        predicted = "related" if noul_value > 0.5 else "unrelated"
        results.append({
            "code1": case["code1"][:40] + "...",
            "code2": case["code2"][:40] + "...",
            "expected": case["expected"],
            "predicted": predicted,
            "noul": noul_value,
            "correct": predicted == case["expected"],
        })

    return {"code_relation": results}


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        print("Get key at: https://console.typesafe.ai/keys")
        return

    client = TypeSafeClient(api_key=API_KEY)

    print("=" * 60)
    print("Jev AST Integration Test")
    print("=" * 60)

    all_results = {}
    all_results.update(test_node_classification(client))
    all_results.update(test_function_complexity(client))
    all_results.update(test_code_relation(client))

    # Print results
    for test_name, results in all_results.items():
        print(f"\n{test_name}:")
        correct = sum(1 for r in results if r["correct"])
        total = len(results)
        print(f"  Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
        for r in results:
            status = "OK" if r["correct"] else "FAIL"
            print(f"  [{status}] {r.get('code', r.get('code1', ''))[:50]}")

    # Save results
    with open("experiments/jev_systemone/ast_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 60)
    print("Results saved to experiments/jev_systemone/ast_results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
