@echo off
cd /d D:\Project\MSCodeBase
python -m pytest tests/test_agentic_search.py -v --tb=short > test_output.txt 2>&1
echo Exit code: %ERRORLEVEL% >> test_output.txt
