# E-09 — upload-bomb защита GitUrlSource (Фаза 2, ТЗ §2.1/§4 upload DoS)

**Дата:** 2026-08-19
**Команда:** `python experiments/universal-engine/e09_upload_bombs.py`
**Статус:** ✅ PASSED (4/4)

## Объект
`GitUrlSource._post_clone_checks` — post-clone лимиты (есть в коде с Фазы 2):
- `max_clone_bytes` (дефолт 500MB) → `too_large`
- `max_file_count` (дефолт 200k) → `too_many_files`
- redirect-check: канонический `remote.origin.url` обязан остаться в allowlist
  (иначе `domain_not_allowed` — защита от редирект-подмены origin)

## Метод
Локальные изолированные деревья (без сети — суть gate post-clone):
1. too_large — дерево ~500KB > лимит 10KB → `too_large`
2. too_many_files — 1000 файлов > лимит 100 → `too_many_files`
3. OK-дерево в лимитах → не бросает (pass)
4. redirect — origin `evil.example.com` вне allowlist → `domain_not_allowed`

## Сырой вывод (хвост)
```
         PASS   дерево по размеру > max_clone_bytes  → too_large
         PASS   1000 файлов > max_file_count=100 → too_many_files
         PASS   дерево в лимитах → pass (не бросает)
         PASS   origin вне allowlist → domain_not_allowed
E-09: 4 cases — 4 PASSED, 0 FAILED
SMOKE E-09: PASSED
```

## Вердикт
Upload-bomb gate работает корректно: оба DoS-вектора (размер, число файлов)
отклоняются машинным kind (`too_large`/`too_many_files` → мапится в INCONCLUSIVE),
OK-путь чист, редирект-подмена origin блокируется. Фаза 2 (GitUrlSource) полностью закрыта.

## Урок
- Post-clone лимиты — правильная вторая линия обороны (SSRF-пред-проверки в `_parse_url`
  + `_resolve_and_check_ips` закрывают сетевую сторону, лимиты — дисковую).
- Тестировать лимиты локально дешёвыми деревьями (не 500MB-клонами) — достаточно для
  проверки механики; константы 500MB/200k — тюнинг, не архитектура.
- Связь: ТЗ §4 «ограничение размера/объёма при клонировании» — реальный DoS-вектор,
  теперь подтверждён тестом.
