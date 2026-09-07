# Design: Dynamic Tool Discovery

- **Status:** Draft
- **Issue:** [#430](https://github.com/epam/ai-dial-quickapps-backend/issues/430)

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

**Config:** opt-in flag at `ApplicationConfig` (global) or per-toolset.

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

### Option 6 — Subagent-routed catalog search + orchestrator injection (Recommended)

**Mechanism:**
Combines a lightweight separate-LLM search step (for token-efficient routing) with orchestrator-level
tool injection (for native schema-based calling). It is model-agnostic and requires no
Anthropic-specific API features.

#### Startup: catalog build

Each toolset that opts in builds a compact **catalog entry** — `{name, description}` only — and
stores it in a per-toolset `ToolCatalog`. Full `OpenAiToolConfig` definitions are fetched and
held in memory as today but are **not forwarded to `payload["tools"]`**.

```python
# Stored at init time, never sent to the main LLM upfront
catalog: list[ToolCatalogEntry]  # [{name, description}, ...]
definitions: dict[str, OpenAiToolConfigDict]  # name → full schema
```

#### Main orchestrator call

`payload["tools"]` contains only two meta-tools plus any always-on (non-deferred) tools:

```
tool_search(query: str) → list[{name, description}]
tool_discovery(tool_name: str) → full OpenAiToolConfig JSON
```

Deferred tool definitions are **absent from the tools array**. The main LLM sees a minimal
surface.

#### tool_search execution: separate chat completion

When the main LLM calls `tool_search`, the tool handler fires a **separate, isolated chat
completion** — a fresh context with no conversation history and no system prompt:

```
model:    configurable (defaults to the orchestrator deployment; a cheap/fast
          model such as a Haiku-class DIAL deployment is recommended)
messages: [{"role": "user", "content": <query from main LLM>}]
system:   minimal routing instruction +
          compact catalog injected as context (all names + descriptions)
tools:    none
```

The routing LLM returns the best-matching tool names and descriptions. Because this call carries
no conversation history or system prompt, its token cost is proportional only to the catalog
size — not to conversation length.

**Result returned to main LLM:** `[{name, description}, ...]`

#### tool_discovery execution: local lookup, no LLM

When the main LLM calls `tool_discovery(tool_name)`, the handler does a plain dictionary lookup
against the in-memory `definitions` map and returns the full `OpenAiToolConfig` JSON. No LLM
call is made.

**Result returned to main LLM:** full tool schema as JSON text in the tool result.

#### Orchestrator injection (Path A)

The orchestrator intercepts any `tool_discovery` result and:
1. Parses the returned tool name(s) from the result.
2. Adds the corresponding `OpenAiToolConfigDict` to a per-iteration `_pending_tools: dict[str, OpenAiToolConfigDict]`.
3. On the **next** call to `_ChatCompletionConfigBuilder.build()`, the pending definitions are
   merged into `payload["tools"]`.
4. The main LLM now sees the discovered tool natively and calls it with proper schema-based
   argument generation.

Discovered tools accumulate across iterations within a turn. Optionally they are serialised
into `custom_content.state` so they persist across conversation turns (avoiding rediscovery on
the next user message).

#### Flow diagram

```
Turn start
  │
  ▼
Main LLM call
  tools = [tool_search, tool_discovery, ...always-on]
  messages = full conversation history
  │
  ├─ LLM calls tool_search("find Salesforce tools")
  │     │
  │     └─ Separate chat completion (fresh context):
  │           model   = fast routing model
  │           context = compact catalog (names + descriptions only)
  │           input   = "find Salesforce tools"
  │           → [{name: "sf_query", description: "..."}, ...]
  │     Result returned to main LLM
  │
  ├─ LLM calls tool_discovery("sf_query")
  │     │
  │     └─ Local dict lookup → full OpenAiToolConfig JSON
  │     Orchestrator registers "sf_query" in _pending_tools
  │     Result returned to main LLM
  │
  ▼
Next main LLM call
  tools = [tool_search, tool_discovery, ...always-on, sf_query ← injected]
  │
  └─ LLM calls sf_query(object="Account", ...) natively ✓
```

#### Deferral threshold

Even when `deferred: true` is set, a toolset is loaded eagerly if it is small enough that
deferring it would cost more (extra round-trips) than it saves (token reduction). Two guards
are evaluated at startup; a toolset is deferred only when it clears **both**:

| Guard | Config key | Default | Check |
|---|---|---|---|
| Tool count | `min_tools_for_deferral` | `5` | `len(catalog) >= threshold` |
| Token estimate | `min_tokens_for_deferral` | `1000` | `estimated_tokens >= threshold` |

Token estimate is computed as `sum(len(json.dumps(schema)) for schema in definitions.values())`
— a cheap character-count proxy evaluated once at startup. It is intentionally approximate;
exact tokenisation is not worth the overhead here.

```
deferred_effective = (
    config.deferred
    and len(catalog) >= discovery.min_tools_for_deferral
    and estimated_tokens >= discovery.min_tokens_for_deferral
)
```

A toolset with `deferred: false` is always loaded eagerly regardless of size. A toolset with
`deferred: true` that falls below either threshold is silently promoted to eager and its tools
are included in `payload["tools"]` as normal — no discovery overhead, no behavioural change
visible to the model.

#### Configuration

```json
{
  "orchestrator": {
    "tool_discovery": {
      "enabled": true,
      "routing_deployment": "claude-haiku-dial-deployment",
      "min_tools_for_deferral": 5,
      "min_tokens_for_deferral": 1000
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

- `deferred: true` on a toolset opts it into the catalog. Default: `false` (existing behaviour preserved).
- `routing_deployment` names the DIAL deployment used for the `tool_search` separate completion.
  When omitted, it falls back to the orchestrator's own deployment.
- `min_tools_for_deferral` and `min_tokens_for_deferral` are global guards; toolsets that do
  not clear both are silently promoted to eager loading. Both default to values that make
  deferral a no-op for small toolsets.
- Non-deferred toolsets continue to populate `payload["tools"]` immediately, as today.

#### Changes required

| Area | Change |
|---|---|
| `BaseToolSet` | Add `deferred: bool = False` field |
| `OrchestratorConfig` | Add `tool_discovery: ToolDiscoveryConfig` sub-config (`enabled`, `routing_deployment`, `min_tools_for_deferral`, `min_tokens_for_deferral`) |
| Toolset initialisation modules | After building the catalog, apply deferral thresholds; promote under-threshold toolsets to eager; for remaining deferred toolsets build `ToolCatalog` + `definitions` map and skip `provide_openai_tools` contribution |
| `AgentModule` | Inject `ToolCatalogRegistry` (merged catalog across all effectively-deferred toolsets); expose `tool_search` and `tool_discovery` as `StagedBaseTool` implementations via `@multiprovider` |
| `tool_search` tool | Fires isolated `AssistantInvoker`-like completion; no messages/system prompt, only catalog context |
| `tool_discovery` tool | Dict lookup on `ToolCatalogRegistry.definitions`; no LLM call |
| `orchestrator.py` | After each iteration, check tool results for `tool_discovery` outputs; merge returned schemas into `_pending_tools`; pass to `_ChatCompletionConfigBuilder` on next call |
| `_ChatCompletionConfigBuilder` | Accept `extra_tool_dicts` parameter; merge into `payload["tools"]` |
| State serialisation (optional) | Persist `_pending_tools` names in `custom_content.state["discovered_tools"]` for cross-turn reuse |

**Round-trip cost:** +2 turns before first native tool use (search → discovery → tool call).
Subsequent calls to the same tool within a turn are free (already in `_pending_tools`). With
cross-turn state, rediscovery is skipped on later turns.

**Token cost of `tool_search` call:**
`catalog_tokens(N tools) + query_tokens` — independent of conversation length. For 200 tools
with 20-token descriptions each, this is ~4 K tokens regardless of how long the conversation is.

**Pros:**
- Fully model-agnostic: works with any DIAL deployment as the orchestrator.
- Separate LLM routing call avoids spending main-context tokens on search; scales with catalog
  size, not conversation size.
- Native schema injection (Path A) means the main LLM always calls discovered tools with proper
  structured arguments — no prompt workarounds.
- Non-breaking opt-in: `deferred: false` by default preserves all existing behaviour.
- Routing model is configurable — can use a cheap/fast deployment to minimise cost.
- Extensible: the `tool_search` implementation can be swapped to embedding-based or keyword-only
  without changing the orchestrator or injection logic.

**Cons:**
- +2 round-trips before first native use of a deferred tool.
- The separate chat completion introduces a new code path for firing isolated completions.
- Orchestrator needs `_pending_tools` state; cross-turn persistence requires state serialisation.
- `tool_search` quality depends on the routing model and catalog description quality.

---

## Comparison

| | Option 1 | Option 2 | Option 3 | Option 4 | Option 5 | **Option 6** |
|---|---|---|---|---|---|---|
| Model-agnostic | Yes | Yes | Yes | No (Anthropic 4.5+) | Yes | **Yes** |
| Orchestrator changes | None | None | Significant | Medium | Medium | **Medium** |
| Native schema on discovered tool call | No | No | Yes | Yes | Depends | **Yes** |
| Full name-space visible upfront | No | Yes | No | No | No | **No** |
| Prompt cache preserved | — | — | — | Yes (by design) | — | **Partial** ¹ |
| Per-tool granularity | Toolset | Toolset | Toolset | Per-tool | Per-tool | **Toolset** |
| Search uses separate LLM call | No | No | No | No (server-side) | No | **Yes** |
| Implementation complexity | Low | Low | High | Medium | Medium–High | **Medium** |
| Follows existing lazy pattern | Yes | Partial | No | No | No | **Partial** |
| Custom search logic possible | Yes | Yes | Yes | Yes | Yes | **Yes** |

¹ Deferred tools are absent from `payload["tools"]` in main calls, so the stable tools prefix
(always-on tools + meta-tools) is cacheable. Discovered tools appended per-iteration break the
cache for that iteration only.

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
   only for mixed toolsets where some tools are always-on.

2. **Routing model:** Should `routing_deployment` default to the orchestrator deployment, or
   should there be a system-wide fallback configured at the application level?

3. **Search implementation in MVP:** Plain keyword/substring match on catalog names and
   descriptions, or a real LLM routing call from the start? Keyword match is deterministic and
   has no latency; LLM routing handles synonyms and fuzzy intent but adds a network call.

4. **Multi-turn persistence:** Serialise `_pending_tools` into `custom_content.state` so
   rediscovery is skipped on subsequent turns, or always rediscover? Persistence saves
   round-trips but grows state size.

5. **Always-on tools threshold:** Should any heuristic automatically promote a recently
   discovered tool to always-on (e.g. if it has been discovered in the last N turns), or is
   that always explicit config?

---

## Out of Scope (MVP)

| Item | Reason |
|---|---|
| Embedding-based or subagent-based search | Swap-in strategy on top of Option 6 search step |
| Dynamic MCP server connection/disconnection | Significant lifecycle change; Option 5 follow-on |
| Per-tool granularity within a toolset | Per-toolset is sufficient for the initial use case |
| Automatic context-window threshold triggering | Always-opt-in is simpler and more predictable |

---

## References

- [MCP Client Best Practices — Progressive Tool Discovery](https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices)
- [Anthropic Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Anthropic — Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Anthropic — Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
