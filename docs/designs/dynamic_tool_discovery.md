# Design: Dynamic Tool Discovery

- **Status:** Implemented
- **Issue:** [#430](https://github.com/epam/ai-dial-quickapps-backend/issues/430)
- **Chosen approach:** Option #6

## Problem Statement

All tool definitions (REST API, MCP, DIAL deployment) are merged into one flat list and sent
verbatim to the LLM on every request:

```python
# _chat_completion_config_builder.py
payload["tools"] = self.__tools   # every tool, fully expanded, every call
```

With five or more MCP servers or large REST APIs this can consume ~55 K tokens upfront per turn,
regardless of which tools the model will actually use. This dilutes model attention and degrades
tool-selection accuracy.

**Root cause:** `AgentModule.provide_openai_tools` assembles a single flat `list[OpenAiToolConfigDict]`
at DI-wiring time. There is no mechanism to defer, filter, or paginate that list at request time.

---

## Goals

- Reduce upfront token cost for applications with many tools by deferring full definitions until
  the model indicates it needs them.
- Non-breaking: existing applications that do not opt in behave identically.
- Shaped for future configurability (per-tool granularity, semantic search, result caching)
  without implementing those knobs in MVP.

---

## Codebase Anchors

| What | File |
|---|---|
| LLM payload assembly | `src/quickapp/core/agent/_chat_completion_config_builder.py` |
| Tool list DI wiring | `src/quickapp/core/agent/agent_module.py` (`provide_openai_tools`) |
| MCP schema loading | `src/quickapp/mcp_tooling/_mcp_tool_initializer.py` |
| Existing lazy-injection precedent | `src/quickapp/orchestrator_attachment_strategies/lazy_on_demand/` |
| Toolset config root | `src/quickapp/config/toolsets/toolset.py`, `BaseToolSet` |
| Internal tool base | `src/quickapp/common/staged_base_tool.py` (`StagedBaseTool`) |
| Stream parsing | `src/quickapp/common/chat_completion_stream/parse.py` |
| Orchestrator loop | `src/quickapp/core/agent/orchestrator.py` |

---

## Decision Points

Four orthogonal decisions drive the design space:

| # | Decision | Choices |
|---|---|---|
| A | **Deferral granularity** | Per-toolset vs per-tool |
| B | **Discovery surface** | Keyword search · Compact manifest · Semantic search · Subagent-based |
| C | **How full definitions reach the LLM** | As tool-call result text · Injected into `payload["tools"]` · Server-side expansion (`tool_reference`) |
| D | **Provider scope** | Model-agnostic (any DIAL deployment) vs Anthropic-native API feature |

---

## Options

### Option 1 — Per-toolset deferred flag + custom keyword-search discovery tool

**Mechanism:**
Add `deferred: bool = False` to `BaseToolSet`. When `deferred=true`, the toolset does not
contribute its tool schemas to `payload["tools"]`. Instead it contributes a single internal
discovery tool:

```
{toolset_name}_discover(query: str) → list[{name, description, parameters}]
```

The tool performs a keyword match on tool name + description and returns full definitions as
JSON text in the tool-call result. The LLM reads the definitions from context and then makes
the actual tool call.

**Round-trip cost:** +1 before first tool use (discover → read result → call tool).

**MCP init:** schemas still fetched at startup (no change); they are just withheld from
`payload["tools"]` until discovered.

**Config example:**
```json
{
  "name": "my-mcp-server",
  "type": "mcp",
  "deferred": true,
  "server": { "url": "..." }
}
```

**Pros:**
- Follows `LazyOnDemandStrategyModule` pattern exactly — no orchestrator changes.
- Model-agnostic: works with any DIAL deployment.
- Non-breaking opt-in.
- Token savings are immediate (entire toolset suppressed).

**Cons:**
- Model must understand and follow the discovery protocol → system-prompt engineering required.
- Full definition returned as text; the model cannot use the schema for structured argument
  generation on the same call (requires an extra round-trip to actually call the tool natively).
- Keyword search quality may be insufficient for large or ambiguously-named tool catalogs.

---

### Option 2 — Compact manifest upfront + single `get_tool_definition` tool

**Mechanism:**
All tool names + one-line descriptions (no `parameters`) are sent upfront, either as a
minimalist `tools` array (empty parameters) or as a structured section in the system prompt.
A single internal tool `get_tool_definition(tool_name: str)` returns the full `OpenAiToolConfig`
JSON for any tool on demand.

**Round-trip cost:** +1 before first use of any previously-unseen tool.

**Config:** opt-out flag per-toolset (`deferred: false` to disable for a specific toolset).

**Pros:**
- Model always has full name-space visibility (all names + descriptions visible).
- Single shared discovery tool regardless of toolset count.
- Model-agnostic.

**Cons:**
- Manifest can still be substantial for 100+ tools.
- Full definition returned as text; same two-round-trip issue as Option 1.

---

### Option 3 — Orchestrator-level dynamic tool injection

**Mechanism:**
A discovery tool returns tool names. The orchestrator intercepts the result and **injects the
corresponding full schemas into `payload["tools"]` on the next LLM call** — not into the
message history. The model then uses the tool natively with proper schema-based argument
generation.

**Changes required:**
- Orchestrator maintains `_discovered_tool_names: set[str]` state across iterations.
- `_ChatCompletionConfigBuilder` accepts a per-request "additional tools" override.
- Discovery tool result processed as a side-effect before the next iteration.
- Discovered names must optionally be persisted in conversation state for multi-turn continuity.

**Round-trip cost:** +1 (discover call → definitions in `tools` array → native call).

**Pros:**
- LLM interacts with discovered tools natively (proper schema, no prompt workarounds).
- Cleanest UX: discovered tools behave identically to pre-loaded ones from the model's perspective.
- Model-agnostic.

**Cons:**
- Significant orchestrator changes.
- Discovered-tool state must survive across iterations and possibly across conversation turns.
- More complex error paths.

---

### Option 4 — Anthropic native `defer_loading` + server-side Tool Search

**Mechanism:**
Anthropic's Messages API supports `defer_loading: true` on individual tool definitions and a
built-in server-side search tool. The API runs the search on Anthropic's infrastructure and
returns `tool_reference` blocks that it auto-expands into full definitions before the model sees
them.

**API contract:**
```json
{
  "tools": [
    { "type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25" },
    {
      "name": "my_tool",
      "description": "...",
      "input_schema": { ... },
      "defer_loading": true
    }
  ]
}
```

- `defer_loading: true` controls what enters the **model's context window**, not what is sent
  over the wire. All definitions are still transmitted to the API on every request.
- The API excludes deferred tools from the system-prompt prefix → **prompt cache is preserved**.
- Two search variants: `tool_search_tool_regex_20251119` (Python regex patterns) and
  `tool_search_tool_bm25_20251119` (BM25 natural-language queries).
- Supports up to **10,000 deferred tools**.
- The response contains `server_tool_use` and `tool_search_tool_result` blocks (server-executed;
  no client `tool_result` reply needed for these) plus a `tool_reference` block that the API
  expands automatically.

**Model support:** Claude Haiku 4.5, Sonnet 4.5, Opus 4.5 and all newer models.
Claude Opus 4.1 and earlier do not support this feature.

**Custom client-side variant:** The `tool_reference` response format is also usable by a
custom search tool (embedding-based, semantic, etc.): return `tool_reference` blocks in a
standard `tool_result`, and the API expands them the same way.

**Changes required in QuickApp:**
1. `_ChatCompletionConfigBuilder` — optionally set `defer_loading: true` on tool dicts and
   include the tool search tool entry.
2. `parse.py` / stream handler — parse `server_tool_use` and `tool_search_tool_result` block
   types (currently unknown to the parser).
3. `orchestrator.py` message builder — preserve `server_tool_use` and `tool_search_tool_result`
   blocks verbatim in the ASSISTANT message history (do not treat them as executable tool calls).
4. Config — a new `OrchestratorConfig.tool_search` sub-config controlling search variant and
   which toolsets/tools to defer.
5. Capability detection — fall back gracefully when the orchestrator deployment is not an
   Anthropic model that supports this feature.

**Round-trip cost:** +1 search turn. But definitions are expanded server-side within that
same turn, so the model can call the discovered tool in the very next turn with no extra
client round-trip.

**Pros:**
- No custom search implementation to maintain — Anthropic handles indexing, matching, and
  schema expansion.
- Prompt cache preserved (deferred tools excluded from the stable prefix).
- Native `tool_reference` expansion means the model always works with real tool schemas.
- Supports per-tool granularity on the API side.

**Cons:**
- **Not model-agnostic**: only works when the orchestrator deployment exposes Anthropic's
  Messages API (Claude Sonnet/Opus 4.5+). Other DIAL deployments (GPT-4, Gemini, etc.)
  do not have this feature.
- Full definitions still transmitted to the API on every request (wire cost unchanged, only
  context-window cost reduced).
- New block types (`server_tool_use`, `tool_search_tool_result`, `tool_reference`) require
  changes to the stream parser and message history handling.
- `defer_loading: true` and `cache_control` cannot be set on the same tool (API returns 400).

---

### Option 5 — MCP-protocol progressive discovery (three-layer)

**Mechanism:**
Follows the [MCP client best practices](https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices)
progressive discovery pattern. The host fetches all tool definitions via `tools/list` at startup
but exposes them to the model through a three-layer surface:

| Layer | Tool | What it returns |
|---|---|---|
| 1 — Catalog | `search_tools(query)` | `[{name, description}]` — names + one-liners only |
| 2 — Inspect | `get_tool_details(name)` | Full `inputSchema` for one tool |
| 3 — Execute | `{tool_name}(...)` | Normal tool execution |

Full definitions enter the context only at Layer 2, after the model identifies the specific
tool it wants. When implemented with custom client-side `tool_reference` blocks (see Option 4
custom variant), the Layer 2 inspection call can be eliminated and the Layer 1 result can
directly expand into full definitions.

**Threshold recommendation (from MCP spec):** switch to progressive discovery once tool
definitions exceed 1–5% of the model's context window.

**Dynamic server management extension:** connect MCP servers lazily — maintain a server
registry, connect only when the model requests a server's capabilities. Requires changes to
`_MCPToolInitializer` to support deferred connection and `tools/list` fetching.

**Round-trip cost:** +1 (search) or +2 (search + inspect) before first tool use.

**Pros:**
- Fully model-agnostic (any LLM; no Anthropic-specific API features).
- Covers both tool-level and server-level deferral.
- Aligns with the emerging MCP ecosystem standard, future-proofing integration as MCP
  clients converge on this pattern.
- Layer 2 (inspect) is optional: with Option 4's `tool_reference` extension it collapses to
  a single extra round-trip.
- `list_changed` notification support (already a concept in MCP) enables cache invalidation.

**Cons:**
- Two round-trips (catalog + inspect) in the full three-layer form.
- Dynamic server management is a significant additional change (`_MCPToolInitializer`,
  connection lifecycle, reconnect on demand).
- Without the `tool_reference` trick (Option 4 custom variant), full definition is returned as
  text — same schema-generation problem as Options 1–2.

---

### Option 6 — `DeferredToolsContext` + anonymous agent search + lazy schema injection (Recommended, chosen)

**Mechanism:**
At request time, toolset initializers (MCP, REST, and internal) split their output between the
normal `list[StagedBaseTool]` (eager tools) and a shared `DeferredToolsContext` (deferred tools).
A single `tool_search` meta-tool is injected; when triggered it fires an isolated "anonymous agent"
chat completion that consults only the deferred catalog, then stores the matched tools' full
schemas in a request-scoped `LazyLoadedToolsHolder`, which `_ChatCompletionConfigBuilder` merges
into `payload["tools"]` on the next build. No Anthropic-specific API features are required, and
**no orchestrator changes were needed** — the mechanism is entirely local to the `tool_search`
tool's own execution and the request-scoped holder it writes to.

> **As built:** the sections below describe the mechanism as originally proposed. Where the
> landed implementation differs, an **As built** note calls it out. See the
> [Changes required](#changes-required) table for the final shape.

#### Step 1 — Request initialisation

When a new chat completion request arrives, toolset initializers run as today and build full
`OpenAiToolConfig` definitions. They then apply the deferral decision per toolset (the real
predicate, `is_toolset_deferred` — note the tri-state `deferred` field, see
[Deferral threshold](#deferral-threshold)):

```
if is_toolset_deferred(toolset, discovery_cfg, len(tools)):
    → register {name, description} entries + full definitions with DeferredToolsContext
    → the same tools are still appended to the module's own list[StagedBaseTool]
      (they exist as StagedBaseTool instances throughout — deferral only withholds
      their *schema* from the initial LLM payload, in AgentModule.provide_openai_tools)
else:
    → nothing extra happens; the tool is eager as today
```

**As built:** REST API and MCP toolsets support deferral (`rest_api_tooling_module.py`,
`_mcp_tool_initializer.py`). Internal toolsets also support it. `dial-deployment` and `dial-app`
toolsets do not yet call `is_toolset_deferred` — setting `deferred` on those has no effect today
(tracked as a follow-up).

`DeferredToolsContext` holds two structures across all deferred toolsets in the request (not
one instance per toolset — a single request-scoped context aggregates all of them):
- **catalog**: `list[{name, description}]` — compact, never forwarded to the main LLM
- **definitions**: `dict[str, OpenAiToolConfigDict]` — full schemas (transformed the same way
  as eager tools — const params stripped, `enrich_openai_tool_schema` applied), looked up by
  `_ToolSearchTool` when the anonymous agent returns matches

Toolsets with `deferred: false`, or that fall below the tool-count threshold, stay eager —
`AgentModule.provide_openai_tools` includes them in `payload["tools"]` directly.

#### Step 2 — Main orchestrator call

`payload["tools"]` is built from the eager `list[StagedBaseTool]` plus the single `tool_search`
meta-tool injected by `AgentModule`. Deferred tools are **absent**.

```
payload["tools"] = [tool_search, ...eager tools from RequestContext]
payload["messages"] = full conversation history
```

The description of `tool_search` explicitly states that additional tools are available and can
be discovered on demand, so the model knows to search before assuming a capability is missing.

**As built:** the description also carries a dynamic, per-request section listing every currently
deferred toolset by name, its tool count, and its own `description` (when set) — e.g. "Additional
toolsets available for discovery: - salesforce. Available tools: 12. Query and update Salesforce
records". This is built in `_ToolSearchTool.enrich_openai_tool_schema` from
`DeferredToolsContext.toolset_summaries`, giving the model a hint about *what* (and how much) is
hidden, not just that *something* is discoverable — without the per-tool schema cost that listing
every tool upfront would incur.

#### Step 3 — `tool_search` execution: anonymous agent

When the orchestrator calls `tool_search(query)`, its handler delegates to a new
**`AnonymousAgent`** module — a self-contained, isolated chat completion with no conversation
history and no system prompt from the main request:

```
model:   service_model (config: defaults to orchestrator deployment)
system:  "You are a tool routing assistant. Given a user query, return the names of
          the tools from the following catalog that are most relevant.
          Catalog: [{name, description}, ...]"   ← injected from DeferredToolsContext
messages:[{"role": "user", "content": <query>}]
tools:   none
```

The anonymous agent returns a list of tool names. Because this call carries no conversation
history and no application system prompt, its token cost is bounded by the catalog size alone.

**Result returned to the main LLM:** `[{name, description}]` of matched tools, confirming what
is now available to load.

#### Step 4 — `_ToolSearchTool` builds OpenAI definitions

Rather than a separate lazy-initializer module, `_ToolSearchTool` (a `StagedBaseTool`) itself
looks up each matched name in `DeferredToolsContext.get_definition(...)` and passes the
corresponding `OpenAiToolConfigDict` objects to `LazyLoadedToolsHolder.add(...)`. No LLM call is
made at this step.

#### Step 5 — Lazy schema injection (no orchestrator involvement)

**As built, this differs from the original proposal:** there is no orchestrator-side interception
or `_lazy_loaded_tools` state inside `orchestrator.py`. Instead:
1. `LazyLoadedToolsHolder` is a request-scoped holder (`core/agent/lazy_loaded_tools_holder.py`)
   that `_ToolSearchTool` writes into directly during its own tool-call execution.
2. On every subsequent `_ChatCompletionConfigBuilder.build()` call within the same request,
   the builder reads `lazy_loaded_tools_holder.get_all()` and merges those definitions into
   `payload["tools"]`, de-duplicated by function name against the eager tools.
3. The orchestrator loop is completely unaware of tool discovery — it just re-builds the payload
   each iteration as it always did, and the holder's contents are picked up automatically.

The main LLM now sees the discovered tools natively alongside `tool_search` and the eager tools,
and calls them with proper schema-based argument generation.

Cross-turn persistence (serialising discovered tool names into
`custom_content.state["lazy_loaded_tools"]` so rediscovery is skipped on the next user message)
was **not implemented** — see [Out of Scope](#out-of-scope-mvp).

#### Flow diagram

```
New request arrives
  │
  ├─ MCP/REST/internal initializers: len(tools) >= threshold → DeferredToolsContext
  │                                                           (catalog + definitions)
  │                                  len(tools) < threshold  → eager list[StagedBaseTool]
  │
  ▼
Orchestrator — iteration 1
  payload["tools"] = [tool_search, ...eager tools]
  payload["messages"] = full conversation history
  │
  └─ Main LLM calls tool_search("I need to query Salesforce contacts")
        │
        └─ _ToolSearchTool → _AnonymousAgent (isolated chat completion):
              model   = service_model
              system  = routing prompt + catalog from DeferredToolsContext
              message = "I need to query Salesforce contacts"
              → ["sf_query_contacts", "sf_list_contacts"]
           _ToolSearchTool: names → full OpenAiToolConfigDicts, written into
           LazyLoadedToolsHolder (request-scoped; orchestrator is not involved)
           Result returned to main LLM: [{name, description}, ...]

Orchestrator — iteration 2
  _ChatCompletionConfigBuilder reads LazyLoadedToolsHolder.get_all() and merges:
  payload["tools"] = [tool_search, ...eager tools,
                      sf_query_contacts ←injected,
                      sf_list_contacts  ←injected]
  │
  └─ Main LLM calls sf_query_contacts(filter="LastName='Smith'") natively ✓
```

#### Deferral threshold

A toolset is only placed into `DeferredToolsContext` if `is_toolset_deferred` returns true.
`deferred` is a tri-state field (`bool | None`, default `None`/unset) — unset **or** `true`
both defer; only an explicit `false` forces eager regardless of count:

```python
def is_toolset_deferred(toolset, discovery_cfg, tool_count) -> bool:
    return (
        toolset.deferred is not False
        and discovery_cfg is not None
        and discovery_cfg.enabled
        and tool_count >= discovery_cfg.min_tools_for_deferral
    )
```

Below the threshold — or when `tool_discovery` is disabled/unset entirely — a toolset is loaded
eagerly, no discovery overhead.

#### Configuration

```json
{
  "orchestrator": {
    "tool_discovery": {
      "enabled": true,
      "service_model": "claude-haiku-dial-deployment",
      "min_tools_for_deferral": 5
    }
  },
  "tool_sets": [
    {
      "name": "salesforce",
      "type": "mcp",
      "deferred": true,
      "server": { "url": "..." }
    },
    {
      "name": "internal-utils",
      "type": "internal",
      "deferred": false
    }
  ]
}
```

- `deferred: true` (or unset/`null`) opts the toolset into `DeferredToolsContext`. Default: `true` (omitting the field defers by default).
- `service_model` names the DIAL deployment used for the `AnonymousAgent` chat completion.
  When omitted, falls back to the orchestrator's own deployment.
- `min_tools_for_deferral` is the tool-count guard below which a deferred toolset is silently
  promoted to eager. Default: `5`.
- Non-deferred and below-threshold toolsets populate `RequestContext` immediately, as today.

#### Changes required (as built)

| Area | Change |
|---|---|
| `BaseToolSet` (`config/toolsets/base.py`) | Add `deferred: bool \| None` field (tri-state, default `None`/unset — unset behaves as deferred, see [Deferral threshold](#deferral-threshold)) |
| `config/tool_discovery.py` | New `ToolDiscoveryConfig` (`enabled`, `service_model`, `min_tools_for_deferral`), referenced by `OrchestratorConfig.tool_discovery` |
| `shared/deferred_tools/` (`DeferredToolsContext`, `is_toolset_deferred`) | Request-scoped shared object aggregating `catalog`/`definitions` across all deferred toolsets in the request; `is_toolset_deferred` is the pure threshold predicate. Bound via its own `DeferredToolsModule`, spliced into `shared_module` |
| REST, MCP, internal toolset modules | After building each toolset's tools, evaluate `is_toolset_deferred`; register with `DeferredToolsContext` or leave in the eager `list[StagedBaseTool]` accordingly. **`dial-deployment`/`dial-app` toolsets do not yet do this** — follow-up |
| `tool_discovery/_anonymous_agent.py` (`_AnonymousAgent`) | Fires a single isolated `chat.completions.create` call (no history, no app system prompt); takes the catalog and a user query; returns matched tool names |
| `tool_discovery/_tool_search_tool.py` (`_ToolSearchTool`) | Internal `tool_search` (registered name: `internal_tool_search`) tool injected via `ToolDiscoveryModule`'s own `@multiprovider` (preview-gated); calls `_AnonymousAgent`, looks up matched names in `DeferredToolsContext`, writes results into `LazyLoadedToolsHolder`, returns `[{name, description}]` to the main LLM. Its own `enrich_openai_tool_schema` override appends a dynamic list of deferred toolset names/descriptions (`DeferredToolsContext.toolset_summaries`) to the static tool description |
| `core/agent/lazy_loaded_tools_holder.py` (`LazyLoadedToolsHolder`) | Request-scoped holder of discovered `OpenAiToolConfigDict`s — replaces the originally-proposed lazy-initializer + orchestrator-side `_lazy_loaded_tools` state |
| `tool_discovery/_tool_search_hint_prompt_provider.py` (`_ToolSearchHintPromptProvider`) | System-prompt-level reminder to call `internal_tool_search` before declaring a limitation, plus the same deferred-toolset summary list (name, tool count, description — via the shared `_toolset_summary_format.format_toolset_summaries`) that `_ToolSearchTool.enrich_openai_tool_schema` appends to the tool's own description. Contributed by `ToolDiscoveryModule`'s own `_provide_prompt_parts` (preview-gated, same condition as the tool itself). `ToolDiscoveryModule` is registered in `app_factory.py` **before** `SkillsModule` specifically so this hint lands immediately ahead of the `<available_skills>` block in the aggregated system prompt |
| `_chat_completion_config_builder.py` | Reads `LazyLoadedToolsHolder.get_all()` on every build and merges into `payload["tools"]`, de-duplicated against eager tool names — **`orchestrator.py` itself was not changed** |
| Cross-turn state persistence | **Not implemented** — see [Out of Scope](#out-of-scope-mvp) |

**Round-trip cost:** +1 turn before first native tool use (search + inject → tool call).
The anonymous agent call happens inside the `tool_search` tool execution, not as a separate
orchestrator iteration. Subsequent calls to the same tool within a turn are free (already in
`_lazy_loaded_tools`). With cross-turn state, rediscovery is skipped on later turns.

**Token cost of `tool_search` (anonymous agent call):**
`catalog_tokens + query_tokens` — independent of conversation length. For 200 deferred tools
with ~20-token descriptions each, this is ~4 K tokens regardless of how long the conversation is.

**Pros:**
- Fully model-agnostic: works with any DIAL deployment as orchestrator.
- `DeferredToolsContext` cleanly separates eager and deferred tool state at the DI layer —
  no orchestrator logic needed to decide what to defer.
- Anonymous agent isolates search cost from main conversation tokens; scales with catalog size,
  not conversation length.
- Native schema injection means the main LLM calls discovered tools with proper structured
  arguments from the iteration after discovery.
- Opt-out: `deferred: true` by default; threshold guard prevents regression for small toolsets.
  Set `deferred: false` on a toolset to keep it always-eager.
- `AnonymousAgent` is a reusable module independent of tool discovery.
- Search strategy is swappable (keyword, embedding, different model) without touching the
  orchestrator or injection logic.

**Cons:**
- +1 orchestrator iteration before first native use of a deferred tool.
- `AnonymousAgent` introduces a new code path for isolated completions.
- Discovered tools only live for the current turn (`LazyLoadedToolsHolder` is request-scoped);
  cross-turn persistence would require state serialisation (not implemented, see Out of Scope).
- Search quality depends on service model and catalog description quality.

---

## Comparison

| | Option 1 | Option 2 | Option 3 | Option 4 | Option 5 | **Option 6** |
|---|---|---|---|---|---|---|
| Model-agnostic | Yes | Yes | Yes | No (Anthropic 4.5+) | Yes | **Yes** |
| Orchestrator changes | None | None | Significant | Medium | Medium | **None** (as built) |
| Native schema on discovered tool call | No | No | Yes | Yes | Depends | **Yes** |
| Full name-space visible upfront | No | Yes | No | No | No | **No** |
| Prompt cache preserved | — | — | — | Yes (by design) | — | **Partial** ¹ |
| Per-tool granularity | Toolset | Toolset | Toolset | Per-tool | Per-tool | **Toolset** |
| Search uses separate LLM call | No | No | No | No (server-side) | No | **Yes** |
| Implementation complexity | Low | Low | High | Medium | Medium–High | **Medium** |
| Follows existing lazy pattern | Yes | Partial | No | No | No | **Partial** |
| Custom search logic possible | Yes | Yes | Yes | Yes | Yes | **Yes** |

¹ Deferred tools are absent from `payload["tools"]` in main calls, so the stable prefix
(eager tools + `tool_search`) is cacheable. Lazy-loaded tools appended after discovery break
the cache for that iteration only.

---

## Recommendation

**Option 6** is the recommended approach. It is the only option that is simultaneously
model-agnostic, delivers native schema-based tool calling after discovery, and isolates the
search token cost from the conversation context.

Options 1–3 are useful reference points for the individual sub-problems Option 6 combines.
Option 4 is the right choice if the team decides to target Anthropic deployments exclusively
and wants to offload search infrastructure entirely. Option 5 (full MCP three-layer + dynamic
server management) remains the long-term architecture for MCP toolsets and can be layered on
top of Option 6 incrementally.

---

## Open Questions

1. **Granularity:** `deferred` on `BaseToolSet` (per-toolset) or also settable per-tool within
   a toolset? Per-toolset covers MCP servers and REST API groups cleanly; per-tool is needed
   only for mixed toolsets where some tools are always-on. **Still open** — per-toolset is what
   shipped; per-tool granularity remains a possible future extension.

2. ~~**`service_model` default**~~ — **Resolved, as built:** falls back to the orchestrator's
   own deployment when omitted (`_AnonymousAgent.route`).

3. ~~**Search implementation in MVP**~~ — **Resolved, as built:** pure LLM routing via
   `_AnonymousAgent`, no keyword-only fallback. Not currently planned.

4. ~~**Multi-turn persistence**~~ — **Resolved, as built: not implemented.** Discovered tools
   are always rediscovered each turn; see [Out of Scope](#out-of-scope-mvp).

5. **Always-on threshold:** Should there be a heuristic that automatically promotes a
   frequently-discovered tool to eager loading (e.g. seen in last N turns), or is that always
   explicit config? **Still open** — not implemented; today it's always explicit config
   (`deferred: false` per toolset).

---

## Out of Scope (MVP)

| Item | Reason |
|---|---|
| Embedding-based search in `_AnonymousAgent` | Swap-in strategy; `_AnonymousAgent` interface is the extension point |
| Dynamic MCP server connection/disconnection | Significant lifecycle change; Option 5 follow-on |
| Per-tool granularity within a toolset | Per-toolset is sufficient for the initial use case |
| Automatic threshold based on token count | Tool-count threshold is simpler and good enough for MVP |
| Cross-turn discovery persistence (`custom_content.state["lazy_loaded_tools"]`) | Not implemented — `LazyLoadedToolsHolder` is request-scoped only; discovered tools are rediscovered every turn |
| `dial-deployment` / `dial-app` toolset deferral | REST, MCP, and internal toolsets support `deferred`; deployment/app toolsets do not yet call `is_toolset_deferred` — tracked as a follow-up |

---

## References

- [MCP Client Best Practices — Progressive Tool Discovery](https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices)
- [Anthropic Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Anthropic — Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Anthropic — Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
