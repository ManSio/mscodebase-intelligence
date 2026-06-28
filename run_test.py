import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_agentic_search.py", "-v", "--tb=short"], capture_output=True, text=True, timeout=120, cwd="/d/Project/MSCodeBase")
with open("/d/Project/MSCodeBase/test_result.txt", "w") as f:
    f.write("STDOUT:\n" + r.stdout + "\n\nSTDERR:\n" + r.stderr + f"\n\nRC: {r.returncode}\n")
