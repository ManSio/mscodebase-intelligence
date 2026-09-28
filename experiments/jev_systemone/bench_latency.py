"""
Бенчмарк задержки Jev API.

Тестирует:
- Noul (yes/no)
- Choice (выбор из списка)
- Score (оценка по шкале)
- Параллельные вопросы (mix)
- Разные размеры state

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/bench_latency.py
"""

import os
import time
import statistics
from typesafe_sdk import TypeSafeClient, Noul, Choice, Score

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"
N_ITERATIONS = 10


def bench_noul(client: TypeSafeClient, state: str) -> list[float]:
    """Тест Noul (yes/no) вопроса."""
    times = []
    for _ in range(N_ITERATIONS):
        start = time.time()
        client.system_one(
            state=state,
            questions={
                "test": Noul(instructions="Is this a test?")
            },
            model=MODEL,
        )
        times.append(time.time() - start)
    return times


def bench_choice(client: TypeSafeClient, state: str) -> list[float]:
    """Тест Choice (выбор из списка) вопроса."""
    times = []
    for _ in range(N_ITERATIONS):
        start = time.time()
        client.system_one(
            state=state,
            questions={
                "choice": Choice(
                    instructions="Which category?",
                    options=["A", "B", "C", "D"],
                )
            },
            model=MODEL,
        )
        times.append(time.time() - start)
    return times


def bench_score(client: TypeSafeClient, state: str) -> list[float]:
    """Тест Score (оценка по шкале) вопроса."""
    times = []
    for _ in range(N_ITERATIONS):
        start = time.time()
        client.system_one(
            state=state,
            questions={
                "score": Score(
                    instructions="Rate this from 1 to 5",
                    levels=["1", "2", "3", "4", "5"],
                )
            },
            model=MODEL,
        )
        times.append(time.time() - start)
    return times


def bench_parallel(client: TypeSafeClient, state: str) -> list[float]:
    """Тест параллельных вопросов (mix of types)."""
    times = []
    for _ in range(N_ITERATIONS):
        start = time.time()
        client.system_one(
            state=state,
            questions={
                "noul": Noul(instructions="Is this urgent?"),
                "choice": Choice(
                    instructions="Which team?",
                    options=["frontend", "backend", "devops"],
                ),
                "score": Score(
                    instructions="How complex?",
                    levels=["low", "medium", "high"],
                ),
            },
            model=MODEL,
        )
        times.append(time.time() - start)
    return times


def bench_large_state(client: TypeSafeClient, state: str) -> list[float]:
    """Тест с большим state (10KB текста)."""
    times = []
    for _ in range(N_ITERATIONS):
        start = time.time()
        client.system_one(
            state=state,
            questions={
                "noul": Noul(instructions="Is this relevant?"),
            },
            model=MODEL,
        )
        times.append(time.time() - start)
    return times


def print_stats(name: str, times: list[float]) -> None:
    """Вывод статистики."""
    print(f"\n{name}:")
    print(f"  Min:    {min(times)*1000:.1f} ms")
    print(f"  Max:    {max(times)*1000:.1f} ms")
    print(f"  Mean:   {statistics.mean(times)*1000:.1f} ms")
    print(f"  Median: {statistics.median(times)*1000:.1f} ms")
    print(f"  P95:    {sorted(times)[int(len(times)*0.95)]*1000:.1f} ms")


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        print("Get key at: https://console.typesafe.ai/keys")
        return

    client = TypeSafeClient(api_key=API_KEY)

    short_state = "This is a test message."
    large_state = "Lorem ipsum dolor sit amet. " * 500  # ~10KB

    print("=" * 60)
    print("Jev API Latency Benchmark")
    print("=" * 60)

    print_stats("Noul (short state)", bench_noul(client, short_state))
    print_stats("Choice (short state)", bench_choice(client, short_state))
    print_stats("Score (short state)", bench_score(client, short_state))
    print_stats("Parallel (3 questions)", bench_parallel(client, short_state))
    print_stats("Noul (large state ~10KB)", bench_large_state(client, large_state))

    print("\n" + "=" * 60)
    print("Benchmark complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
