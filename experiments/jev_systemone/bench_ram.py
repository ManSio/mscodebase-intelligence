"""
Тест потребления RAM при работе с Jev API.

Запуск:
    pip install typesafe-sdk
    python experiments/jev_systemone/bench_ram.py
"""

import os
import time
import psutil
from typesafe_sdk import TypeSafeClient, Noul

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
MODEL = "jev-latest"


def get_ram_mb() -> float:
    """Текущее потребление RAM процессом в MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def main() -> None:
    if not API_KEY:
        print("ERROR: TYPESAFE_API_KEY not set")
        return

    print("=" * 60)
    print("Jev API RAM Usage Benchmark")
    print("=" * 60)

    ram_before = get_ram_mb()
    print(f"RAM before client creation: {ram_before:.1f} MB")

    client = TypeSafeClient(api_key=API_KEY)

    ram_after_client = get_ram_mb()
    print(f"RAM after client creation: {ram_after_client:.1f} MB")
    print(f"Client overhead: {ram_after_client - ram_before:.1f} MB")

    # Test RAM during requests
    ram_during = []
    for i in range(10):
        client.system_one(
            state=f"Test message {i}",
            questions={"test": Noul(instructions="Is this a test?")},
            model=MODEL,
        )
        ram_during.append(get_ram_mb())

    print(f"\nRAM during requests:")
    print(f"  Min: {min(ram_during):.1f} MB")
    print(f"  Max: {max(ram_during):.1f} MB")
    print(f"  Mean: {sum(ram_during)/len(ram_during):.1f} MB")

    ram_final = get_ram_mb()
    print(f"\nRAM after all requests: {ram_final:.1f} MB")
    print(f"Total overhead: {ram_final - ram_before:.1f} MB")

    print("\n" + "=" * 60)
    print("Note: Jev is a cloud model, RAM usage is minimal (HTTP client only)")
    print("=" * 60)


if __name__ == "__main__":
    main()
