"""
Тест скрытых возможностей и нетрадиционного использования Jev.

Тестирует:
- Нетрадиционные применения
- Комбинирование примитивов
- Работу с большими объемами данных
- Параллельную обработку

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/test_hidden_capabilities.py
"""

import os
import json
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"


def test_tricky_classification(client: TypeSafeClient) -> dict:
    """Тест сложных случаев классификации."""
    test_cases = [
        {
            "state": "The user wants to delete a file but is not sure if it's safe",
            "question": "What is the user's intent?",
            "options": ["delete", "check", "create", "modify"],
            "expected": "check",
        },
        {
            "state": "This code has a bug but it's not obvious",
            "question": "Is there a bug?",
            "expected_yes": True,
        },
    ]

    results = []
    for case in test_cases:
        if "options" in case:
            response = client.system_one(
                state=case["state"],
                questions={
                    "intent": Choice(
                        instructions=case["question"],
                        options=case["options"],
                    )
                },
                model=MODEL,
            )
            predicted = response.answers["intent"].choice
            results.append({
                "state": case["state"][:50] + "...",
                "expected": case["expected"],
                "predicted": predicted,
                "correct": predicted == case["expected"],
            })
        else:
            response = client.system_one(
                state=case["state"],
                questions={
                    "has_bug": Noul(instructions=case["question"]),
                },
                model=MODEL,
            )
            noul_value = response.answers["has_bug"].noul
            predicted = "yes" if noul_value > 0.5 else "no"
            results.append({
                "state": case["state"][:50] + "...",
                "expected": "yes" if case["expected_yes"] else "no",
                "predicted": predicted,
                "noul": noul_value,
                "correct": predicted == ("yes" if case["expected_yes"] else "no"),
            })

    return {"tricky_classification": results}


def test_composite_scoring(client: TypeSafeClient) -> dict:
    """Тест комбинирования нескольких Score."""
    state = "This is a sample code snippet for testing purposes."

    response = client.system_one(
        state=state,
        questions={
            "readability": Score(
                instructions="How readable is this code?",
                levels=["poor", "fair", "good", "excellent"],
            ),
            "maintainability": Score(
                instructions="How maintainable is this code?",
                levels=["poor", "fair", "good", "excellent"],
            ),
            "performance": Score(
                instructions="How performant is this code?",
                levels=["poor", "fair", "good", "excellent"],
            ),
        },
        model=MODEL,
    )

    results = {}
    for key in ["readability", "maintainability", "performance"]:
        results[key] = {
            "score": response.answers[key].score,
            "confidence": response.answers[key].confidence,
        }

    return {"composite_scoring": results}


def test_parallel_questions(client: TypeSafeClient) -> dict:
    """Тест параллельных вопросов (10+ вопросов в одном запросе)."""
    state = "This is a test message for parallel questions."

    questions = {
        f"q{i}": Noul(instructions=f"Is this question {i} relevant?")
        for i in range(10)
    }

    response = client.system_one(
        state=state,
        questions=questions,
        model=MODEL,
    )

    results = {}
    for i in range(10):
        key = f"q{i}"
        results[key] = response.answers[key].noul

    return {"parallel_questions": results}


def test_large_batch(client: TypeSafeClient) -> dict:
    """Тест обработки большого количества вопросов."""
    state = "This is a test message for large batch processing."

    questions = {
        f"batch_q{i}": Noul(instructions=f"Batch question {i}: Is this relevant?")
        for i in range(50)
    }

    response = client.system_one(
        state=state,
        questions=questions,
        model=MODEL,
    )

    results = {}
    for i in range(50):
        key = f"batch_q{i}"
        results[key] = response.answers[key].noul

    return {"large_batch": results}


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        print("Get key at: https://console.typesafe.ai/keys")
        return

    client = TypeSafeClient(api_key=API_KEY)

    print("=" * 60)
    print("Jev Hidden Capabilities Test")
    print("=" * 60)

    all_results = {}
    all_results.update(test_tricky_classification(client))
    all_results.update(test_composite_scoring(client))
    all_results.update(test_parallel_questions(client))
    all_results.update(test_large_batch(client))

    # Print results
    for test_name, results in all_results.items():
        print(f"\n{test_name}:")
        if test_name == "tricky_classification":
            correct = sum(1 for r in results if r["correct"])
            total = len(results)
            print(f"  Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
            for r in results:
                status = "OK" if r["correct"] else "FAIL"
                print(f"  [{status}] {r['state'][:50]}")
        elif test_name == "composite_scoring":
            for key, value in results.items():
                print(f"  {key}: score={value['score']:.2f}, confidence={value['confidence']:.2f}")
        elif test_name == "parallel_questions":
            print(f"  10 questions processed in parallel")
            print(f"  Min noul: {min(results.values()):.2f}")
            print(f"  Max noul: {max(results.values()):.2f}")
        elif test_name == "large_batch":
            print(f"  50 questions processed in parallel")
            print(f"  Min noul: {min(results.values()):.2f}")
            print(f"  Max noul: {max(results.values()):.2f}")

    # Save results
    with open("experiments/jev_systemone/hidden_capabilities_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\n" + "=" * 60)
    print("Results saved to experiments/jev_systemone/hidden_capabilities_results.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
