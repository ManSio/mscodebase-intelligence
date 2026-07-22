@echo off
cd /d D:\Project\MSCodeBase
python -m pytest tests/test_index_progress.py::TestIndexerProgressCallback::test_callback_is_optional -v --tb=long
