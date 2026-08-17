"""
Мониторинг индексации — все фазы с точным расчётом.
Запуск: python scripts/monitor.py (в отдельном терминале)

Режимы для ЛЮБОГО проекта (протокол AGENTS.md — агент вызывает монитор
после intel_trigger_reindex):
  python scripts/monitor.py                             → глобальный main-лог
  python scripts/monitor.py --project "D:/Path/Proj"    → per-project <Proj>.log (если есть)
  python scripts/monitor.py --data-root "C:/my/mscodebase" → лог из своего data_root
  python scripts/monitor.py --log "C:/x/mscodebase-intelligence.log" → прямой файл

Скрипт сам добавляет корень репо в sys.path, поэтому запускается из любого
каталога (не только из каталога MSCodeBase).

v2: fixed avg, IVF progress, weighted speed, per-phase stats.
v3: + lock status, Not Found counter, auto-index lifecycle.
v4: + --project/--data-root/--log (мониторинг любого проекта).
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Self-bootstrap: позволяем запускать monitor.py из ЛЮБОГО проекта/каталога
# (протокол AGENTS.md: агент обязан вызывать монитор после intel_trigger_reindex).
# `python scripts/monitor.py` кладёт в sys.path каталог скрипта, а не корень репо —
# без этой вставки `import src.core.*` не разрешался бы вне репо.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path and (_repo_root / "src").is_dir():
    sys.path.insert(0, str(_repo_root))

# Единое имя лог-файла (Single Source of Truth)
try:
    from src.core.log_manager import get_main_log_path, get_log_dir  # noqa: I001 — после self-bootstrap
    LOG_FILE = get_main_log_path()
except ImportError:
    LOG_DIR = Path(os.environ.get(
        "LOG_DIR",
        r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs"
    ))
    LOG_FILE = LOG_DIR / "mscodebase-intelligence.log"

# ── CLI: монитор можно навести на любой проект (AGENTS.md) ──────────
#   --project PATH    — корень проекта; предпочитает per-project лог <имя>.log,
#                       иначе падает на глобальный data_root/logs/main.log
#   --data-root PATH  — override data_root (== MSCODEBASE_DATA_DIR, где logs/)
#   --log PATH        — прямой путь к лог-файлу (максимальный контроль)
_ap = argparse.ArgumentParser(description="Мониторинг индексации MSCodebase Intelligence")
_ap.add_argument("--project", default=None, help="корень проекта (резолв per-project лога)")
_ap.add_argument("--data-root", default=None, help="override data_root (где data_root/logs)")
_ap.add_argument("--log", default=None, help="прямой путь к лог-файлу")
_cli, _ = _ap.parse_known_args()

if _cli.log:
    LOG_FILE = Path(_cli.log)
elif _cli.data_root and "get_main_log_path" in globals():
    os.environ["MSCODEBASE_DATA_DIR"] = _cli.data_root
    try:
        LOG_FILE = get_main_log_path()
    except Exception:  # noqa: BLE001 — резолв-фолбэк
        pass
elif _cli.project and "get_log_dir" in globals():
    try:
        _pp = Path(_cli.project)
        _pl = get_log_dir(_pp) / f"{_pp.name}.log"
        LOG_FILE = _pl if _pl.exists() else get_main_log_path()
    except Exception:  # noqa: BLE001 — резолв-фолбэк
        pass

if not LOG_FILE.exists():
    print(f"⚠️  Лог-файл не найден: {LOG_FILE}", file=sys.stderr)
    print("   (индексация ещё не начиналась, или неверный --project/--data-root). Жду создания...", file=sys.stderr)

# ── Живой прогресс async-переиндексации (job-manager) ──────────
# С 2026-08 (Задача 4/5 + job-manager) per-chunk-строки пишутся в progress.json,
# а НЕ в лог. Лог-парсер показывает устаревиее «Завершено» — читаем progress.json
# как ЕДИНЫЙ источник для intel_trigger_reindex (баг 2026-08-18).
_proj_root = Path(_cli.project).resolve() if getattr(_cli, 'project', None) else _repo_root
PROGRESS_FILE = None
try:
    from src.core.artifact_paths import get_progress_file
    PROGRESS_FILE = get_progress_file(_proj_root)
except Exception:  # noqa: BLE001
    PROGRESS_FILE = None


def read_progress_json():
    """Читает живой прогресс job-manager (progress.json).

    Возвращает dict при активной фазе (phase не пустой/idle), иначе None.
    Является приоритетным источником: лог при async-переиндексации пуст.
    """
    if PROGRESS_FILE is None or not PROGRESS_FILE.exists():
        return None
    try:
        import json
        d = json.loads(PROGRESS_FILE.read_text(encoding='utf-8', errors='replace'))
        if isinstance(d, dict) and d.get('phase') not in (None, '', 'idle'):
            return d
    except Exception:  # noqa: BLE001 — best-effort
        return None
    return None

# ─── Состояние ────────────────────────────────────────────
PHASE_LOADING = "⏳ Загрузка..."
PHASE_PARSING = "📂 Парсинг"
PHASE_PARSED  = "📂 Парсинг готов"
PHASE_EMBED   = "🧠 Эмбеддинг"
PHASE_EMBEDDED = "⚙️  Эмбеддинг готов"
PHASE_WRITING = "💾 Запись в БД"
PHASE_IVF     = "🏗️  IVF индекс"
PHASE_DONE    = "✅ Завершено"

# ─── Скорость: EMA (Exponential Moving Average) ───────────
# α=0.3 — последние измерения весомее, но не мгновенно
EMA_ALPHA = 0.3
recent_ema = 0.0       # EMA скорость (ch/s)
ema_initialized = False

# Текущая фаза и счётчики
phase = PHASE_LOADING
total_chunks = 0
done_chunks = 0
phase_start_time = time.time()

# Пер-фазовые метрики
phase_metrics = {}  # {phase_name: {count, elapsed, speed}}

# Счётчики для DB write
db_files_written = 0
db_chunks_written = 0

# Счётчики для IVF
ivf_started = False

# PID-lock статус
lock_status = "🔒 Ожидание..."
not_found_count = 0
auto_index_status = "⏳"  # ⏳ idle / 🚀 running / ✅ done / ❌ failed

# Таймер
monitor_start = time.time()
last_log_offset = 0  # позиция в файле для инкрементального чтения

# Run ID — отличает текущий запуск индексации от предыдущих
current_run_id = None  # устанавливается при "Auto-index: starting"


def read_log_incremental():
    """Читает только новые строки из лога (быстро, без перечитывания всего файла)."""
    global last_log_offset
    if not LOG_FILE.exists():
        return []
    new_lines = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(last_log_offset)
            for line in f:
                new_lines.append(line.rstrip('\n'))
            last_log_offset = f.tell()
    except Exception:  # noqa: BLE001 — best-effort чтение
        pass
    return new_lines


def reset_run_state():
    """Сбрасывает ВСЁ состояние при новом запуске индексации."""
    global total_chunks, done_chunks, phase, phase_start_time
    global db_files_written, db_chunks_written, ivf_started
    global recent_ema, ema_initialized, not_found_count
    global last_done, last_time, lock_status
    total_chunks = 0
    done_chunks = 0
    phase = PHASE_LOADING
    phase_start_time = time.time()
    db_files_written = 0
    db_chunks_written = 0
    ivf_started = False
    recent_ema = 0.0
    ema_initialized = False
    not_found_count = 0
    last_done = 0
    last_time = time.time()
    lock_status = '🔒 Ожидание...'
    phase_metrics.clear()


def read_log_tail(n=50):
    """Читает последние N строк лога (для начальной загрузки)."""
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return [ln.rstrip('\n') for ln in lines[-n:]]
    except Exception:  # noqa: BLE001 — tail-чтение best-effort
        return []


# ─── Парсеры строк лога ──────────────────────────────────

def parse_embed(line):
    """[embed] 3844/3857 batch=4ch/0.1s=40ch/s avg=20ch/s elapsed=194s"""
    m = re.search(
        r'\[embed\]\s+(\d+)/(\d+)\s+batch=\d+ch/[\d.]+s=(\d+)ch/s\s+avg=(\d+)ch/s\s+elapsed=(\d+)s',
        line
    )
    if m:
        return {
            'done': int(m.group(1)),
            'total': int(m.group(2)),
            'inst': int(m.group(3)),
            'avg_log': int(m.group(4)),
            'elapsed': int(m.group(5)),
        }
    return None


def parse_total_chunks(line):
    """Total chunks: 3857, batch_size=4"""
    m = re.search(r'Total chunks:\s*(\d+)', line)
    return int(m.group(1)) if m else None


def parse_found_files(line):
    """Found 264 files"""
    m = re.search(r'Found\s+(\d+)\s+files', line)
    return int(m.group(1)) if m else None


def parse_db_write(line):
    r"""Записано в БД: src\core\foo.py (12 чанков)"""
    m = re.search(r'Записано в БД:.*\((\d+)\s+чанков\)', line)
    return int(m.group(1)) if m else None


def parse_creating_index(line):
    """Creating index (23071 chunks)..."""
    m = re.search(r'Creating index \((\d+) chunks\)', line)
    return int(m.group(1)) if m else None


def parse_ivf_done(line):
    """IVF_FLAT index created"""
    return 'IVF_FLAT index created' in line


def parse_indexing_complete(line):
    """Indexing complete: 100 new/changed, 0 removed, total 3857 chunks"""
    m = re.search(r'Indexing complete.*?total\s+(\d+)\s+chunks', line)
    return int(m.group(1)) if m else None


def parse_pid_lock(line):
    """🔒 PID lock acquired / 🔓 PID lock released"""
    if 'PID lock acquired' in line:
        return 'acquired'
    if 'PID lock released' in line:
        return 'released'
    if 'Stealing stale PID lock' in line:
        return 'stale'
    if 'PID lock timeout' in line:
        return 'timeout'
    return None


def parse_not_found(line):
    """Not found / lance error / does not exist"""
    line_lower = line.lower()
    if ('not found' in line_lower or 'lanceerror' in line_lower or
            'does not exist' in line_lower or 'no such' in line_lower):
        # Исключаем информационные строки из общего подсчёта
        if 'reset_connection' in line_lower or 'retry' in line_lower:
            return 'self_healed'
        return 'found'
    return None


def parse_auto_index(line):
    """Auto-index: starting / complete / failed"""
    if 'Auto-index: starting background indexing task' in line:
        return 'start'
    if 'Авто-индексация завершена' in line:
        return 'done'
    if 'Авто-индексация не выполнена' in line:
        return 'failed'
    return None


def parse_embed_complete(line):
    """Embed complete: 3857 in 194.3s (20 ch/s)"""
    if not isinstance(line, str):
        return None
    m = re.search(r'Embed complete:\s*(\d+)\s+in\s+([\d.]+)s\s*\((\d+)\s+ch/s\)', line)
    if m:
        return {
            'total': int(m.group(1)),
            'elapsed': float(m.group(2)),
            'speed': int(m.group(3)),
        }
    return None


# ─── EMA скорость ─────────────────────────────────────────

def update_ema(new_speed):
    """Обновляет EMA скорость. Чем больше α, тем быстрее реагирует."""
    global recent_ema, ema_initialized
    if new_speed <= 0:
        return  # не портим EMA нулевыми/отрицательными
    if not ema_initialized:
        recent_ema = new_speed
        ema_initialized = True
    else:
        recent_ema = EMA_ALPHA * new_speed + (1 - EMA_ALPHA) * recent_ema


# ─── Отображение ─────────────────────────────────────────

def fmt_time(seconds):
    if seconds < 60:
        return f"{seconds:.0f}с"
    elif seconds < 3600:
        return f"{seconds/60:.1f}мин"
    else:
        return f"{seconds/3600:.1f}ч"


def fmt_eta(remaining, speed):
    if speed < 0.1:
        return "∞"
    eta = remaining / speed
    return fmt_time(eta)


def bar(done, total, width=30):
    filled = int(width * done / max(total, 1))
    return "█" * filled + "░" * (width - filled)


def render_lock_emoji():
    if 'acquired' in lock_status or '✅' in lock_status:
        return '🔒'
    elif 'stale' in lock_status:
        return '⚠️'
    elif 'timeout' in lock_status:
        return '❌'
    else:
        return '🔓'


def render():
    os.system('cls' if os.name == 'nt' else 'clear')
    now = time.time()
    total_elapsed = now - monitor_start
    avg_log = 0  # инициализация: задаётся в ветке эмбеддинга, но используется в блоке «Тренд» при любой фазе

    print("📊 МОНИТОР ИНДЕКСАЦИИ v3")
    print("─" * 60)
    print(f"  Фаза: {phase}")
    print(f"  Время: {fmt_time(total_elapsed)}")
    print()

    # Живой прогресс job-manager (переиндексация async) — ПРИОРИТЕТ над логом.
    # Если progress.json активен, лог-парсер (старый запуск) вводит в заблуждение.
    live = read_progress_json()
    if live:
        _phase = live.get('phase', 'indexing')
        _progress = int(live.get('progress', 0) or 0)
        _total = int(live.get('total_chunks', 0) or 0)
        _done = round(_total * _progress / 100) if _total else 0
        print(f"  🟢 Job-manager (progress.json): phase={_phase}, {_progress}%")
        if _total:
            print(f"     {bar(_done, _total)} {_progress}%")
            print(f"     {_done}/{_total} чанков")
            print(f"     ETA: {fmt_eta(_total - _done, recent_ema or 31)} | EMA ~{recent_ema:.0f} ch/s")
        else:
            print(f"     {bar(_progress, 100)} {_progress}%")
        if live.get('current_file'):
            print(f"     📄 {live['current_file']}")
        print("─" * 60)
        return False  # живём по progress.json, не выходим на устаревшем «done» лога

    # PID-lock статус
    print(f"  {render_lock_emoji()} Lock: {lock_status}")
    if not_found_count > 0:
        print(f"  🐛 Not Found: {not_found_count} (self-healed: {phase_metrics.get('self_healed', 0)})")
    print(f"  🚀 Auto-index: {auto_index_status}")
    print()

    # Парсинг
    if phase in (PHASE_LOADING, PHASE_PARSING, PHASE_PARSED):
        files_found = phase_metrics.get('parse_files', 0)
        if files_found:
            print(f"  📂 Файлов найдено: {files_found}")
        else:
            print("  📂 Сканирование файлов...")
        print()

    # Эмбеддинг
    if total_chunks > 0 and phase in (PHASE_EMBED, PHASE_WRITING, PHASE_IVF):
        pct = done_chunks / total_chunks * 100
        print(f"  🧠 Эмбеддинг: {bar(done_chunks, total_chunks)} {pct:.0f}%")
        print(f"     {done_chunks}/{total_chunks} ({total_chunks - done_chunks} осталось)")

        # Три скорости: instant (из лога), EMA (взвешенная), log avg (с сервера)
        embed_metrics = phase_metrics.get('embed', {})
        inst = embed_metrics.get('last_inst', 0)
        avg_log = embed_metrics.get('last_avg_log', 0)

        print(f"     Мгновенная: {inst} ch/s | EMA: {recent_ema:.0f} ch/s | Сервер avg: {avg_log} ch/s")
        print(f"     ETA: {fmt_eta(total_chunks - done_chunks, recent_ema)}")
        print()

    # Запись в БД
    if phase in (PHASE_WRITING, PHASE_IVF, PHASE_DONE) and db_files_written > 0:
        print(f"  💾 Записано в БД: {db_files_written} файлов ({db_chunks_written} чанков)")
        print()

    # IVF индекс
    if phase in (PHASE_IVF, PHASE_DONE):
        ivf_chunks = phase_metrics.get('ivf_chunks', 0)
        if ivf_chunks:
            print(f"  🏗️  IVF: индексация {ivf_chunks} чанков...")
        else:
            print("  🏗️  IVF: построение индекса...")
        print()

    # Завершено
    if phase == PHASE_DONE:
        embed_metrics = phase_metrics.get('embed', {})
        embed_elapsed = embed_metrics.get('elapsed', 0)
        embed_speed = embed_metrics.get('final_speed', 0)
        print(f"  ✅ Всего чанков: {total_chunks}")
        if embed_speed:
            print(f"  ✅ Эмбеддинг: {embed_elapsed:.0f}с ({embed_speed} ch/s)")
        print(f"  ✅ Записей в БД: {db_files_written} файлов, {db_chunks_written} чанков")
        print(f"  ✅ Общее время: {fmt_time(total_elapsed)}")
        print()
        print("  🎉 Индексация завершена!")
        print("─" * 60)
        return True

    # Тренд
    if ema_initialized and done_chunks > 0:
        print(f"  Тренд: {'⬆️' if recent_ema > (avg_log or 1) else '➡️'} "
              f"(EMA vs лог avg)")
        print()

    print("─" * 60)
    print("  Ctrl+C для выхода | Обновление 5с")
    return False


# ─── Main loop ────────────────────────────────────────────

os.system('cls' if os.name == 'nt' else 'clear')
print("📊 МОНИТОР ИНДЕКСАЦИИ v3")
print("─" * 60)
print("  Инициализация... чтение лога")
print(f"  Лог: {LOG_FILE}")
if getattr(_cli, 'project', None):
    print(f"  Проект: {_cli.project}")
print("─" * 60)

# Начальная загрузка — последние 200 строк
initial_lines = read_log_tail(200)

# Шаг 1: Находим последний Auto-index: starting — всё ДО него = старый запуск
_last_auto_start_idx = -1
for _i, line in enumerate(initial_lines):
    if parse_auto_index(line) == 'start':
        _last_auto_start_idx = _i

if _last_auto_start_idx >= 0:
    initial_lines = initial_lines[_last_auto_start_idx + 1:]
    _found_complete = any(parse_indexing_complete(ln) or parse_ivf_done(ln) for ln in initial_lines)
    if _found_complete:
        # Последний запуск уже завершился — начнём как будто ничего не идёт
        phase = PHASE_LOADING

# Шаг 2: Обрабатываем строки текущего запуска
for line in initial_lines:
    # ★ Сброс при новом auto-index start
    ai_init = parse_auto_index(line)
    if ai_init == 'start':
        reset_run_state()
        auto_index_status = '🚀 running'
    elif ai_init == 'done':
        auto_index_status = '✅ done'
    elif ai_init == 'failed':
        auto_index_status = '❌ failed'

    ff = parse_found_files(line)
    if ff:
        phase_metrics['parse_files'] = ff

    tc = parse_total_chunks(line)
    if tc:
        total_chunks = tc

    embed = parse_embed(line)
    if embed:
        done_chunks = embed['done']
        total_chunks = embed['total']
        phase_metrics.setdefault('embed', {})
        phase_metrics['embed']['last_inst'] = embed['inst']
        phase_metrics['embed']['last_avg_log'] = embed['avg_log']
        phase_metrics['embed']['elapsed'] = embed['elapsed']
        update_ema(embed['inst'])

    cw = parse_db_write(line)
    if cw:
        db_files_written += 1
        db_chunks_written += cw

    ic = parse_creating_index(line)
    if ic:
        phase_metrics['ivf_chunks'] = ic
        ivf_started = True

    if parse_ivf_done(line):
        phase = PHASE_DONE

    ec = parse_embed_complete(line)
    if ec:
        phase_metrics.setdefault('embed', {})
        phase_metrics['embed']['final_speed'] = ec['speed']
        phase_metrics['embed']['elapsed'] = ec['elapsed']

    ic2 = parse_indexing_complete(line)
    if ic2:
        total_chunks = ic2
        phase = PHASE_DONE

# Определяем начальную фазу
if phase == PHASE_LOADING:
    if total_chunks > 0:
        phase = PHASE_EMBED
    elif phase_metrics.get('parse_files'):
        phase = PHASE_PARSED

last_done = done_chunks
last_time = time.time()

try:
    while True:
        time.sleep(5)

        # Инкрементальное чтение — только новые строки
        new_lines = read_log_incremental()

        # Обрабатываем новые строки
        for line in new_lines:
            # ★ ПЕРВЫМ ДЕЛОМ: ловим Auto-index start → сброс всего
            ai = parse_auto_index(line)
            if ai == 'start':
                reset_run_state()
                current_run_id = time.time()  # noqa: F841 — глобальная
                auto_index_status = '🚀 running'
            elif ai == 'done':
                auto_index_status = '✅ done'
            elif ai == 'failed':
                auto_index_status = '❌ failed'

            # Парсинг файлов
            ff = parse_found_files(line)
            if ff:
                phase_metrics['parse_files'] = ff
                if phase == PHASE_LOADING:
                    phase = PHASE_PARSING

            # Total chunks
            tc = parse_total_chunks(line)
            if tc:
                total_chunks = tc
                if phase in (PHASE_LOADING, PHASE_PARSING, PHASE_PARSED):
                    phase = PHASE_PARSED

            # Embed progress
            embed = parse_embed(line)
            if embed:
                done_chunks = embed['done']
                total_chunks = embed['total']
                phase_metrics.setdefault('embed', {})
                phase_metrics['embed']['last_inst'] = embed['inst']
                phase_metrics['embed']['last_avg_log'] = embed['avg_log']
                phase_metrics['embed']['elapsed'] = embed['elapsed']

                # EMA: только при росте done_chunks (защита от reset)
                now = time.time()
                dt = now - last_time
                if dt > 0.5 and done_chunks > last_done:
                    instant_speed = (done_chunks - last_done) / dt
                    update_ema(instant_speed)
                    last_done = done_chunks
                    last_time = now

                if phase not in (PHASE_WRITING, PHASE_IVF, PHASE_DONE):
                    phase = PHASE_EMBED

            # Embed complete
            ec = parse_embed_complete(line)
            if ec:
                phase_metrics.setdefault('embed', {})
                phase_metrics['embed']['final_speed'] = ec['speed']
                phase_metrics['embed']['elapsed'] = ec['elapsed']
                if phase == PHASE_EMBED:
                    phase = PHASE_EMBEDDED

            # DB write
            cw = parse_db_write(line)
            if cw:
                db_files_written += 1
                db_chunks_written += cw
                if phase in (PHASE_EMBEDDED, PHASE_WRITING):
                    phase = PHASE_WRITING

            # IVF start
            ic = parse_creating_index(line)
            if ic:
                phase_metrics['ivf_chunks'] = ic
                ivf_started = True
                if phase in (PHASE_WRITING, PHASE_EMBEDDED):
                    phase = PHASE_IVF

            # PID lock
            lock = parse_pid_lock(line)
            if lock == 'acquired':
                lock_status = '✅ Acquired'
            elif lock == 'released':
                lock_status = '🔓 Released'
            elif lock == 'stale':
                lock_status = '⚠️ Stale (stolen)'
            elif lock == 'timeout':
                lock_status = '❌ Timeout'

            # Not Found detection
            nf = parse_not_found(line)
            if nf == 'found':
                not_found_count += 1
            elif nf == 'self_healed':
                phase_metrics['self_healed'] = phase_metrics.get('self_healed', 0) + 1

            # IVF done
            if parse_ivf_done(line):
                phase = PHASE_DONE

            # Indexing complete — только если мы в активной фазе
            ic2 = parse_indexing_complete(line)
            if ic2 and phase != PHASE_LOADING:
                total_chunks = ic2
                phase = PHASE_DONE

        # Рендер
        done = render()
        if done:
            break

except KeyboardInterrupt:
    print("\nОстановлен")
