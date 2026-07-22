import sys, os, subprocess
os.chdir(r"D:\Project\MSCodeBase")
with open("test_output.txt", "w", encoding="utf-8", errors="replace") as f:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_sandbox.py", "-v", "--tb=short"],
        stdout=f, stderr=subprocess.STDOUT, timeout=120
    )
print(r.returncode)
