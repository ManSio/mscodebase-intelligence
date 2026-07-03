import pytest
import sys

print("=== ЗАПУСК ШПИОНА ТЕСТОВ ===")
print(f"Интерпретатор: {sys.executable}")

# Запускаем pytest с максимальным вербоузом и отключением захвата вывода,
# чтобы увидеть, на каком именно тесте или импорте замрёт процесс
exit_code = pytest.main(["-vv", "-s", "--tb=short", "tests/"])
print(f"=== ЗАВЕРШЕНО С КОДОМ: {exit_code} ===")
