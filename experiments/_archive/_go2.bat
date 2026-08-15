@echo off
cd /d D:\Project\MSCodeBase
python experiments/_run_compiler_standalone.py > experiments\_output.txt 2>&1
echo FINISHED
