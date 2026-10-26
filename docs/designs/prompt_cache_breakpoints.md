# Design: Prompt Cache Breakpoints

- **Status:** Implemented
- **User-facing:** [CONFIGURATION - Environment variables](../../CONFIGURATION.md#environment-variables), [Agent - Prompt caching](../agent.md#prompt-caching)
- **Implemented:** 2026-10-29 ([PR#696](https://github.com/epam/ai-dial-quickapps-backend/pull/696))
- **Issue:** [#636](https://github.com/epam/ai-dial-quickapps-backend/issues/636)
- **Dependencies:**
  - [Dynamic Tool Discovery](dynamic_tool_discovery.md) — lazily-loaded tools change the tools block
  - [Time Awareness](time_awareness.md) — the timestamp lives in messages, not in the system prompt

## Problem Statement

Every orchestrator iteration resends the full request (`_ChatCompletionConfigBuilder.build`). The tool
definitions and the system prompt come first, and they are the largest part that is identical across
iterations, turns and even conversations of the same app. A user turn with tool calls makes several model
calls, so this prefix is billed at the full input rate every time.

QuickApps never asks for it to be cached:

- On deployments with explicit-only caching (Claude behind the Bedrock and Vertex AI adapters), nothing is
  cached unless the admin presets a request-level breakpoint (see [Alternatives](#alternatives-considered)).
  The Bedrock adapter does not support that preset.
- On a deployment with several upstreams and only `cacheSupported`, Core keeps upstream affinity only for
  prefixes that end at a breakpoint. Without one, a follow-up call can land on another upstream and miss the
  cache.

This design marks up to three cache breakpoints: the system message, the last message and the last tool. The
tools + system prompt part pays off from its 2nd use, by any conversation of the app. The history part pays off
only in a turn that makes a 2nd model call: today the replayed history changes on every turn
([Known Issues](#known-issues)), so a turn with a single call writes the history at 1.25× and never reads it
back.

### How DIAL caching works

**Adapters.** The cache marker is `custom_fields.cache_breakpoint`. Adapters read it on a message, on a tool,
or at request level:

| Adapter | What it does with `custom_fields.cache_breakpoint` |
|---|---|
| Anthropic (Claude API, Foundry) | Message / tool: an explicit `cache_control`. Request level: Anthropic's automatic caching. |
| Bedrock (Claude) | Message / tool: a Converse `cachePoint`. Request level: not supported. |
| Vertex AI | Claude: as the Anthropic adapter. Gemini: ignored; Gemini caches implicitly. |
| OpenAI | No explicit marker for GPT models. Core and the adapter handle automatic caching. |

`aidial_sdk` 0.45 also declares `prompt_cache_breakpoint` on content parts. No DIAL adapter reads it yet. The
likely consumer is OpenAI GPT-5.6+ explicit breakpoints ([Appendix A](#appendix-a-research-provider-caching)).

**DIAL Core** never caches content and never adds breakpoints on its own. It keeps requests that share a
prefix on the same upstream:

- It acts only when the model has `cacheSupported` or `autoCachingSupported`. Both are Core config keys; the
  deployment listing shows them as `features.cache` and `features.auto_caching`.
- It hashes the prefix in the order `tools` → `messages`. It skips `custom_fields`, and it hashes only the
  attachments of `custom_content`. So adding a breakpoint never changes a hash.
- With `cacheSupported`, only positions that carry a breakpoint become routing keys. With
  `autoCachingSupported`, every position does.
- It stores "prefix hash → upstream" in Redis: 10 minutes by default, or the expiry the adapter returns. If
  that upstream fails, `X-DIAL-CACHE-POLICY` decides: `availability-priority` (default) reroutes,
  `cache-priority` retries the same one.
- Model `defaults` are deep-merged into each request. An admin can therefore preset
  `custom_fields.cache_breakpoint` at request level, and it survives a request that carries its own
  `custom_fields`.

## Design Goals

- **G1.** On a deployment with `cacheSupported` (`features.cache`), the tools + system prompt prefix is
  cached and reused across orchestrator iterations, turns and conversations of the same app, and the history
  across the iterations of a turn.

  G1 assumes a byte-stable tools + system prompt prefix for the same app, user and tool set. It holds unless the
  conversation has skills picked from a message or the app has 2 or more MCP or `dial-app` toolsets
  ([Known Issues](#known-issues)). Verified by the local Claude Sonnet 5.5 run in
  [Alternatives](#alternatives-considered) row D.
- **G2.** On any other deployment QuickApps adds no `cache_breakpoint`.
- **G3.** QuickApps never adds a breakpoint that takes the request past 4 (the Anthropic limit), counting
  client breakpoints and a possible Core-default request-level one.
- **G4.** An operator can switch the feature off without changing the model configuration.

---

## Alternatives Considered

| Option | Verdict |
|---|---|
| **A. Admin presets a request-level breakpoint in Core `defaults`** | Already possible with no QuickApps change, and it also caches the history. But the Bedrock adapter does not support it, and it applies to every caller of the deployment. It **composes** with this design: it takes the 1 slot we keep free. Our breakpoints use the default TTL, so the preset must too. |
| **B. QuickApps sends a request-level breakpoint** | Same Bedrock gap. D's last-message breakpoint moves with the history the same way and works on every Claude adapter. |
| **C. One explicit breakpoint on the system message** (the previous draft) | Superseded by D, which keeps it as the first priority. On its own it caches only tools + system. |
| **D. Breakpoints on the system message, the last message and the last tool** | **Chosen.** All Claude adapters support message and tool breakpoints. In a local test (Claude Sonnet 5.5, 5 turns of exactly 2 calls each, ~6.7k-token system prompt, 8 tools) it cut the cost by 66%, against 55% for C. The history is rewritten on every turn ([Known Issues](#known-issues)), so the first call of a turn misses the history entry and only the 2nd call reads it. With 1 call per turn, D costs more than C. |

The system-message breakpoint also caches the tools, because providers cache in the order
`tools → system → messages`. The last-tool breakpoint keeps the tools cached when only the system prompt
changes: an inbound system message with `ALLOW_OVERRIDE_SYSTEM_MESSAGE=true`, skills picked from a message,
or an edited prompt. It costs no extra write tokens while the prefix is stable, only a slot, so it comes last
in priority.

---

## Use Cases

### UC-1: Multi-step tool turn on Claude

**Trigger:** A user message leads to 3 orchestrator iterations on a Bedrock Claude deployment with
`cacheSupported`.
**Behavior:** Iteration 1 reads tools + system prompt if another conversation of the app wrote them, and
writes the history. Iterations 2 and 3 read everything up to the previous call's last message and write only
the new tool call and result.
**Outcome:** Iterations 2 and 3 bill most of their input at the cache-read rate.

### UC-2: Another conversation of the same app

**Trigger:** A second user starts a conversation within the cache TTL (5 minutes, refreshed by every hit).
**Behavior:** Same app, same tool set and no picked skills, so the same prefix. Core routes the call to the
upstream that holds the entry.
**Outcome:** The first call of the new conversation already reads tools + system prompt from the cache.

### UC-3: Deployment without `cacheSupported`, or the feature switched off

**Trigger:** Any request to an OpenAI, Gemini, or not-configured Claude deployment, or to any deployment while
`PROMPT_CACHE_BREAKPOINTS_ENABLED=false`.
**Behavior:** QuickApps adds no breakpoint. Automatic caching works as today.
**Outcome:** The outbound payload carries only the client's own `cache_breakpoint`s, if any.

### UC-4: `tool_search` loads a deferred tool

**Trigger:** The model loads a deferred tool mid-turn.
**Behavior:** The tools block changes, so the next call misses and writes a new entry for the new tool set.
The next turn starts with the eager tools only and reads the first entry again.
**Outcome:** One cache write for each distinct tool set.

### UC-5: The next turn of the conversation

**Trigger:** The user sends the next message within the cache TTL.
**Behavior:** Today the replayed history changes on every turn ([Known Issues](#known-issues)), so the first
call reads tools + system prompt and writes the history again. Once the history is stable, it would read the
history up to the previous turn's last breakpoint.
**Outcome:** Tools + system prompt are read. The history is written again once per turn, and read back only if
the turn makes a 2nd call.

### UC-6: The client sends its own breakpoints

**Trigger:** An API client sends a request with breakpoints on 2 messages, one of them the last message.
**Behavior:** 3 − 2 = 1 free slot. QuickApps places its breakpoint on the system message (priority 1) and
stops. The last message already carries the client's breakpoint, so nothing is lost there.
**Outcome:** The request carries 3 breakpoints, and 1 slot stays free for a Core-default request-level one.

### UC-7: The deployment ships static tools

**Trigger:** The orchestrator deployment has `defaults.tools`, so the tools block ends with `static_function`
tools.
**Behavior:** The last-tool breakpoint skips them and lands on the last `function` tool.
**Outcome:** The request is accepted, and the tools up to the last function tool are cached.

---

## Proposed Design

### 1. Capability gate and kill switch

- **What:**
  - `OrchestratorCapabilities.supports_cache_breakpoints -> bool`, returning `features.cache is True`.
  - `AgentSettings.prompt_cache_breakpoints_enabled`, env `PROMPT_CACHE_BREAKPOINTS_ENABLED`, default `true`.
- **Owner:** `_ChatCompletionConfigBuilder` reads both (it gets `AgentSettings` injected) and calls
  `_PromptCacheBreakpoints.apply` only when both are true.
- **Semantics:**
  - Breakpoints are placed only when both are true.
  - `autoCachingSupported` alone does not turn the feature on: Core and the adapter already cover it.
  - The feature is not behind `ENABLE_PREVIEW_FEATURES`. Its opt-in is the admin's `cacheSupported` flag,
    which an admin sets only for a model whose adapter caches.
- **Change:** a new property, a new setting, and one row in `CONFIGURATION.md`.

### 2. Breakpoint placement

- **What:** A new `_PromptCacheBreakpoints` in `core/agent/_prompt_cache_breakpoints.py`, injected into
  `_ChatCompletionConfigBuilder`. `build()` calls `apply(prepared_messages, all_tools)` after
  `_prepare_messages` and `_merge_tools`.
- **Owner:** the config builder. The slot budget (G3) has to be counted on the final outbound payload, which
  includes client tools, lazily-loaded tools and every transformer's output. The builder is the only place
  that sees all of it, and it already shapes the payload by capability (`_drop_unsupported_reasoning_effort`).
- **Semantics:**
  1. Count the breakpoints the client sent on outbound messages and tools. Their `custom_fields` survive
     `_ScrubExtraFieldsTransformer`, because `custom_fields` is a declared SDK field.
  2. Free slots = 3 − that count. One of the 4 slots is reserved for a possible Core-default request-level
     breakpoint, which QuickApps cannot see.
  3. Fill the free slots in priority order, skipping a target that already carries a client breakpoint:

     | Priority | Target | Caches | Reused by |
     |---|---|---|---|
     | 1 | `messages[0]`, if it is the system message | tools + system prompt | every conversation of the app |
     | 2 | `messages[-1]`, unless it is the system message | tools + system prompt + history | the next iteration of the turn (the next turn too, once the history is stable) |
     | 3 | the last `function` tool | tools | calls where only the system prompt changed |

  - A marked item is replaced by a copy with `custom_fields.cache_breakpoint = {}`. Tool dicts are shared
    across the iterations of a request, so they are never mutated.
  - Static tools (`defaults.tools`, appended after the function tools) are never marked: the SDK's
    `StaticTool` has no `custom_fields`, so SDK-based adapters would reject the request with `400`.
  - Client breakpoints are counted, not inspected: a client TTL is ignored, and ours always use the default.
  - A client breakpoint on the system message never reaches the builder: `_AddSystemPromptTransformer` always
    builds a new system `Message`.
- **Value:** `{}`, i.e. the provider's default TTL (5 minutes).
- **Logging:** DEBUG, with the positions only.
- **Change:** a new class, bound as a singleton in `AgentModule`, and one call in `build()`.

---

## Known Issues

Documented in the "Prompt caching" section of `docs/agent.md`. Unless stated otherwise, the workaround is
`PROMPT_CACHE_BREAKPOINTS_ENABLED=false`.

- **No effect without `cacheSupported`** on the orchestrator deployment. Workaround: set the flag on Claude
  deployments whose adapter caches.
- **Below the model's minimum prefix** (512–4,096 tokens, [Appendix A](#appendix-a-research-provider-caching))
  nothing is cached. No workaround.
- **Writes cost more on Claude.** Tokens written to the cache cost 1.25×. While the history changes on every
  turn (below), the first call of each turn writes the whole history after the system prompt again. A turn with
  a single model call (no tool call) never reads that write back, so it pays 25% more on the history, however
  busy the app is: the history entry belongs to one conversation. Steady traffic helps only the tools + system
  part. At 1.25× per write and 0.1× per read (0.05× on Opus/Sonnet 5.5), the history breakpoint breaks even
  when about 26–28% of turns make a 2nd call.
- **One miss when the tools change:**
  - a `tool_search` load;
  - a different client-sent tool set;
  - the first file attachment, which turns on `available_context` (`should_activate_context_tool`) and,
    with `lazy_on_demand`, the get-content tool (`should_enable_get_content_tool`).
- **One miss when only the system prompt changes.** The tools are still read through the last-tool
  breakpoint; the system prompt and the history are written again:
  - an inbound system message with `ALLOW_OVERRIDE_SYSTEM_MESSAGE=true`;
  - an edited prompt or skill;
  - skills picked from a message. `_InvokedSkillsContext` has `order = -10`, so picks come first in
    `<available_skills>`. The pick turn misses, the conversation stops sharing the app's entry (UC-2), and
    each eviction by the `max_skills` cap misses again.
- **The prefix can change with 2 or more MCP or `dial-app` toolsets.** They load in parallel, and each one
  publishes its results as soon as its server answers, so the order follows the completion order and can
  differ on every request:
  - `_MCPToolInitializer.initialize`: the tool list, the MCP resource cards and the tool-search hint in the
    system prompt, and the `tool_search` description;
  - `_DialAppResolver.resolve`: `resolved_mcp_toolsets` (the MCP toolset list above) and
    `resolved_deployment_tools` (the tools block).

  A request whose order differs misses and writes tools, system prompt and history again. The rest of the
  prefix is already deterministic: the configured prompt parts, the static tools, skills (config order,
  predefined sorted, picks in chip order) and the timestamp, which is a synthetic tool-call pair rather than
  part of the system prompt. Workaround: none. Possible fix in [Out of Scope](#out-of-scope).
- **Load concentration.** On a multi-upstream deployment with only `cacheSupported`, every conversation of an
  app has the same routing key. Core sends them all to the upstream that holds the entry while it lives, and
  falls back only when that upstream is unavailable. Watch rate limits on that upstream.
- **The history misses on the first call of every turn.** Everything after the first user message changes on
  every turn:
  - Synthetic pairs with `APPEND_IF_CHANGED` (the file-transfer `read_skill` pair, config hooks with
    `append_if_changed`) are found in the history and rebuilt in place.
    `SyntheticToolCallInjector._inject_append_if_changed` calls `_enrich_state` even when the pair is identical.
  - With `features.timestamp`, `_TimestampMetadataEnricher` stamps the rebuilt pair with a new
    `response_timestamp`, and `_TimestampAnnotationTransformer` renders it as a new `[Timestamp: …]` line in
    the tool content.
  - Observed in a local test on Claude Sonnet 5.5: every turn's first call read exactly the tools + system entry. The
    stored history does not show it, because the annotation is added when the request is built.

  Other mechanisms rewrite the history too:
  - `_GetContentHistoryPolicy` rewrites `get_content` results when it saves history.
  - Hooks with a TTL `refresh_condition`, or with templated arguments, rewrite their synthetic pair in place.
  - Skill invocations, the file-transfer instruction, MCP eager resources and hooks are first inserted right
    after the first user message.
  - A client `tool_choice` is sent on the first call only, and Anthropic invalidates the messages cache when
    it changes.

  The later calls of the turn hit. Workaround: none short of
  `PROMPT_CACHE_BREAKPOINTS_ENABLED=false`. Possible fix in [Out of Scope](#out-of-scope).

---

## Out of Scope

- **A request-level breakpoint (option B).** The Bedrock adapter does not support it, and the last-message
  breakpoint already moves with the history.
- **Making the history byte-stable across turns** ([Known Issues](#known-issues)). The first step is small:
  `_inject_append_if_changed` returns `messages` unchanged when the found pair's `tool_calls` (call id, name,
  rendered arguments) match the new ones, as its own comment says ("no-op when identical"). Pairs whose TTL
  expiry or templated arguments changed are still rebuilt. Side effect: an unchanged pair keeps the timestamp
  of the turn it first appeared in.
  - A local trial of this change (same Claude Sonnet 5.5 dialog as row D) made every turn's first call read
    the whole previous history: 77% cheaper than without breakpoints, against 66% without the fix. With it, a
    single-call turn no longer pays the +25% history write; only the last call before the user leaves or
    pauses past the TTL does.
  - It changes the shared synthetic-injection mechanism (`append_if_changed` hooks and the file-transfer
    `read_skill` pair), so it belongs in its own change. After it, update UC-5, the "Reused by" column and the
    cost Known Issues.
  - The other mechanisms need their own design.
- **Logging cache counters.** QuickApps reads only `prompt_tokens` and `completion_tokens`, so cache hits are
  not visible in its logs; the adapters return `cached_tokens` and `cache_write_tokens`. Logging those counts
  on "Model call completed" is a separate, small change. Until then, check hits in the provider's usage
  reports.
- **Publishing MCP and `dial-app` toolsets in config order** ([Known Issues](#known-issues)). Possible fix:
  each toolset buffers what it adds, and `initialize` / `resolve` apply the buffers after `gather`, in config
  order, with the interactive-login retry applied together with the first pass. It changes tool and
  resource-card order on every deployment, so it belongs in its own change.
- **`prompt_cache_breakpoint` on content parts.** No adapter reads it. Revisit once the OpenAI adapter maps
  it to GPT-5.6+ explicit breakpoints.
- **Keeping the client's system-message breakpoint in the `ALLOW_OVERRIDE_SYSTEM_MESSAGE` path** (issue
  item 4). `_AddSystemPromptTransformer` rebuilds the system message from its text and drops the client's
  breakpoint, as today. While the feature is active, ours sits at the same position, so nothing is lost.
  While it is inactive because the deployment has no `cacheSupported`, the client's breakpoint would not cache
  anything either. With `PROMPT_CACHE_BREAKPOINTS_ENABLED=false` on a `cacheSupported` deployment, it would
  have cached; that loss is accepted, as today.
- **A 1-hour TTL.** The 2× write pays off only when the same prefix is reused 5–60 minutes apart. Turn the
  feature on with the default first and measure.
- **A per-breakpoint switch** (for example, option C: system and last tool only). The last-message breakpoint
  costs more on apps whose turns mostly make 1 call ([Known Issues](#known-issues)), but making the history
  byte-stable (above) removes that surcharge for every app. Revisit if the cost shows up after that fix.
- **A per-app opt-out.** The cost profile depends on the deployment and its traffic, which the operator
  controls (G4). An app owner has no better information.
- **DIAL deployment tools and sub-agents.** They are separate model calls with their own prefixes, and the
  orchestrator call is the one that repeats within a turn.

---

## Configuration / Usage Examples

Core configuration of a Claude deployment:

```json
"features": { "cacheSupported": true }
```

Outbound request, abridged:

```json
{
  "tools": [ { "type": "function", "function": { "name": "search" }, "custom_fields": { "cache_breakpoint": {} } } ],
  "messages": [
    { "role": "system", "content": "...", "custom_fields": { "cache_breakpoint": {} } },
    { "role": "user", "content": "..." },
    { "role": "assistant", "tool_calls": [ "..." ] },
    { "role": "tool", "content": "...", "custom_fields": { "cache_breakpoint": {} } }
  ]
}
```

Turning it off: `PROMPT_CACHE_BREAKPOINTS_ENABLED=false`.

---

## Migration

### Breaking changes

None.

### Non-breaking changes

- Apps on a deployment with `cacheSupported` start sending the breakpoints.
- **Operator note:** Claude bills a 1.25× write the first time a prefix is seen in each 5-minute window, and
  0.1× (0.05× on Opus/Sonnet 5.5) for each reuse.
  - Tools + system prompt: shared by every conversation of the app, so steady traffic pays less.
  - History: written again on the first call of every turn (Known Issues), and read back only by a 2nd call
    in the same turn. Apps whose turns usually make 2 or more calls pay less; apps with mostly single-call
    turns pay up to 25% more on the history.

## Summary of Changes

| Component | Change |
|---|---|
| `OrchestratorCapabilities` | + `supports_cache_breakpoints` |
| `AgentSettings` | + `prompt_cache_breakpoints_enabled` (`PROMPT_CACHE_BREAKPOINTS_ENABLED`, default `true`) |
| `core/agent/_prompt_cache_breakpoints.py` | New `_PromptCacheBreakpoints` |
| `_ChatCompletionConfigBuilder` | Places the breakpoints |
| `CONFIGURATION.md` | + `PROMPT_CACHE_BREAKPOINTS_ENABLED` row (L1) |
| `docs/agent.md` | + "Prompt caching" section with Known issues (L2) |
| `docs/README.md` | + capability-map row (Stable) linking L1 and L2 |

---

## Appendix A: Research: Provider Caching

Snapshot as of **2026-10-22**, from the providers' first-party docs and pricing pages (see
[Sources](#sources)). Prices are USD per 1M tokens, standard tier, global endpoint. DIAL usually reaches Claude
through Bedrock or Vertex AI and GPT through Azure, whose prices can differ.

### How each provider caches

| | Anthropic (Claude) | OpenAI (GPT) | Google (Gemini) |
|---|---|---|---|
| **Automatic caching** | Only when requested: a top-level `cache_control` places a moving breakpoint on the last cacheable block. | Always on. GPT-5.6+ places an implicit breakpoint at the end of the latest eligible message. Older models use fixed intervals (2,048 tokens on GPT-5.5). | Implicit caching, on by default for Gemini 2.5+. |
| **Explicit control** | Up to **4 breakpoints** per request, on tools, system or message blocks. | GPT-5.6+: `prompt_cache_breakpoint` on content blocks, `prompt_cache_options` (`mode`, `ttl`). Older models: `prompt_cache_key` (routing hint only) and `prompt_cache_retention`. | A separate `cachedContents` resource (generateContent API only). Not on Gemini 4 Argon or the Interactions API. |
| **What is cached** | Prefix in the order `tools → system → messages`. | The full rendered context: instructions, tools, history, structured-output schema. | Prompt prefix. Large common content should go first. |
| **Minimum prefix** | 512 tokens (Opus 5.5, Opus 5, Sonnet 5.5, Haiku 5.5, Fable 5.x); 1,024 (Opus 4.8, Sonnet 5, Sonnet 4.6); 2,048 (Opus 4.7); 4,096 (Opus 4.6/4.5, Haiku 4.5). Shorter prefixes are silently not cached. | 1,024 visible input tokens (GPT-5.6+). On older models it varies with the request settings. | Implicit: 4,096 (Gemini 4 Argon, 3.8/3.6 Flash, 3.1 Pro); 2,048 (2.5 Flash/Pro). |
| **TTL** | 5 min by default, or `1h`. Each hit refreshes the timer for free. | GPT-5.6+: `30m` (default) or `12h` (Responses API only). Older: `in_memory` (≈5–10 min idle, up to 1 h) or `24h`. | Implicit: not documented. Explicit: 1 h by default. |
| **Other limits** | Each breakpoint looks back at most 20 blocks for an earlier entry. Caches are per workspace (per organization on Bedrock and Vertex). | At most 4 cache writes per request. Lookups check the first 2 and the latest 50 explicit breakpoints. | Implicit hits are not guaranteed. Explicit caches are billed for storage. |
| **Usage fields** | `cache_creation_input_tokens`, `cache_read_input_tokens` | `cached_tokens`, `cache_write_tokens` | Cached token count in `usage_metadata` |

DIAL adapters report both counters as `usage.prompt_tokens_details.cached_tokens` and `cache_write_tokens`.

### Explicit breakpoints vs. automatic caching

Does adding our breakpoint hurt a provider that caches automatically?

| | Effect of an explicit breakpoint on the system prompt | Risk |
|---|---|---|
| **Anthropic, automatic mode on** (admin preset, option A) | They compose. The automatic breakpoint takes 1 of the 4 slots, ours takes another. Writes are billed only for tokens past the highest cache hit, so the extra entry costs no extra write tokens: the tools + system tokens would be written by the automatic breakpoint anyway. Two documented `400`s: all 4 slots taken by explicit markers plus the automatic one, and an explicit marker **on the last block** with a different TTL. We leave 1 slot free (§2), but our last-message breakpoint sits on the last block with the default TTL. | None while the preset uses the default TTL. |
| **Anthropic, no automatic mode** | The only way anything gets cached. A miss costs 1.25× on the tools + system tokens; a hit costs 0.1× (0.05× on Opus/Sonnet 5.5). | +25% on that part for a single call with no reuse within 5 min. |
| **OpenAI GPT-5.6+** | Explicit breakpoints **add to** the implicit one, unless `prompt_cache_options.mode` is `explicit`. The implicit breakpoint takes 1 of the 4 write slots. Reuse is lost only in explicit-only mode: a request then checks only its own explicit breakpoints and skips the implicit entries of earlier requests. | None as long as the adapter never sends `mode: explicit`. Not sent today: the gate (§1) never fires for GPT deployments, which use `autoCachingSupported`. |
| **OpenAI ≤ GPT-5.5** | No explicit breakpoint concept. | Not sent (gate). Whether the OpenAI adapter would forward an unknown `custom_fields` to Azure is unverified. |
| **Gemini** | No per-request breakpoint. The Vertex adapter ignores the marker for Gemini; implicit caching continues. | None. Not sent anyway (gate). |
| **DIAL Core routing** | `custom_fields` is excluded from the hash, so the marker never changes a routing key. With `cacheSupported` only, the system breakpoint **becomes** a routing key shared by every conversation of the app. | Load concentration on one upstream (Known issues). |

### Price multipliers vs. base input

| | Cache write | Cache read | Storage |
|---|---|---|---|
| **Anthropic** | 1.25× (5 min), 2× (1 h) | 0.1×; 0.05× on Opus 5.5 / Sonnet 5.5; 0.025× on Fable 5.1 | None |
| **OpenAI GPT-5.6+** | 1.25× (30 min), 2.5× (12 h) | 0.1×; 0.05× on gpt-6.1-sol | None |
| **OpenAI ≤ GPT-5.5** | No surcharge | Per model: 0.1× (GPT-5.5, 5.4-mini/nano), 0.25× (GPT-4.1) | None |
| **Gemini implicit** | No surcharge | 0.1×; 0.05× on Gemini 4 Argon | None |
| **Gemini explicit** | Creation billed as input | 0.1× | Per 1M tokens per hour: $0.50 (3.8/3.6 Flash), $4.50 (3.1 Pro) |

### Prices of mainstream models (USD / 1M tokens)

| Model | Input | Cache write | Cache read | Output |
|---|---:|---:|---:|---:|
| Claude Opus 5.5 | 4.00 | 5.00 (5 min) / 8.00 (1 h) | 0.20 | 20.00 |
| Claude Sonnet 5.5 | 2.00 | 2.50 / 4.00 | 0.10 | 10.00 |
| Claude Sonnet 4.6 | 3.00 | 3.75 / 6.00 | 0.30 | 15.00 |
| Claude Haiku 5.5 (≤100K prompt) | 0.10 | 0.125 / 0.20 | 0.01 | 0.50 |
| gpt-6-astra | 10.00 | 12.50 (30 min) / 25.00 (12 h) | 1.00 | 50.00 |
| gpt-6-sol | 2.00 | 2.50 / 5.00 | 0.20 | 10.00 |
| gpt-6.1-sol | 2.00 | 2.50 / 5.00 | 0.10 | 10.00 |
| gpt-6-luna | 0.10 | 0.125 / 0.25 | 0.01 | 0.50 |
| gpt-5.5 (≤272K) | 5.00 | — | 0.50 | 30.00 |
| gpt-4.1 | 2.00 | — | 0.50 | 8.00 |
| Gemini 4 Argon¹ | 2.00 | — (implicit only) | 0.10 | 10.00 |
| Gemini 3.8 Flash² | 0.75 | — | 0.075 | 3.75 |
| Gemini 3.1 Pro Preview (≤200K) | 2.00 | — | 0.20 | 12.00 |
| Gemini 3.1 Flash-Lite | 0.25 | — | 0.025 | 1.50 |

¹ Until 2026-11-30. From 2026-12-01 the prices are $4.00 / $0.20 / $20.00.
² Until 2026-12-31. From 2027-01-01 the prices are $1.50 / $0.15 / $7.50, and storage is $1.00.

### Worked example: one orchestrator turn

The turn has a 20K-token tools + system prefix and 4 model calls. The example counts input cost for that prefix
only.

| Model | No cache (4 × full price) | With cache (1 write + 3 reads) | Saving |
|---|---:|---:|---:|
| Claude Opus 5.5 | $0.320 | $0.100 + $0.012 = $0.112 | 65% |
| Claude Sonnet 5.5 | $0.160 | $0.050 + $0.006 = $0.056 | 65% |
| gpt-6-sol (automatic, no QuickApps change) | $0.160 | $0.050 + $0.012 = $0.062 | 61% |
| Gemini 3.8 Flash (implicit, if it hits) | $0.060 | $0.015 + $0.0045 = $0.0195 | 67% |

**Break-even.** With a 1.25× write, caching pays off from the 2nd call that reuses the prefix within the TTL
(1.25 + 0.1 = 1.35 < 2). The tools + system entry is shared by every conversation of the app (UC-2), so apps
with steady traffic keep it warm. The history entry belongs to one conversation and, today, to one turn, so it
breaks even only in a turn with 2 or more calls.

### Sources

- Anthropic: [Pricing](https://platform.claude.com/docs/en/about-claude/pricing),
  [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
  [aidial-adapter-anthropic README](https://pypi.org/project/aidial-adapter-anthropic/)
- OpenAI: [Prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching),
  [Pricing](https://developers.openai.com/api/docs/pricing)
- Google: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing),
  [Implicit caching](https://ai.google.dev/gemini-api/docs/caching),
  [Context caching (generateContent)](https://ai.google.dev/gemini-api/docs/generate-content/caching)
- DIAL Core: [Prompt caching tutorial](https://docs.dialx.ai/tutorials/developers/prompt-caching),
  [`models.md`](https://github.com/epam/ai-dial-core/blob/development/docs/dynamic-settings/models.md),
  [`UpstreamCacheService.java`](https://github.com/epam/ai-dial-core/blob/development/server/src/main/java/com/epam/aidial/core/server/service/UpstreamCacheService.java)
- DIAL adapters: [Bedrock README](https://github.com/epam/ai-dial-adapter-bedrock#prompt-caching),
  [Bedrock `converse/caching.py`](https://github.com/epam/ai-dial-adapter-bedrock/blob/development/aidial_adapter_bedrock/llm/converse/caching.py),
  [Vertex AI `dial_api/caching.py`](https://github.com/epam/ai-dial-adapter-vertexai/blob/development/aidial_adapter_vertexai/dial_api/caching.py),
  [OpenAI `utils/caching.py`](https://github.com/epam/ai-dial-adapter-openai/blob/development/aidial_adapter_openai/utils/caching.py)
