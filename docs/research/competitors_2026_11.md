# Competitor profiles — refreshed 2026-11-11

Scope: `synrag` and `rag-mcp` (the latter = this repository,
<https://github.com/ManSio/mscodebase-intelligence>), requested for the
2026-11-11 overnight run.
Method: GitHub REST API (`/repos`, `/releases`, `/search/repositories`) and the
README/release bodies of the repositories named below, fetched on 2026-11-11.
Every figure is quoted **as the author states it**, together with the
denominator they state (tasks, runs, corpus). Nothing here is measured by us;
none of these numbers may be republished as ours.

Rule for reading this page: a percentage without its corpus, its n and its
command is not comparable to ours (see `docs/FACTS.md` §7 for our own numbers
and the commands that regenerate them).

## synrag — `EnmanuelReynoso23/synrag`

Repository facts (API, 2026-11-11):

| Field | Value |
|---|---|
| Created / last push | 2026-10-05 / 2026-11-09 |
| Stars / forks | 1 / 0 |
| Open issues | 14 |
| License | MIT |
| Language | Python |
| Latest release | `v1.5.0`, published 2026-10-16 |
| Tools | 28 MCP tools; profiles `esencial` = 5, `bajo_demanda` = 2 |
| Stack (self-described) | Tree-sitter AST chunks, BM25 (Tantivy over LanceDB), CPU rerank (TinyBERT/FlashRank), import-impact graph |

### Claimed numbers and their denominators (README, fetched 2026-11-11)

| Claim | Denominator as stated | Source |
|---|---|---|
| **-63.9% billed tokens** (305,736 → 110,338), 95% CI -83% to -24%; correct answers 87% → 94% | 10 multi-step tasks × 2 rounds, Gemini 3.5 Flash-Lite, every token the API bills | README "Measured, not promised" |
| Find/read one function vs grep + reading the range: Flask -36…-38%, Hono -52%; definition first in 92-100% of cases | public repos Flask and Hono | same table |
| Natural-language questions: Flask -37% | same | same |
| Repo packed as signatures: Flask -76%, Hono -84% | same | same |
| Import resolution: 100% coverage, 100% precision | vs the TypeScript compiler and Python `ast` | same |
| Tool definitions cost 2,068 / 412 / 159 tokens per turn | full / `esencial` / `bajo_demanda` profiles | same |
| Latency 59-89 ms median, 3-4 ms cached | CPU only | same |
| **Where it loses:** short tasks **+117%** | tool definitions outweigh the task | same |

### Claim drift inside the project (observed, not ours to judge)

The `v1.5.0` release body (2026-10-16) gives the same "real agent" experiment —
10 multi-step tasks × 2 rounds — as **-29.2%** tokens and **87% → 90%** quality,
with "high variance between rounds". The README (fetched 2026-11-11) gives
**-63.9%** and **87% → 94%** for the same setup. Both numbers are the author's;
the difference is over time and is not explained in either text.

Consequence for reading: when citing synrag, quote the date as well as the
figure, and never mix the two runs.

## rag-mcp — canonical repository

`rag-mcp` in this project's documentation means **this** repository:
<https://github.com/ManSio/mscodebase-intelligence> (MIT, branch `main`).
Canonical mapping confirmed by the owner on 2026-11-12.

The name itself is not unique: `GET /search/repositories?q=rag-mcp+in:name`
returned **2,479 repositories** on 2026-11-11, which is why the mapping is
written down instead of implied. For context only — none of these is what the
docs mean by `rag-mcp` — the nearest candidates by stars:

| Repository | Stars | Last push | Claims metrics? |
|---|---:|---|---|
| `coleam00/mcp-crawl4ai-rag` | 2,268 | 2025-07-25 | no metric table found in README |
| `jerry-ai-dev/MODULAR-RAG-MCP-SERVER` | 1,199 | 2026-03-10 | no metric table found |
| `KelvinQiu802/llm-mcp-rag` | 585 | 2025-04-06 | no metric table found |
| `shinpr/mcp-local-rag` | 429 | 2026-11-04 | **no numbers at all** — README documents tools and settings, not results |

`shinpr/mcp-local-rag` is the closest to our problem shape (local-first, hybrid
semantic + keyword search over documents, MCP + CLI, MIT, LanceDB,
Transformers.js). It makes **no performance claim**, so there is nothing to
compare against and nothing to check.

## What this changes for us

1. synrag publishes the same metric (-% tokens) on the same experiment shape and
   changed its value between the release note and the README. Our own rule
   (one page of numbers, each with its command) is the answer to exactly that
   failure mode.
2. `rag-mcp` resolves to <https://github.com/ManSio/mscodebase-intelligence>;
   the README states the mapping so no mention is ambiguous.
3. No competitor's number is used in our README, CHANGELOG or FACTS.

