# Embedding tool search: model comparison at 1000 tools

**Status:** Measured (POC, not merged). **Branch:** `poc/tool-search-strategies`
**Related:** [`docs/designs/tool_search_strategies_comparison.md`](../../docs/designs/tool_search_strategies_comparison.md)

## Setup

- **Catalog:** `tools_1000.json`, built by `build_suite.py` from `test_application_1000_tools.json`. 13 toolsets (area/department), 1000 tools, all descriptions open with the same boilerplate.
- **Queries:** `queries_1000.json`, 66 queries.
  - 39 English from `poc/data/queries.json` (one expected tool each).
  - 27 from `queries_extra.json`: 18 multilingual (uk 5, de 4, fr 3, es 3, pl 3), 5 English (one expects two tools), 4 off-topic that should match nothing (en, uk, de).
- **Strategy:** each tool is embedded as `name: description`; a query is embedded and tools are ranked by cosine similarity. No toolset blending (`--toolset-weight 0`), top-k 5, no score floor.
- **Local models:** `sentence-transformers` on CPU, vectors cached per tool in `.cache/`. **DIAL model:** `text-embedding-3-large` through the local Core's embeddings endpoint.
- **Raw output:** `results_1000.txt` (four local models), `results_1000_dial.txt` (`text-embedding-3-large`), and `results_1000_<model>.txt` for the other DIAL models, all with every miss listed (the Cohere file holds the error).
- Reproduce: `python poc/embedding_poc/build_suite.py`, then
  `poetry run python poc/embedding_poc/embedding_search.py eval --model <model> --tools poc/embedding_poc/tools_1000.json --queries poc/embedding_poc/queries_1000.json` (add `--backend dial` for the DIAL model, with `DIAL_URL` and `DIAL_API_KEY` set).

## Legend

- **recall@k**: for each query, the share of its expected tools that appear among the k highest-scoring tools, averaged over the 62 queries that have an expected tool. A query with two expected tools scores 0.5 if only one is in the top k.
  - **recall@1**: the right tool is ranked first. This is what matters if the search returns a single tool.
  - **recall@3 / recall@5**: the right tool is within the first 3 or 5 results. This is what matters if a second stage, such as an LLM selector, picks from a short list. recall@5 close to 1.0 means a shortlist of 5 almost never loses the right tool.
  - recall@1 can never exceed recall@3, and recall@3 can never exceed recall@5.
- **MRR** (mean reciprocal rank): for each query, 1 divided by the rank of the first expected tool (1.0 if first, 0.5 if second, 0.33 if third, and so on), averaged over the same 62 queries. It rewards ranking the right tool near the top and punishes a lower rank more gently than recall@1 does. 1.0 is perfect.
- **Top score (real vs off-topic)**: the cosine similarity of the best-ranked tool, averaged separately over queries that have an answer and over the 4 off-topic queries. A large gap means a score floor can tell "no match" apart.
- **Cold index time**: time to embed all 1000 tools from scratch. **Query time**: mean time to embed one query and rank all tools.

## Parameters used

All runs used the same search parameters, which are the defaults of `embedding_search.py`:

| Parameter | Value used | What it does |
|---|---|---|
| `--top-k` | 5 | Maximum number of tools a search returns. |
| `--min-score` | 0.0 (disabled) | Absolute cosine-similarity floor: tools scoring below it are dropped. |
| `--margin` | 1.0 (disabled) | Tools scoring more than this below the best hit are dropped (relative cut-off). |
| `--toolset-weight` | 0.0 (disabled) | Weight of the parent toolset's similarity added to each tool's score. |

**What these parameters change in the numbers above:** recall@1/3/5 and MRR are computed from the full ranking of all 1000 tools, so they do not depend on `--top-k`, `--min-score` or `--margin`. They measure the ranking quality of the model only. The parameters affect only what a real search would return, which shows in two other metrics:

- **no_match_acc** (share of the 4 off-topic queries that return nothing) is 0.000 in every run, because with the floor disabled the search always returns 5 tools. It is not a quality result.
- **avg_selected** is 5.0 in every run for the same reason.

How each parameter would move quality in production:

- **`--top-k`**: a larger k raises the chance the right tool is in the result (see recall@5 against recall@3) but gives the next stage more candidates, which costs tokens and can add confusion among near-duplicate tools. A smaller k cuts that cost but loses the right tool whenever it ranks below k. With near-duplicate tools, k of 5 to 10 is a reasonable range to test.
- **`--min-score`**: raising it lets the search answer "no match" and returns fewer tools for off-topic queries. If it is too high it also cuts correct tools whose similarity is low, such as a non-English query or a vague one, and recall drops below the recall@k values above. It is model-specific: the safe range is between the off-topic and real-query top scores in the "no match" table (for example, roughly 0.2 to 0.5 for `text-embedding-3-large`, but the range for `multilingual-e5-large-instruct` is only 0.74 to 0.87). The best floor depends on the model and was not tuned on the 1000-tool run.
- **`--margin`**: keeps only tools close to the best score, so a clear match returns 1 to 2 tools and a vague query returns more. A small margin saves tokens but can cut a second expected tool in multi-tool queries. A large margin behaves like plain top-k.
- **`--toolset-weight`**: blends in the parent toolset similarity. It may help when the right toolset is clear but tools inside it look alike, and may hurt when a query spans two toolsets. It was not tested.

On the 20-tool suite, `--min-score 0.4 --margin 0.15` with bge-m3 gave no-match accuracy 1.0 and about 2.9 selected tools per query, with recall unchanged. This has not been repeated on the 1000-tool catalog, so the combined effect of the floor and margin on recall there is unmeasured.

## Quality

recall@k and MRR are defined in the [Legend](#legend).

| Model | Where | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| text-embedding-3-large | DIAL (hosted) | **0.887** | **0.976** | 0.984 | **0.935** |
| gemini-embedding-001 | DIAL (hosted) | 0.879 | 0.960 | 0.968 | 0.927 |
| gemini-embedding-2-preview | DIAL (hosted) | 0.863 | 0.935 | 0.968 | 0.917 |
| amazon.titan-embed-text-v2 | DIAL (hosted) | 0.798 | 0.935 | 0.984 | 0.880 |
| cohere.embed-multilingual-v3 | DIAL (hosted) | not run (Core returns `502 No route`) | | | |
| BAAI/bge-m3 | local CPU | 0.815 | 0.952 | **1.000** | 0.898 |
| intfloat/multilingual-e5-large-instruct | local CPU | 0.879 | 0.935 | 0.952 | 0.922 |
| paraphrase-multilingual-MiniLM-L12-v2 | local CPU | 0.669 | 0.790 | 0.839 | 0.751 |
| Qwen/Qwen3-Embedding-0.6B | local CPU | 0.444 | 0.581 | 0.677 | 0.558 |

### recall@3 by language

The non-English sets have 3 to 5 queries each, so one miss moves a figure a lot.

| Model | en | uk | de | fr | es | pl |
|---|---|---|---|---|---|---|
| text-embedding-3-large | 0.97 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| gemini-embedding-001 | 0.94 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| gemini-embedding-2-preview | 0.93 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 |
| amazon.titan-embed-text-v2 | 0.95 | 0.80 | 0.75 | 1.00 | 1.00 | 1.00 |
| bge-m3 | 1.00 | 0.80 | 0.75 | 0.67 | 1.00 | 1.00 |
| multilingual-e5-large-instruct | 0.98 | 0.80 | 1.00 | 0.33 | 1.00 | 1.00 |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.80 | 0.60 | 1.00 | 0.33 | 1.00 | 1.00 |
| Qwen3-Embedding-0.6B | 0.55 | 0.40 | 0.75 | 0.67 | 1.00 | 0.67 |

## Time

| Model | Parameters | Cold index, 1000 tools | Query time (embed + rank), mean | Notes |
|---|---|---|---|---|
| text-embedding-3-large | hosted | ~131 s | ~1730 ms | query time is dominated by the network call to embed the query |
| gemini-embedding-001 | hosted | ~40 s | ~1380 ms | same note |
| gemini-embedding-2-preview | hosted | ~36 s | ~1510 ms | same note |
| amazon.titan-embed-text-v2 | hosted | ~128 s | ~1230 ms | same note |
| cohere.embed-multilingual-v3 | hosted | not run | not run | Core returns `502 No route` |
| bge-m3 | 568M | ~570 s | ~73 ms | |
| multilingual-e5-large-instruct | 560M | ~468 s | ~199 ms | |
| paraphrase-multilingual-MiniLM-L12-v2 | 118M | ~17 s | ~18 ms | |
| Qwen3-Embedding-0.6B | 600M | ~467 s | ~208 ms | |

Cold index times are single runs on one developer CPU, with other work running, so treat them as rough. The first bge-m3 index took 579 s and 572 s on two runs. Vectors are cached per tool afterwards, so a warm index loads in about 0.1 s.

## "No match" separation

The search always returns top-k, so "no match" needs a score floor. The table shows the mean top score for queries that have an answer against the 4 off-topic queries.

| Model | Real queries | Off-topic | Gap |
|---|---|---|---|
| text-embedding-3-large | 0.555 | 0.091 | 0.46 |
| amazon.titan-embed-text-v2 | 0.530 | 0.108 | 0.42 |
| gemini-embedding-001 | 0.734 | 0.494 | 0.24 |
| gemini-embedding-2-preview | 0.764 | 0.505 | 0.26 |
| bge-m3 | 0.648 | 0.321 | 0.33 |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.617 | 0.189 | 0.43 |
| Qwen3-Embedding-0.6B | 0.868 | 0.590 | 0.28 |
| multilingual-e5-large-instruct | 0.869 | 0.736 | 0.13 |

On the 20-tool suite, `--min-score 0.4 --margin 0.15` with bge-m3 gave no-match accuracy 1.0 and about 2.9 selected tools per query. A floor was not tried on the 1000-tool run, so no-match accuracy there is unmeasured (all rows above ran with a floor of 0).

## Findings

- `text-embedding-3-large` ranks best and is the only model with every non-English query in the top 3. It leaves tool text on the platform and adds about 1.7 s per search in this setup.
- `gemini-embedding-001` is close behind (recall@1 0.879, recall@3 0.960, every non-English query in the top 3) and indexed 1000 tools in about 40 s, a third of the time of the OpenAI and Titan models. Its off-topic scores are high (0.494), so a "no match" floor would be fragile.
- `gemini-embedding-2-preview` is slightly worse than 001 here, and missed one of three Spanish queries (es recall@3 0.67). It is a preview model, so its behavior may change.
- `amazon.titan-embed-text-v2` has the weakest top-1 ranking of the hosted models (0.798) and drops Ukrainian and German queries, but finds the right tool in the top 5 for 98% of queries and separates off-topic queries well.
- All four hosted models finished within about 1 to 2 s per query on this setup. None came close to a local model's query latency.
- `bge-m3` is the best local model: it found the right tool in the top 5 for every query and has the lowest query time of the large models. Its multilingual top-3 ranking is weaker (uk 0.80, de 0.75, fr 0.67).
- `multilingual-e5-large-instruct` ranks well (recall@1 0.879) but its scores are tightly bunched, so a "no match" threshold would be fragile.
- The remaining misses are near-duplicate neighbors: the same function in another team, or the right team with another function. Embeddings alone have trouble with this.
- Per the design doc's deployment constraints, a per-tool vector cache (content-hash key) is what keeps the cold index cost from repeating. The POC cache has this shape.

## Caveats

- **Qwen3-Embedding-0.6B result is not trusted.** It missed many plain English queries. The setup (hand-written instruction prefix, default `sentence-transformers` loading) was not verified, so the model may be misconfigured rather than weak.
- **Small query set.** 66 queries, with 3 to 5 per non-English language. Differences of a few points between the top models are within noise.
- **Synthetic data.** The catalog is generated, with near-identical boilerplate and one query per tool at most.
- **Labels.** One label was fixed after the first run (the vendor-risk query). Labels were written by hand and not independently reviewed.
- **Cohere not run.** `cohere.embed-multilingual-v3` is defined in `models.json`, but every request to it (even a single short input) returns `502 No route` from the local Core, so it has no working upstream here. This is an environment problem, not a model result. Cohere v3 also expects separate `search_document` and `search_query` input types, which this script's generic embeddings call does not set, so a working route would still need an input-type check.
- **No task-specific settings for the hosted models.** The Gemini models support task types and Titan v2 supports output dimensions and normalization. The script sends plain `input` only, so these were not tuned.
- **Query time for the DIAL models** includes the local-to-Core round trip, and Core forwards to a remote upstream. How much of the 1.7 s is network, Core or the upstream was not measured.

## Not yet tried

- `--toolset-weight` (blend the parent toolset similarity into the tool score).
- Embedding a shorter text (`name` plus the first sentence after the boilerplate).
- BM25 plus embedding hybrid, and a "no match" floor on the 1000-tool run.
- Verifying the Qwen3 setup, and other hosted embedding deployments.
