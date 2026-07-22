import subprocess, sys, os
os.chdir(r"D:\Project\MSCodeBase")
r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_sandbox.py", "-v", "--tb=short"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace", timeout=120
)
with open("test_output.txt", "w", encoding="utf-8") as f:
    f.write(r.stdout or "")
print("DONE", r.returncode)
