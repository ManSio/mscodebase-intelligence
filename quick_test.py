import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
import subprocess
r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_sandbox.py", "-v", "--tb=short"],
    cwd=r"D:\Project\MSCodeBase",
    timeout=120
)
sys.exit(r.returncode)
