@echo off
cd /d D:\Project\MSCodeBase
python experiments\run_experiment_compiler.py > experiments\compiler_results_output.txt 2>&1
echo DONE_CODE=%ERRORLEVEL% >> experiments\compiler_results_output.txt
