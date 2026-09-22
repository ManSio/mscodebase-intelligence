"""E3: стоимость gc.collect() в цикле index_project_runner на масштабе прода.
Продуктивный цикл: _all_embeddings=[None]*335013, _flat_chunks=335k пар,
на KАЖДОЙ пачке 32 — gc.collect(). Замер: время gc при растущем списке.
Сравнение: цикл С gc против БЕЗ gc (одни присваивания + структуры).
"""
import sys, time, gc
sys.stdout.reconfigure(encoding='utf-8')

TOTAL = 100_000
BATCH = 32
ROUNDS = 5

# структуры как в проде
_flat_chunks = [(i, "x" * 60) for i in range(TOTAL)]   # text ~203 tok аналогillus
_all_embeddings = [None] * TOTAL
_fake_vec = [0.1] * 384

# цикл БЕЗ gc
t0 = time.time()
for r in range(ROUNDS):
    for i in range(0, TOTAL, BATCH):
        for j in range(BATCH):
            _all_embeddings[i + j] = _fake_vec
el_no = time.time() - t0
print(f"loop {ROUNDS}x{TOTAL} без gc: {el_no:.2f}s ({(el_no/ROUNDS/(TOTAL/BATCH))*1000:.1f}ms/пачку)")

# цикл С gc.collect() на каждой пачке
_all_embeddings = [None] * TOTAL
t0 = time.time()
gc_times = []
for r in range(ROUNDS):
    for i in range(0, TOTAL, BATCH):
        for j in range(BATCH):
            _all_embeddings[i + j] = _fake_vec
        tg0 = time.time()
        gc.collect()
        gc_times.append(time.time() - tg0)
el_gc = time.time() - t0
print(f"loop {ROUNDS}x{TOTAL} С gc:  {el_gc:.2f}s ({(el_gc/ROUNDS/(TOTAL/BATCH))*1000:.1f}ms/пачку)")
print(f"gc.collect() отдельно: p50={sorted(gc_times)[len(gc_times)//2]*1000:.1f}ms "
      f"max={max(gc_times)*1000:.0f}ms calls={len(gc_times)}")
print(f"накладные gc: {el_gc-el_no:.2f}s на {ROUNDS} проходов → "
      f"{(el_gc-el_no)/(ROUNDS*(TOTAL/BATCH))*1000:.1f}ms/пачку чистого gc")

# экстраполяция на прод (335013 чанков / 32 = 10469 пачек)
per_batch_gc_ms = (el_gc - el_no) / (ROUNDS * (TOTAL / BATCH)) * 1000
print(f"\nПРОД 335013 чанков → 10469 пачек → gc-оверхед ≈ {10469*per_batch_gc_ms/1000:.0f}s "
      f"(из ~8ч прогона)")
# проверка: добавляем объекты (1340 live tuple-ов в _file_embeddings? нет — revisit)
print(f"RAM финально: {TOTAL*384*8/1e6:.0f} MB (только fake векторы, прода 335k -> х2.6)")