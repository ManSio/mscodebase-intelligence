#!/usr/bin/env bash
set -uo pipefail
cd /d/Project/MSCodeBase
python -m pytest tests/test_index_progress.py -k test_callback_is_optional -v --tb=long
