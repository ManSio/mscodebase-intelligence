"""
Патчит PE-импорты DLL: заменяет api-ms-win-crt-* → ucrtbase.dll.

На Windows Insider (build >= 26000) Microsoft удалила виртуальные API Set DLL
(api-ms-win-crt-*), что вызывает STATUS_DLL_NOT_FOUND при запуске MSVC-сборок.
Функции из API Set есть в ucrtbase.dll — просто меняем имя DLL в импорте.

Использование:
    python patch_dll_imports.py путь/к/llama-server-impl.dll
"""

import struct
import sys
from pathlib import Path


def patch_imports(dll_path: Path, dry_run: bool = True) -> int:
    """Меняет api-ms-win-crt-* → ucrtbase.dll в таблице импорта PE.
    
    Returns: количество изменённых импортов.
    """
    data = bytearray(dll_path.read_bytes())

    # DOS header → PE offset
    pe_off = struct.unpack_from('<I', data, 0x3C)[0]

    # Проверяем PE signature
    if data[pe_off:pe_off + 4] != b'PE\x00\x00':
        print(f"❌ Не PE-файл: {dll_path}")
        return 0

    # Optional header
    opt_hdr = pe_off + 24
    magic = struct.unpack_from('<H', data, opt_hdr)[0]

    if magic == 0x10b:   # PE32
        data_dir_start = opt_hdr + 96
    elif magic == 0x20b:  # PE32+
        data_dir_start = opt_hdr + 112
    else:
        print(f"❌ Неизвестный PE magic: {magic:#x}")
        return 0

    # IMAGE_DIRECTORY_ENTRY_IMPORT (index 1)
    import_dir_rva = struct.unpack_from('<I', data, data_dir_start + 8)[0]
    if import_dir_rva == 0:
        print("ℹ️  Нет импортов")
        return 0

    # Section headers
    sections_offset = data_dir_start + 128  # 16 entries × 8 bytes
    num_sections = struct.unpack_from('<H', data, pe_off + 6)[0]

    # Конвертируем RVA → raw offset
    def rva_to_raw(rva):
        for i in range(num_sections):
            s = sections_offset + i * 40
            sv = struct.unpack_from('<I', data, s + 12)[0]
            ss = struct.unpack_from('<I', data, s + 8)[0]
            sr = struct.unpack_from('<I', data, s + 20)[0]
            if sv <= rva < sv + ss:
                return sr + (rva - sv)
        return None

    import_table_raw = rva_to_raw(import_dir_rva)
    if import_table_raw is None:
        print("❌ Не найден raw offset для таблицы импорта")
        return 0

    changed = 0
    pos = import_table_raw
    api_set_dlls = {}

    while True:
        # Читаем IMAGE_IMPORT_DESCRIPTOR (20 bytes)
        original_first_thunk = struct.unpack_from('<I', data, pos)[0]
        name_rva = struct.unpack_from('<I', data, pos + 12)[0]

        if original_first_thunk == 0 and name_rva == 0:
            break  # конец таблицы

        # Конвертируем RVA имени DLL в raw
        dll_name_raw = rva_to_raw(name_rva)
        if dll_name_raw is None:
            pos += 20
            continue

        # Читаем имя DLL
        end = data.index(b'\x00', dll_name_raw)
        dll_name = data[dll_name_raw:end].decode('ascii', errors='replace')

        if dll_name.lower().startswith('api-ms-win-crt-'):
            # Заменяем имя на ucrtbase.dll
            new_name = b'ucrtbase.dll\x00'
            old_len = end - dll_name_raw
            if len(new_name) <= old_len:
                old_name = data[dll_name_raw:dll_name_raw + old_len]
                data[dll_name_raw:dll_name_raw + len(new_name)] = new_name
                # Затираем остаток нулями
                for i in range(dll_name_raw + len(new_name), dll_name_raw + old_len):
                    data[i] = 0
                changed += 1
                api_set_dlls[dll_name] = new_name.decode()
                print(f"  🔄 {dll_name} → ucrtbase.dll")
            else:
                print(f"  ⚠️  {dll_name}: новое имя длиннее старого ({len(new_name)} > {old_len}), пропускаю")

        pos += 20

    if changed > 0 and not dry_run:
        dll_path.write_bytes(bytes(data))
        print(f"\n✅ {changed} импортов исправлено, файл сохранён: {dll_path}")
    elif changed > 0 and dry_run:
        print(f"\n✅ {changed} импортов будет исправлено (dry-run)")
    else:
        print("ℹ️  Нет api-ms-win-crt-* импортов для замены")

    return changed


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    dll_path = Path(sys.argv[1])
    if not dll_path.exists():
        print(f"❌ Файл не найден: {dll_path}")
        return

    dry_run = '--write' not in sys.argv
    if dry_run:
        print(f"🔍 Dry-run режим (добавь --write для записи)")
    else:
        print(f"✏️  Режим записи")

    print(f"📄 Файл: {dll_path} ({dll_path.stat().st_size / 1024:.0f} KB)")
    patch_imports(dll_path, dry_run=dry_run)


if __name__ == '__main__':
    main()
