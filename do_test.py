#!/usr/bin/env python3
"""Run pytest and save output to file."""
import subprocess
import sys
import os

def main():
    os.chdir(r"D:\Project\MSCodeBase")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_sandbox.py", "-v", "--tb=short"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        creationflags=0
    )
    with open("test_output.txt", "wb") as f:
        f.write(result.stdout or b"")
        f.write(f"\nRETURN_CODE={result.returncode}\n".encode())
    print(f"pytest done, exit={result.returncode}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
