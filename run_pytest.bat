@echo off
cd /d D:\Project\MSCodeBase
python -m pytest tests/test_sandbox.py -v --tb=short > test_output.txt 2>&1
