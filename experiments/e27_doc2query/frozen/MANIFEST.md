# E27 MANIFEST — воспроизводимость

generator: Qwen3-0.6B Q4_K_M (unsloth GGUF, ~400MB) + llama-server b11476
  (commit 98819068, CPU, -c 4096, temps: temperature 0.2, top-p 0.9, max 120 tok).
prompt v2 (amendment pre-run: v1 «1–2 предложения» уходил в списки и упирался
  в max_tokens=120 обрезком на полуслове — verbatim в e27_gen smoke-лог):
  «строго ОДНО предложение до 25 слов… Запрещены списки…» + max_tokens 80.
  v3 (amendment pre-run: /no_think И enable_thinking=false игнорируются —
  80/80 токенов уходит в think, content=""; verbatim в dbg-логах):
  max_tokens 300 + программный strip <think>-блоков, ответ после. Пустой итог
  пишется как EMPTY (честный промах гейта, не повтор).
  v4 (amendment pre-run: temp 0.2 даёт семплированную пустоту — thinking съедает
  весь бюджет на части прогонов; verbatim dbg2 vs smoke): temp 0.0 + seed 42
  (детерминированно); пусто → ОДИН повтор temp 0.2 seed 43, флаг retried в results;
  снова пусто → EMPTY. Сиды зафиксированы в каждом результате.
  (frozen, RU): `Опиши назначение этого Python-файла строго ОДНИМ предложением
  до 25 слов на русском языке. Запрещены списки, заголовки, примеры кода
  и общие рассуждения. Только суть. /no_think\n\nФАЙЛ {relpath}\n```python\n{head}\n```,
  где head = первые 2000 символов файла (шапка: импорты+докстринг+первые def —
  решение про скорость зафиксировано: полный файл на CPU неприемлем).
corpus_gen: 27 файлов E26-корпуса (GOLD_FILES+DISTRACTORS bench_e18).
  Описания verbatim в results/descriptions.json (судья — владелец).
index_arms: R = E26 raw reuse (число, не перегенерация);
  RD1 = raw + DESC (чистая атрибуция описаний; H27-1 именно про неё);
  RD2 = AUGMENTED(E26) + DESC (стек: символы И описания — readout синергии);
  D = DESC-only (тот же чанк-скелет, текст = `FILE + DESC`, без кода).
queries: 17 frozen E18 (до генерации — утечка исключена конструкцией).
scale: время/файл → экстраполяция на весь src (подсчёт .py файлов отдельно).
