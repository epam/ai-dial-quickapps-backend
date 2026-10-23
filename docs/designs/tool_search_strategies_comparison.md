# Tool search strategies: desk comparison at 1000 tools

**Status:** Findings (desk analysis, not measured)
**Related:** [`scalable_tool_discovery.md`](scalable_tool_discovery.md), POC harness in `poc/` (branch `poc/tool-search-strategies`, not merged)

## Scope

Compares four ways to pick tools inside `internal_tool_search` when the deferred catalog holds about 1000 tools:

1. **LLM, whole catalog** – today's `_AnonymousAgent.route`: one call with the full catalog in the prompt.
2. **Decision-model service (Jev)** – TypeSafe's Jev, a typed decision model (see [Jev](#jev-typesafe)), called with the query as `state` and the candidates as a Choice question.
3. **Embedding container** – a separate service with an embedding model and semantic search.
4. **Two-step** – above a tool-count threshold, search toolset names and descriptions first, then search only the tools inside the matched toolsets (the stage router can be any of 1-3).

Only the catalog size is computed from the test data. Latency figures are estimates from typical model behaviour and vendor claims. Quality claims are reasoned from the data shape and the sources below, not measured here.

## Test data (`test_application_1000_tools.json`)

- 1000 `dial-deployment` tools in one toolset, about 938k characters of `name: description` text, roughly **235k tokens** (characters / 4).
- The tools are roughly department x team x about 12 function types. Descriptions are about 940 characters each and open with the same boilerplate ("A highly specialized research assistant operating within...").
- The distinguishing signal (department, team, function) is compact and also present in the tool name, for example `tech_ai_cybersecurity_competitor_and_peer_benchmarker`.
- Splitting by deployment path gives 13 toolsets (about 75 tools each, `poc/split_toolsets.py --depth 2`) or 74 toolsets (about 12 tools each, `--depth 3`).

## Jev (TypeSafe)

Jev is not a chat model. It is a "System One" decision model: you send a text `state` plus typed questions and it returns constrained answers with probabilities. It does not generate text, explain, or call tools. Facts below are from TypeSafe's docs and a third-party hands-on write-up; benchmark numbers are vendor-reported or from third-party tests on classification workloads, not tool routing.

| Aspect | Jev 1.13 / 1.14 |
|---|---|
| Request limit | 64K tokens (`state` plus all questions) |
| Per-question limit | 32K tokens (`state` plus one question) |
| Long-context mode | 262K for both limits, via a request header; slower and less accurate |
| Question types | Noul (boolean, probability 0-1), Choice (up to **255 options**, probability per option plus confidence), Score (2-10 levels) |
| Modality | Text only |
| Price | $0.042 per million input tokens, output free |
| Latency (vendor) | 70-500 ms end to end; one independent test saw 0.19-0.77 s, with occasional 503 retries |
| Accuracy (reported) | 67.8% agreement vs 74.1% for a frontier LLM on the vendor's workflows; 72.5% vs 84.0% / 79.0% on a 200-item third-party test |

### What the limits mean for a 1000-tool catalog

- **Whole catalog is not possible as one Choice.** 1000 options exceeds the 255-option cap, and 235k tokens exceeds the 64K request limit. Only long-context mode (262K) would hold the text, still not the options cap.
- **Workaround, not recommended:** one Noul question per tool ("is this tool relevant?"), chunked into about 4-5 parallel requests. About 235k tokens per search, at $0.042/M that is roughly $0.01 per search, and the near-duplicate descriptions make independent yes/no probabilities hard to compare.
- **Natural fit: a Choice question over a shortlist of at most 255 options.** That matches the two-step design (stage 1: 13 or 74 toolsets; stage 2: about 12-75 tools) or a retrieved shortlist of 20-50 tools. Each request is a few thousand to about 17k tokens, well inside the limits.
- **Useful properties:** per-option probabilities give a ranked top-k directly, and confidence supports an abstain threshold ("no matching tool"), which plain embedding search lacks. Cost per search is negligible.
- **Risks:** accuracy is below frontier LLMs in the reported tests and was not measured on tool routing or near-duplicate options; text-only, English strongest; no explanation of the choice; occasional 503s need retry handling; it is an external hosted API, so the catalog text (tool names and descriptions) leaves the platform.
- **Unknown:** the exact request/response format and how option text counts toward the per-question limit (check TypeSafe's API reference before implementing). The POC container in `poc/containers/decision/` calls an OpenAI-compatible chat endpoint and would need an adapter for Jev's API.

## Deployment constraints

Three constraints shape which strategies are viable in production, beyond raw speed and accuracy:

1. **The search service is stateless.** It can restart, scale out, and share nothing between replicas.
2. **Every user request searches again.** Once a QuickApp has more than X deferred tools, each request runs `internal_tool_search`, and each user's catalog differs slightly (access filter, per-user MCP listing).
3. **Tool text is mutable.** DIAL deployment tools are identified by id and version and do not change, but MCP servers can be redeployed, so descriptions, titles and even the set of functions can change between requests.

How each strategy copes:

| Strategy | Stateless | Per-request search | Mutable descriptions |
|---|---|---|---|
| LLM or Jev on a candidate list | fine, candidates travel with each call | cost scales with requests, but each call is small (with two-step) | always fresh, nothing cached |
| Embedding with a catalog-hash index (as in the POC) | breaks: index lost on restart, not shared between replicas | breaks: per-user catalogs rarely hash the same, so the cold index build repeats | stale until the hash changes |
| Embedding with a **per-tool** vector cache | works: vectors are a rebuildable cache, not required state | works: users share most tools, so most lookups hit | works: content hash changes with the text |
| BM25 shortlist built per request | fine, no state | milliseconds to tens of milliseconds for 1000 entries | always fresh |

### Per-tool embedding cache (if embeddings are used)

- **Key:** `sha256(name + title + description + embedding model id)`; **value:** the vector. A changed MCP description produces a new key, so no explicit invalidation is needed. Tools that disappear are simply never requested again and age out through LRU or TTL.
- **Freshness:** the QuickApp already lists MCP tools on every request, so current names and descriptions are always at hand. The cache only avoids re-embedding text it has seen.
- **Search:** gather the vectors for this request's tools (embedding only the misses, in one batched call), then compute cosine similarity locally. 1000 vectors are about 6 MB and well under a millisecond.
- **Storage:** an in-process LRU is enough to start (each replica starts cold). Redis is already part of the local stack if sharing across replicas is wanted.
- **Service shape:** the embedding service reduces to a stateless `embed(texts)`, which DIAL's embeddings endpoint already provides. The separate container with `/index` and `/search` is not needed in production.
- **Cold start:** the first search against a new catalog embeds about 235k tokens (about 2-10 s). Do it lazily at the first search, not in the prep step, and let concurrent first requests share one build, so apps that never search pay nothing.

### Natural toolsets

In production the toolsets for two-step search already exist: each MCP server or deployment toolset has its own name and description. The synthetic split (`poc/split_toolsets.py`) is only needed because the test data puts all 1000 tools into one toolset. The weakness is that stage 1 quality depends on those descriptions being specific, and they can change too.

## Comparison

Estimates for a 1000-tool catalog.

| | 1. LLM, whole catalog | 2. Jev (Choice over a shortlist of at most 255) | 3. Embedding container | 4. Two-step (toolsets, then tools) |
|---|---|---|---|---|
| Works on the full 1000 tools in one call | only on 1M-window models | **no** (255-option cap, 64K request limit) | yes | yes |
| Prompt per search | about 235k tokens | about 3k-17k tokens per call on a shortlist or toolset | none (query only) | about 1k (stage 1) + about 17k (stage 2) at 13 toolsets; about 4k + about 3k at 74 toolsets |
| Search latency | about 4-12 s, up to about 20 s, on a long-context fast model; prefix caching may reduce it | about 0.1-0.8 s per call; about 0.2-1.6 s for two stages | warm: about 60-300 ms with a remote embedding API, about 10-30 ms with a local model | about 1.5-3 s with LLM stages (two sequential small calls) |
| Preparation cost | none | none | embedding the tools: about 235k tokens, about 2-10 s cold; only new or changed tools afterwards with a per-tool cache | none |
| Cost per search | highest | negligible (about $0.0001-0.001) | negligible (the index build dominates) | low |
| Context-limit risk | exceeds 128k-200k windows | cap at 255 options and 64K per request | none | none |
| Quality | degrades with 1000 near-duplicate entries; positional bias | below frontier LLMs in reported tests; untested on tool routing; gives probabilities and confidence | good recall, weaker top-1; cannot say "no match" without a threshold | close to each model's small-catalog accuracy; errors compound across stages |
| Failure mode | API errors are swallowed and become `[]` ("no match") | 503s and retries; wrong pick among near-duplicate options | wrong tool ranked first among near-duplicates | stage 1 picks the wrong toolset for a query spanning two toolsets |
| Operations | none | external hosted API, catalog text sent out | stateless embedding call plus a per-tool vector cache (in-process or Redis) | none for the LLM stages |

## Notes per strategy

### 1. LLM, whole catalog
- 235k tokens does not fit most 128k-200k context windows. It only works on a 1M-window model such as Gemini.
- Accuracy usually drops as a prompt fills with near-duplicate entries. StackOne cites Factory.ai research putting the drop at about 30% for a full 128k window, and notes positional bias toward earlier-listed tools. These claims are secondary and unverified.
- `_AnonymousAgent.route` returns `[]` on any API error, so a failed or truncated call is indistinguishable from "no tool matches".

### 2. Jev
- See [Jev](#jev-typesafe). Not usable as a single flat call at 1000 tools. Competitive as the selector inside strategy 4 or after a retrieval shortlist, where its latency and cost are far below an LLM's.
- Accuracy relative to the fast LLM on this task is the open question, since the reported results are on classification workloads.

### 3. Embedding container
- Better at getting the right tool into the top 5 than at ranking it first. Embedding the full boilerplate-heavy description compresses similarity scores. Embedding `name: first sentence after the boilerplate`, or adding BM25 on names, should help.
- Dense retrieval alone is weaker for tools than general retrieval benchmarks suggest (ToolRet, ACL Findings 2025).
- It always returns top-k, so it needs a score threshold to report "no match".
- Do not cache the index by catalog hash: per-user catalogs rarely repeat and MCP descriptions change. Cache vectors per tool instead (see [Deployment constraints](#deployment-constraints)).

### 4. Two-step
- Each call sees a small list, so latency and accuracy sit near the small-catalog regime. Retrieving a subset before the LLM is the approach RAG-MCP reports as cutting prompt tokens by over 50% and raising selection accuracy from 14% to 43% (abstract-level figures, via secondary summaries).
- End-to-end accuracy is stage-1 accuracy times stage-2 accuracy. A query spanning two toolsets (for example an ESG analyst for the real-estate cybersecurity team) can fail at stage 1. Mitigations: take 2-3 toolsets, fall back to flat search when stage 1 returns nothing, write distinct toolset descriptions.
- 13 toolsets (about 75 tools each) balances the two stages. 74 toolsets (about 12 each) makes stage 2 trivial but gives stage 1 a longer, more confusable list.
- Requires real toolsets. The test data has one, so it needs the split.

## Recommendation

- Do not rely on the single-prompt approach at 1000 tools.
Given the [deployment constraints](#deployment-constraints) (stateless service, a search on every request, mutable MCP descriptions), build in this order and stop when recall is sufficient:

1. **Two-step search over the real toolsets**, with Jev or a small LLM as the selector at both stages. No new infrastructure, nothing cached, always fresh.
2. **Add a stateless BM25 shortlist** (built per request from the live listing) when a single toolset is itself large, for example over 255 tools, which is Jev's option limit.
3. **Add embeddings with a per-tool vector cache** (content-hash key) only if BM25 plus the selector does not reach the recall needed. Call DIAL's embeddings endpoint directly; no separate index service.

The end state is retrieve, then select: a merged BM25 and embedding shortlist of 20-50 tools, then a selector picks 3-5, abstaining when top probability or confidence is low. This is the direction of `scalable_tool_discovery.md`. Expected well under 1 s warm with Jev.

Jev is attractive for speed, cost and calibrated confidence, but its accuracy on near-duplicate tool descriptions is unproven. Test it against a small LLM on the same candidate lists before committing.

## What is not known

- Real latency and hit rates. `poc/bench.py` (39 queries with expected tools) measures them once Core and the containers are running; the decision container needs a Jev adapter first.
- Whether the top-5 recall estimates for embeddings hold on these near-duplicate descriptions.
- Stage-1 accuracy on the generated toolset descriptions.
- Jev's exact API shape and how option text is counted against its per-question limit.
- Whether an in-process per-tool vector cache has an acceptable hit rate and memory footprint across real per-user catalogs.
- How specific and stable real MCP toolset descriptions are, which bounds stage-1 accuracy.

## Sources

- [TypeSafe docs: models](https://docs.typesafe.ai/models) – Jev limits, question types, pricing.
- [Hands-on Jev write-up (Terence Luk)](https://blog.terenceluk.com/2026/09/typesafe-jev-system-one-model.html) – latency, 503 behaviour, confidence semantics.
- [Jev third-party benchmark (NeuralTrust)](https://neuraltrust.ai/blog/jev-typesafe-ai-security) and [Jev benchmark (AI/ML API)](https://aimlapi.com/blog/what-is-jev) – accuracy and speed comparisons.
- [Anthropic Tool Search overview (third-party write-up)](https://www.growthmethod.com/anthropic-tool-search/) – no official benchmark figures found, none used here.
- [StackOne: MCP tool search, BM25/TF-IDF hybrid](https://stackone.com/blog/mcp-tool-search-bm25-tfidf-hybrid/) – source of the 30% accuracy-drop and positional-bias claims.
- [RAG-MCP (arXiv 2505.03275)](https://arxiv.org/html/2505.03275v1)
- [ToolRet: Retrieval Models Aren't Tool-Savvy (arXiv 2503.01763)](https://arxiv.org/pdf/2503.01763)
