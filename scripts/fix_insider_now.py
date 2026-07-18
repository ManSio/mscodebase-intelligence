"""
Срочный фикс: патч DLL в расширении + синхронизация кода = работает сразу.
Запускать: python scripts/fix_insider_now.py
"""
import struct, os, shutil, sys

ext = os.path.join(os.environ['LOCALAPPDATA'], 'Zed', 'extensions', 'mscodebase-intelligence')
llama_dir = os.path.join(ext, 'llama_msvc')
src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')

print(f'Расширение: {ext}')
print(f'Папка бинарника: {llama_dir}')

# 1. Копируем mtmd.dll если нет
dst_mtmd = os.path.join(llama_dir, 'mtmd.dll')
if not os.path.exists(dst_mtmd):
    vulkan_mtmd = os.path.join(ext, 'llama_vulkan', 'mtmd.dll')
    if os.path.exists(vulkan_mtmd):
        shutil.copy2(vulkan_mtmd, dst_mtmd)
        print('✅ mtmd.dll скопирован из llama_vulkan')
    else:
        print('❌ mtmd.dll нет нигде!')
else:
    print('✅ mtmd.dll уже есть')

# 2. Патчим все DLL — заменяем api-ms-win-crt-* → ucrtbase.dll
print('\n=== ПАТЧИМ DLL ===')
total = 0
for f in sorted(os.listdir(llama_dir)):
    if not (f.endswith('.dll') or f.endswith('.exe')):
        continue
    fp = os.path.join(llama_dir, f)
    with open(fp, 'rb') as fh:
        data = bytearray(fh.read())
    
    apis_before = data.count(b'api-ms-win-crt-')
    if apis_before == 0:
        continue
    
    pe_off = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe_off:pe_off+4] != b'PE\x00\x00':
        continue
    opt = pe_off+24
    magic = struct.unpack_from('<H', data, opt)[0]
    ds = opt+(96 if magic==0x10b else 112)
    irva = struct.unpack_from('<I', data, ds+8)[0]
    if irva == 0:
        continue
    so = ds+128
    ns = struct.unpack_from('<H', data, pe_off+6)[0]
    def r2r(rva):
        for i in range(ns):
            s=so+i*40
            sv=struct.unpack_from('<I',data,s+12)[0]
            ss=struct.unpack_from('<I',data,s+8)[0]
            sr=struct.unpack_from('<I',data,s+20)[0]
            if sv<=rva<sv+ss:
                return sr+(rva-sv)
        return None
    itr = r2r(irva)
    if itr is None:
        continue
    changed=0
    pos=itr
    while True:
        nth=struct.unpack_from('<I',data,pos)[0]
        nr=struct.unpack_from('<I',data,pos+12)[0]
        if nth==0 and nr==0:
            break
        dnr=r2r(nr)
        if dnr is not None:
            end=data.index(b'\x00', dnr)
            dn=data[dnr:end].decode('ascii',errors='replace')
            if dn.lower().startswith('api-ms-win-crt-'):
                new=b'ucrtbase.dll\x00'
                old_len=end-dnr
                if len(new)<=old_len:
                    data[dnr:dnr+len(new)]=new
                    for i in range(dnr+len(new),dnr+old_len):
                        data[i]=0
                    changed+=1
        pos+=20
    if changed:
        with open(fp, 'wb') as fh:
            fh.write(bytes(data))
        total += changed
        print(f'  {f}: {changed} patches')

print(f'\n✅ Итого: {total} импортов пропатчено в {llama_dir}')

# 3. Синхронизируем llama_runner.py из исходников в расширение
runner_src = os.path.join(src_dir, 'core', 'llama_runner.py')
runner_dst = os.path.join(ext, 'src', 'core', 'llama_runner.py')
if os.path.exists(runner_src):
    shutil.copy2(runner_src, runner_dst)
    print(f'✅ llama_runner.py синхронизирован в расширение')
else:
    print(f'❌ исходник не найден: {runner_src}')

# 4. Финальный тест
print('\n=== ФИНАЛЬНЫЙ ТЕСТ ===')
import subprocess
b = os.path.join(llama_dir, 'llama-server.exe')
r = subprocess.run([b, '--version'], capture_output=True, timeout=5, cwd=llama_dir)
if r.returncode == 0:
    print(f'✅ llama-server запускается!')
    print(f'   {r.stderr.decode(errors="replace").strip()}')
else:
    print(f'❌ Всё ещё падает: 0x{r.returncode & 0xFFFFFFFF:08X}')
    sys.exit(1)

# 5. Тест с моделью
m = os.path.join(ext, 'models', 'bge-m3-Q4_K_M.gguf')
if os.path.exists(m):
    import time, httpx
    log = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'llama_fix_test.log')
    proc = subprocess.Popen(
        [b, '--host', '127.0.0.1', '--port', '8099', '-m', m,
         '-c', '1024', '--batch-size', '512', '--ubatch-size', '512',
         '--no-webui', '-ngl', '0', '--embedding'],
        stdout=subprocess.DEVNULL, stderr=open(log, 'w'), cwd=llama_dir,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for i in range(90):
        rc = proc.poll()
        if rc is not None:
            print(f'❌ Умер rc={rc} через {i+1}с')
            with open(log) as f:
                print(f.read()[:300])
            break
        time.sleep(1)
        try:
            r2 = httpx.get('http://127.0.0.1:8099/health', timeout=2.0)
            if r2.status_code == 200:
                r3 = httpx.post('http://127.0.0.1:8099/v1/embeddings',
                              json={'input': ['Hello']}, timeout=10.0)
                if r3.status_code == 200:
                    print(f'✅ Модель загружена, embed dim={len(r3.json()["data"][0]["embedding"])}')
                else:
                    print(f'❌ Embed error: {r3.status_code}')
                proc.kill()
                break
        except:
            pass
    else:
        print('❌ Таймаут 90с')
        proc.kill()
else:
    print(f'❌ Модель не найдена: {m}')

print('\n🎉 Готово! Перезагрузи Zed — llama будет работать.')
