"""
Мониторинг индексации — все фазы с ETA.
Запуск: python scripts/monitor.py (в отдельном терминале)
"""
import sys
import os
import time
import re
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Импортируем единое имя лог-файла из log_manager (Single Source of Truth)
try:
    from src.core.log_manager import get_main_log_path
    LOG_FILE = get_main_log_path()
except ImportError:
    # Fallback для автономного запуска без импорта src
    LOG_DIR = Path(os.environ.get(
        "LOG_DIR",
        r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs"
    ))
    LOG_FILE = LOG_DIR / "mscodebase-intelligence.log"

last_done = 0
last_time = time.time()
speeds = []
phase = "⏳ Ожидание"


def grep_log(pattern, n=20):
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    res = []
    for l in reversed(lines):
        if re.search(pattern, l):
            res.append(l)
            if len(res) >= n:
                break
    return list(reversed(res))


def parse_embed(line):
    m = re.search(
        r'\[embed\]\s+(\d+)/(\d+)\s+batch=\d+ch/[\d.]+s=(\d+)ch/s\s+avg=(\d+)ch/s\s+elapsed=(\d+)s',
        line
    )
    return m.groups() if m else None


def parse_parse(line):
    m = re.search(r'Found\s+(\d+)\s+files', line)
    return m.groups() if m else None


def parse_write(line):
    m = re.search(r'Записано в БД:.*\((\d+)\s+чанков\)', line)
    return m.groups() if m else None


os.system('cls' if os.name == 'nt' else 'clear')
print("📊 МОНИТОР ИНДЕКСАЦИИ (все фазы)")
print("─" * 60)
print("  Запущен в фоне. Обновление каждые 5с.")
print("─" * 60)

total_est = 0  # известное общее кол-во чанков (после Parse complete)

try:
    while True:
        try:
            logs = grep_log(
                r'\[embed\]|Found.*files|Parse complete.*files changed|Total chunks|'
                r'Записано в БД|Indexing complete|Embed complete|Creating index|IVF_FLAT',
                10
            )
        except Exception:
            logs = []

        # Определяем фазу
        all_text = '\n'.join(logs)
        if "Indexing complete" in all_text:
            phase = "✅ Завершено"
        elif "Creating index" in all_text or "IVF_FLAT" in all_text:
            phase = "🏗️  IVF индекс"
        elif "Записано в БД" in all_text:
            phase = "💾 Запись в БД"
        elif "Embed complete" in all_text:
            phase = "⚙️  Эмбеддинг готов"
        elif parse_embed(logs[-1]) if logs else None:
            phase = "🧠 Эмбеддинг"
        elif "Total chunks" in all_text:
            phase = "⚙️  Запуск эмбеддинга"
        elif "Parse complete" in all_text:
            phase = "📂 Парсинг готов"
        elif "Found" in all_text:
            phase = "📂 Парсинг"
        else:
            phase = "⏳ Загрузка..."

        # Данные
        embed_data = None
        for l in reversed(logs):
            p = parse_embed(l)
            if p:
                embed_data = p
                break

        # Total chunks
        for l in logs:
            m = re.search(r'Total chunks:\s*(\d+)', l)
            if m:
                total_est = int(m.group(1))

        # Последняя embed строка
        done, total, inst, avg, elapsed = 0, total_est or 0, 0, 0, 0
        if embed_data:
            done, total, inst, avg, elapsed = map(int, embed_data)

        # ETA
        now = time.time()
        if done and total and done != last_done and last_done > 0:
            dt = now - last_time
            if dt > 1:
                s = (done - last_done) / dt
                speeds.append(s)
                if len(speeds) > 10:
                    speeds.pop(0)
        last_done = done
        last_time = now

        recent_speed = sum(speeds) / len(speeds) if speeds else inst
        remaining = max(1, (total - done)) if total else 0
        eta = remaining / max(recent_speed, 0.1) if recent_speed else 0
        eta_fmt = f"{eta:.0f}с ({eta/60:.1f}мин)" if eta < 3600 else f"{eta/60:.0f}мин"

        os.system('cls' if os.name == 'nt' else 'clear')
        print("📊 МОНИТОР ИНДЕКСАЦИИ")
        print("─" * 60)
        print(f"  Фаза: {phase}")

        if total:
            pct = done / total * 100
            bar_len = 30
            filled = int(bar_len * done / max(total, 1))
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"  Чанки: {bar} {pct:.0f}%")
            print(f"  {done}/{total} ({total - done} осталось)")
            print(f"  Скорость: {inst} ch/s | Средняя: {avg} ch/s | Посл.10с: {recent_speed:.0f} ch/s")
            print(f"  ETA: {eta_fmt} | Прошло: {elapsed}с")
        else:
            # Фаза парсинга — ищем количество файлов
            for l in logs:
                m = re.search(r'Found\s+(\d+)\s+files', l)
                if m:
                    print(f"  Файлов: {m.group(1)}")
                    break
            print("   (прогресс появится при Total chunks)")

        # Тренд
        if len(speeds) >= 3:
            t = speeds[-1] - speeds[0]
            trend = "⬆️" if t > 3 else ("⬇️" if t < -3 else "➡️")
            print(f"  Тренд: {trend} (вариация: {t:.0f} ch/s)")

        print("─" * 60)
        print("  Ctrl+C для выхода | Обновление 5с")

        if "Завершено" in phase:
            print("\n  ✅ Индексация завершена!")
            break

        time.sleep(5)
except KeyboardInterrupt:
    print("\nОстановлен")
