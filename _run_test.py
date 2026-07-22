import subprocess, sys
sys.stdout.reconfigure(encoding='utf-8')
r = subprocess.run(
    [sys.executable, '-m', 'pytest',
     'tests/test_index_progress.py',
     '-k', 'test_callback_is_optional',
     '-v', '--tb=long']
)
sys.exit(r.returncode)
