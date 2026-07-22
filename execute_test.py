import sys
import os
import subprocess

def main():
    os.chdir(r"D:\Project\MSCodeBase")
    
    # Write a simple batch file
    bat_content = '@echo off\ncd /d D:\\Project\\MSCodeBase\npython -m pytest tests/test_sandbox.py -v --tb=short > D:\\Project\\MSCodeBase\\test_output.txt 2\necho %ERRORLEVEL% >> D:\\Project\\MSCodeBase\\test_output.txt\n'
    with open(r"D:\Project\MSCodeBase\run_test.bat", "w") as f:
        f.write(bat_content)
    
    # Run it
    subprocess.run(["cmd.exe", "/c", r"D:\Project\MSCodeBase\run_test.bat"], timeout=120)
    
    # Read and print output
    with open(r"D:\Project\MSCodeBase\test_output.txt", "r", encoding="utf-8", errors="replace") as f:
        print(f.read())

if __name__ == "__main__":
    main()
