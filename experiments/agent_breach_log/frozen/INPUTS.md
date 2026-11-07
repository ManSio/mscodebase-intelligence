# INPUTS — заморожено

Замер: 2026-11-07, HEAD рабочего дерева `D:\Project\MSCodeBase`.

| Файл | sha256 | Строк |
|---|---|---|
| `AGENT_DIARY.md` | `c46d0d1f72d9a86b753c94eaa3986abf31aa582dafffd14c40f0b064e2cdf21b` | 1408 |
| `EXPERIMENTS_LOG.md` | `1e76764b931b2c19b2e6bbde6ef54bcdf36c8099d03ae7ce9777a1d82b53ffb5` | 3692 |
| `tools/knowledge/PATTERNS.md` | `ffb4cf2b4154ccb6df82547262a8ca2fb22d3e4c2f69ed3f443c0c08f0f1ad8c` | 61 |
| `AGENTS.md` | `9038c97dfa0c11a2766d62e8c6544d7501621e722054028e7a7dedbbf2acc73d` | 541 |

Проверка воспроизводимости:

```powershell
Get-FileHash AGENT_DIARY.md,EXPERIMENTS_LOG.md,tools/knowledge/PATTERNS.md,AGENTS.md -Algorithm SHA256
```

Если хэш не совпал — числа ниже относятся к другому состоянию и публиковать их нельзя (§19.11).
