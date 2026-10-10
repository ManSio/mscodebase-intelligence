# E18 SOURCES — откуда всё скачано (воспроизводимость без бинарников в репо)

Бинарники и GGUF удалены из дерева (вес ~920MB); всё перекачивается за минуты.
Замеры в results/*.json, версии зафиксированы в results.*.env.llama_version.

## Модели (ggml-org/embeddinggemma-2-GGUF, Apache-2.0, text-only 271M params)
- https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-Q8_0.gguf
  size=309855456 (совпал с Content-Length)
- https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-BF16.gguf
  size=557950176 (совпал с HF API totalFileSize)
- Оригинал: https://huggingface.co/google/embeddinggemma-2 (740M total, ctx 8192, 768-dim, MRL 128/256/512)

## llama-server (первый релиз с arch gemma-embedding2 = b11476)
- https://github.com/ggml-org/llama.cpp/releases/download/b11476/llama-b11476-bin-win-cpu-x64.zip
  size=19441535, 51 entries, `version: 0.6.0-dev (build 11476, commit 988190680)`
- PR #30054 (ngxson, merge 2026-10-06T16:20:31Z, sha 4fbc76dec5) — до него b9940 и b11429
  падают с `unknown model architecture: 'gemma-embedding2'` (см. models/probe_*_stderr.log).
- b11429: https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-win-cpu-x64.zip
  (проверен, arch НЕ поддерживается — удалён)

## Q4/Q3 (addendum)
- unsloth Q4: https://huggingface.co/unsloth/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-UD-Q4_K_XL.gguf
  size=175673856 (совпал с Content-Length)
- prithivMLmods Q3: https://huggingface.co/prithivMLmods/EmbeddingGemma-2-GGUF/resolve/main/embeddinggemma-2.Q3_K_M.gguf
  size=148869408; .../embeddinggemma-2.Q3_K_L.gguf size=154439968 (оба совпали; Q3_K_L — битый файл, см. лог)
- empyrealworks/EmbeddingGemma-2-GGUF — только переупакованный UD-Q4_K_XL (тот же размер 175673856), меньшего нет.
