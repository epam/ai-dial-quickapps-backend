# Decision-model tool search: results at 1000 tools

**Status:** Partial (POC, not merged). **Branch:** `poc/tool-search-strategies`
**Compare with:** [`../embedding_poc/REPORT.md`](../embedding_poc/REPORT.md) (same catalog and queries)

## Setup

- **Catalog / queries:** the same `tools_1000.json` (13 toolsets, 1000 tools) and `queries_1000.json` (66 queries: 62 with an expected tool, 4 off-topic) as the embedding report.
- **Task:** the model reads tool descriptions and returns tool names. The final list is capped at 10 (`--limit 10`).
- **Modes**
  - **window:** the catalog is split into 10 windows of 100 tools (`--window-size 100`). Each window returns up to 3 candidates (`--per-window 3`), in parallel. A second, **final filter call** gets the union of the candidates and returns the final list.
  - **hier:** stage 1 chooses up to 3 toolsets from the 13 toolset descriptions; stage 2 chooses tools among the tools of the chosen toolsets (about 216).
  - **flat** (one call with the whole catalog, about 230k tokens): not run, see "Not run".
- **Prompt:** the same for all models. It asks for tools that "clearly fit", best first, and allows an empty array. `temperature 0`. The catalog is the system message and the request is the last message.
- **Access:** DIAL Core `/openai/deployments/<model>/chat/completions` (same path as the embedding DIAL runs, so latency includes Core and the upstream). Responses are cached on disk, so reruns do not repay.
- **Price:** high-level only. `prompt_tokens x pricing.prompt + completion_tokens x pricing.completion`, with the prices in `docker_compose_files/core/configuration/generated/models.json`. No cache discounts. Treat as an order of magnitude.
- **Code:** `decision_search.py`. Raw output: `results/<mode>_<model>.txt` (every miss listed). Reproduce:
  `python poc/decision_poc/decision_search.py eval --model <deployment> --mode window --window-size 100 --per-window 3`
  (needs Core on `DIAL_URL`, default `http://localhost:8090`).

## Legend

Same definitions as the embedding report for recall@k and MRR (62 queries with an expected tool). Additional columns:

- **recall@3:** the right tool is among the first 3 of the final list. Because the models return very short final lists (see Findings), recall@3 equals recall@5 and recall@10 for almost every row.
- **Candidate recall (window only):** the right tool is in the union after round 1, before the final filter. It is the ceiling for the final recall.
- **Stage-1 toolset recall (hier only):** the right tool's toolset was among the toolsets chosen in stage 1.
- **No match:** share of the 4 off-topic queries for which the final list was empty. Unlike the embedding runs, decision models can answer this directly.
- **Avg selected:** mean size of the final list on queries with an answer.
- **Time:** mean wall time per query. For window it is the slowest round-1 window plus the final filter; "sum of calls" is the total time of all calls, which is what a rate-limited or single-GPU backend would take.

## Quality, time and price (chat models through DIAL)

| Model | Mode | recall@1 | recall@3 | MRR | No match | Avg selected | Time/query (mean) | Calls/query | Prompt tok/query | Price/query | Price/1000 queries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | window | 0.895 | **0.984** | **0.944** | 4/4 | 1.2 | 3.2 s (sum 17.2 s) | 10.9 | 164,635 | $0.0417 | $41.72 |
| gemini-2.5-flash-lite | window | 0.895 | 0.919 | 0.911 | 4/4 | 1.0 | 3.7 s (sum 21.1 s) | 10.9 | 163,441 | $0.0164 | $16.44 |
| gemini-3.1-flash-lite | hier | 0.863 | 0.887 | 0.879 | 4/4 | 1.5 | 2.5 s | 1.9 | 19,660 | $0.0050 | $4.98 |
| gemini-2.5-flash-lite | hier | 0.815 | 0.839 | 0.831 | 4/4 | 1.3 | 3.6 s | 1.9 | 18,603 | $0.0019 | $1.87 |
| gpt-oss-120b | hier | 0.815 | 0.839 | 0.831 | 4/4 | 1.2 | 6.0 s | 1.9 | 16,826 | $0.0028 | $2.80 |
| gpt-5.4-mini | hier | 0.750 | 0.823 | 0.788 | 4/4 | 1.9 | 4.5 s | 1.9 | 18,685 | $0.0142 | $14.23 |
| gpt-4.1-nano | hier | 0.161 | 0.177 | 0.169 | 4/4 | 0.4 | 2.1 s | 1.4 | 4,927 | $0.0020 | $1.99 |
| amazon.nova-micro-v1 | hier | 0.048 | 0.048 | 0.052 | 4/4 | 0.4 | 2.3 s | 1.1 | 2,522 | $0.0001 | $0.09 |

Window mode round-1 detail:

| Model | Candidate recall | Avg union size | Parse failures | Hallucinated names |
|---|---|---|---|---|
| gemini-3.1-flash-lite | 0.984 | 18.1 | 0/722 | 1/1198 |
| gemini-2.5-flash-lite | 0.968 | 10.2 | 0/721 | 24/915 |

Hier stage-1 toolset recall: gemini-3.1-flash-lite 0.887, gemini-2.5-flash-lite 0.871, gpt-5.4-mini 0.871, gpt-oss-120b 0.855, gpt-4.1-nano 0.242, nova-micro 0.145.

### recall@3 by language

Non-English sets have 3 to 5 queries each, so one miss moves a figure a lot.

| Model | Mode | en | uk | de | fr | es | pl |
|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | window | 1.00 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 |
| gemini-2.5-flash-lite | window | 0.95 | 0.80 | 1.00 | 1.00 | 0.67 | 0.67 |
| gemini-3.1-flash-lite | hier | 0.86 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 |
| gemini-2.5-flash-lite | hier | 0.82 | 0.80 | 1.00 | 1.00 | 0.67 | 1.00 |
| gpt-oss-120b | hier | 0.84 | 0.60 | 1.00 | 1.00 | 0.67 | 1.00 |
| gpt-5.4-mini | hier | 0.84 | 0.60 | 0.75 | 1.00 | 0.67 | 1.00 |

## Comparison with embeddings (same 62 queries)

| Approach | recall@1 | recall@3 | recall@5 | Time/query | Price/query |
|---|---|---|---|---|---|
| Embedding `text-embedding-3-large` | 0.887 | 0.976 | 0.984 | ~1.7 s search (index: ~131 s once, cached) | embedding of 1 query (negligible) + one-time index |
| Embedding `bge-m3` (local CPU) | 0.815 | 0.952 | 1.000 | ~0.07 s (index ~570 s once) | none (local) |
| Decision, window + final filter, gemini-3.1-flash-lite | 0.895 | 0.984 | 0.984 | ~3.2 s | ~$0.042 |
| Decision, hier, gemini-3.1-flash-lite | 0.863 | 0.887 | 0.887 | ~2.5 s | ~$0.005 |

Decision models need no index, so a catalog change costs nothing; embeddings need an index per catalog version but are about 10 to 100x cheaper per query.

## Strands Decider 2B (local, CPU) — small trial only

Run on a developer CPU (no GPU), through `strands-decider serve`, `choice` questions with the tool descriptions as options.

- **Limits found:** the model rejects prompts that do not fit its window (HTTP 422 at 20 tools of full-length descriptions). Descriptions were cut to 160 characters after the shared opening, and calls used 8 options each.
- **Method:** a tournament: windows of 8 tools, top 1 per window (125 windows), then 8-way rounds on the survivors until one list of 5 remained.
- **Result on 3 queries (too few to draw conclusions):** candidate recall 3/3, final recall@3 0.67, recall@1 0.
- **Time:** 146 calls per query, about 12.4 minutes of serial CPU time per query (about 5 s per 8-option call; a single call with 5 full-length options took 8.5 s, with 10 options 85 s while the sweep was running). The "latency 115 s" printed by the script assumes parallel windows, which one CPU server does not give. A GPU (published median 115 ms per call) would make it about 17 s serial per query; this was not measured.
- **Price:** no per-token price (local compute).
- Verdict: not usable on CPU for 1000 tools; needs a GPU or a hosted endpoint before a real comparison.

## Findings

- **Window + final filter beats hier on quality and costs about 8x more.** With gemini-3.1-flash-lite: recall@3 0.984 against 0.887, $41.7 against $5.0 per 1000 queries. The window approach reads the whole catalog on every query (about 165k prompt tokens), so the cost scales with the catalog size.
- **gemini-3.1-flash-lite is the best model here** in both modes, and handles all languages except one Spanish query. It costs 2.5x gemini-2.5-flash-lite for +6.5 points of recall@3 in window mode.
- **The round-1 candidates are nearly complete** (0.97 to 0.98), so almost all window-mode misses are lost in the final filter or are near-duplicate tools, not missed in the windows.
- **Hier is limited by stage 1:** toolset recall (0.86 to 0.89) is about the same as the final recall (0.82 to 0.89), so a wrong toolset is the main loss. The toolsets differ by department, and near-duplicate roles exist in several departments (the same error pattern as embeddings).
- **Small models fail at the routing step:** `gpt-4.1-nano` and `amazon.nova-micro-v1` answered "none fits" for most queries (avg selected 0.4), which gives recall of 0.18 and 0.05. They were cheap and fast but unusable with this prompt.
- **The final lists are short (1 to 2 tools), not 5 to 10,** because the prompt tells the model to return only tools that clearly fit. This is why recall@3 equals recall@10. For the next orchestrator call this is good for token savings but risky when a user request spans two tools; a "return exactly N" variant was not tried.
- **"No match" works** for every model in both modes (4/4), which the embedding runs could not do on 1000 tools without a tuned floor. Empty answers on queries that do have an answer count as misses in recall.
- **Time:** 2.5 to 6 s per query. The window mode is not slower than hier because the 10 windows run in parallel, but the sum of calls (17 to 21 s) matters if the upstream rate-limits.
- **Hallucinated names** are rare, except gemini-2.5-flash-lite in window mode (24/915); they are dropped by the script before scoring.
- gpt-oss-120b is the slowest (6.0 s hier) and returns long outputs (456 completion tokens per query), which is the cost of its reasoning.

## Not run (and why)

- **Flat (single call with all 1000 tools, about 230k tokens):** not run. The sweep was stopped before it, and the long-context candidates (`gpt-4.1`, `gpt-5-mini`, `gemini-2.5-flash`) were not reached or lost their Core route.
- **Window mode for gpt-oss-120b, gpt-5.4-mini; hier and window for claude-haiku-5-5 and gpt-5-mini:** not completed. The runs were stopped manually (slow at 6 parallel workers, about 700 calls per window run).
- **gpt-4.1-mini, gpt-4.1, gpt-5.4-nano, amazon.nova-lite-v1:** they answered in the first route check but later returned `502 No route` from Core during the sweep (and `gpt-5-nano` returned `500 X-UPSTREAM-ENDPOINT header is missing` from the start). This is an environment problem, as with Cohere in the embedding report. `claude-haiku-5-5` rejects `temperature`; the script now retries without it, but it was not rerun.
- **TypeSafe Jev:** skipped on request (needs an API key).

## Caveats

- **Single run per configuration, no repeats.** Temperature 0, but LLM output varies; differences of a few points are within noise (62 queries).
- **Synthetic catalog,** near-identical boilerplate in every description; one expected tool per query in most cases.
- **One prompt for all models.** The weak results of the small models may be a prompt/format mismatch, not a ceiling; the prompt was not tuned per model.
- **Window size 100 and 3 per window were not swept.** Smaller windows would raise candidate recall and cost more calls; the union size (10 to 18) was small enough for one final call.
- **Price is a list-price estimate** from the Core pricing block, without prompt-cache discounts. Cached share was 4 to 47% on some runs, so real cost may be lower.
- **Latency includes Core and the upstream** and is network-dependent; not comparable with the local `bge-m3` row.
- **Decider trial:** 3 queries, shortened descriptions, CPU only.
