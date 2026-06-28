import subprocess
import sys
import os

os.chdir(r"D:\Project\MSCodeBase")
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_agentic_search.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    timeout=120
)

output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nReturn code: {result.returncode}\n"
with open(r"D:\Project\MSCodeBase\test_output.txt", "w", encoding="utf-8") as f:
    f.write(output)

print("Done. Output written to test_output.txt")
print(f"Return code: {result.returncode}")
if result.returncode != 0:
    print("FAILED")
    print(result.stdout[-2000:])
    print(result.stderr[-1000:])
