import time, math, sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

for i in range(24):
    time.sleep(5)
    try:
        import lancedb
        db = lancedb.connect('.codebase_indices/lancedb_v2/index_mscodebase_bfe9644b.db')
        tbl = db.open_table('codebase_chunks')
        n = tbl.count_rows()
        if n > 0:
            print('rows=%d' % n)
            if n >= 4000:
                df = tbl.to_pandas()
                zeros = 0
                norms = []
                for j in range(n):
                    v = df.iloc[j]['vector']
                    if max(abs(x) for x in v) < 1e-10:
                        zeros += 1
                    norms.append(math.sqrt(sum(x*x for x in v)))
                print('ZERO_CHECK: %d/%d zeros' % (zeros, n))
                print('min_norm=%.4f max_norm=%.4f avg_norm=%.4f' % (min(norms), max(norms), sum(norms)/len(norms)))
                v0 = df.iloc[0]['vector']
                print('row0 min=%.4f max=%.4f' % (min(v0), max(v0)))
                break
    except Exception as e:
        pass
print('CHECK_DONE')
