import os, subprocess

ext = os.path.join(os.environ['LOCALAPPDATA'], 'Zed', 'extensions', 'mscodebase-intelligence')
print('1. .env:')
env = os.path.join(ext, '.env')
if os.path.exists(env):
    with open(env) as f:
        for l in f:
            l = l.strip()
            if l and not l.startswith('#'):
                print(' ', l)
else:
    print(' (net)')

print()
print('2. Kod v rasshirenii (llama_runner.py):')
runner = os.path.join(ext, 'src', 'core', 'llama_runner.py')
if os.path.exists(runner):
    with open(runner, encoding='utf-8') as f:
        c = f.read()
    checks = ['_patch_dll_imports', 'mtmd.dll', 'api-ms-win-crt', 'ucrtbase', 'cwd=str(_llama_bin().parent)']
    for k in checks:
        print(' OK' if k in c else ' MISS', k)
else:
    print(' FAIL: file not found')

print()
print('3. Binarnik (llama_msvc/):')
d = os.path.join(ext, 'llama_msvc')
b = os.path.join(d, 'llama-server.exe')
print('  exe:', os.path.exists(b))
if os.path.exists(b):
    print('  size:', os.path.getsize(b)//1024, 'KB')
    print('  CPU dlls:', os.path.exists(os.path.join(d, 'ggml-cpu-haswell.dll')))
    print('  Vulkan:', os.path.exists(os.path.join(d, 'ggml-vulkan.dll')))
    print('  mtmd.dll:', os.path.exists(os.path.join(d, 'mtmd.dll')))
print('  Files:', len([f for f in os.listdir(d) if f.endswith(('.dll','.exe'))]))

bad = 0
for f in os.listdir(d):
    if not f.endswith(('.dll','.exe')):
        continue
    fp = os.path.join(d, f)
    with open(fp, 'rb') as fh:
        n = fh.read().count(b'api-ms-win-crt-')
    if n > 0:
        print('  FAIL:', f, 'imaet', n, 'api-ms-win-crt')
        bad += 1
if bad == 0:
    print('  api-ms-win-crt: clean')

print()
print('4. Test zapuska:')
r = subprocess.run([b, '--version'], capture_output=True, timeout=5, cwd=d)
print('  rc:', r.returncode)
if r.returncode == 0:
    print(' OK:', r.stderr.decode(errors='replace').strip()[:100])
else:
    print(' FAIL: 0x{:08X}'.format(r.returncode & 0xFFFFFFFF))
    print('  err:', r.stderr.decode(errors='replace')[:200])

print()
print('5. Processy:')
r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/NH'], capture_output=True, timeout=3)
o = r.stdout.decode('utf-8', errors='replace').strip()
print('  llama-server:', 'RUNNING' if 'llama' in o.lower() else 'NONE')
r2 = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/NH'], capture_output=True, timeout=3)
o2 = r2.stdout.decode('utf-8', errors='replace').strip()
pyc = len([l for l in o2.split('\n') if 'mscodebase' in l.lower() or 'mcp' in l.lower() or 'main.py' in l.lower()])
print('  MCP python processes:', pyc)

print()
print('6. Port 8080:')
r3 = subprocess.run(
    'netstat -ano | findstr :8080',
    capture_output=True, timeout=3, shell=True
)
o3 = r3.stdout.decode('utf-8', errors='replace').strip()
print(' ', o3[:200] if o3 else 'free')
if o3:
    import re
    pids = set(re.findall(r'(\d+)$', o3, re.MULTILINE))
    for pid in pids:
        r4 = subprocess.run(['tasklist', '/FI', 'PID eq '+pid, '/NH'], capture_output=True, timeout=3)
        print('   PID', pid, ':', r4.stdout.decode('utf-8', errors='replace').strip()[:60])

print()
print('7. Port 8081:')
r5 = subprocess.run(
    'netstat -ano | findstr :8081',
    capture_output=True, timeout=3, shell=True
)
o5 = r5.stdout.decode('utf-8', errors='replace').strip()
print(' ', o5[:200] if o5 else 'free')

print()
print('GOTOVO')
