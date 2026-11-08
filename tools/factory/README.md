# factory — task in, tree of one-action operators, journal out

Задача → дерево → исполнение по одному действию за шаг → журнал → независимая проверка.
Модель вызывается **только** чтобы разложить задачу (мозг). Механизмы — детерминированные
операторы: ни одного токена модели на шаг.

```
задача
  │  brain: правила (сейчас) | LLM по OpenAI-совместимому endpoint (опция)
  ▼
дерево (compound → primitive)   ← gate проверяет кодом, а не обещанием
  ▼
executor: один оператор за шаг, бюджет шагов/токенов/времени
  ▼
journal.jsonl  (append-only, hash-chain, sha256 каждого результата)
  ▼
verify: пересчёт цепочки + перезапуск read-only операторов + хэши артефактов
```

## Команды

```powershell
python tools\factory\cli.py ops                     # каталог операторов
python tools\factory\cli.py plan --task "найди ActionReceipt затем запусти тесты tests/test_write_tools.py"
python tools\factory\cli.py run  --task "..."        # rules-мозг → исполнение
python tools\factory\cli.py run  --plan plan.json    # мозг отдал JSON — gate → исполнение
python tools\factory\cli.py llm  --task "..." --endpoint http://192.168.2.5:1234/v1 --model google/gemma-4-26b-a4b-qat
python tools\factory\cli.py verify --journal .factory\journal.jsonl
```

## Операторы (примитивы, 0 токенов модели)

| оператор | args | лимит |
|---|---|---|
| `ls` | path | ≤60 записей |
| `grep` | pattern, glob | ≤40 попаданий, `build/ dist/ .factory/ venv/ __pycache__` исключены |
| `read` | path, start, lines | ≤80 строк с номерами |
| `outline` | path | top-level символы `.py` |
| `run` | cmd | только allowlist (`python -m pytest`, `python -m ruff`, `git status/diff/log`) |
| `write` | path, content | только внутри репозитория, sha256 артефакта в журнал |
| `git` | sub | status / diff / log |
| `deploy` | script | **dry-run**, ничего не исполняет |

## Дерево и подстановки

```json
{"root": {"id":"root","kind":"compound","goal":"...","children":[
  {"id":"t1","kind":"primitive","op":"grep","args":{"pattern":"\\bActionReceipt\\b"}},
  {"id":"t2","kind":"primitive","op":"read","args":{"path":"$t1.hits.0.file","start":"$t1.hits.0.line"}},
  {"id":"t3","kind":"primitive","op":"run","args":{"cmd":"python -m pytest tests/test_write_tools.py -q"}}
]}}
```

Gate (код) отказывает: неизвестный оператор, лишний аргумент, ссылка на несуществующий/будущий
узел, compound без детей, >40 узлов, глубина >6, дубли id, команда вне allowlist.

## Что гарантирует журнал

* каждая запись: `seq, ts, node, op, args, status, sha256, artifact_sha256, digest, prev, hash`;
* `hash = sha256(prev + canonical(entry))` → правка строки ломает цепочку;
* `verify` перезапускает read-only операторы и сравнивает `sha256` (мир изменился ≠ цепочка сломана);
* для `write` сверяется `artifact_sha256` — подмена файла после прогона даёт `artifact-MISMATCH`;
* `run` не перезапускается: записывается `side-effect-recorded` (перезапуск тестов — отдельное решение).

## Пределы, заложенные честно

* правила-мозг **мелкий**: понимает `найди / покажи / тесты / статус / деплой`; для остального — LLM-мозг или свой план;
* `deploy` — dry-run; настоящий выкат не реализован и не должен появляться без явного разрешения;
* операторов 8; чего нет в каталоге — того фабрика не умеет (это цена «ничего не переполняется»);
* бюджет по умолчанию: 25 шагов / ~60k токенов оценки / 900 с.

## Тесты

`python -m pytest tests/test_factory.py -q` → 14 (gate, allowlist, escape, дедуп, журнал,
подделка цепочки, подмена артефакта, бюджет).
