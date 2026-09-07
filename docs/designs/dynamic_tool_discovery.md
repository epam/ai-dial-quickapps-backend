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
- Model-agnostic: must work for any LLM accessible via DIAL without provider-specific extensions.
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

The only existing "on-demand" pattern in the codebase is `LazyOnDemandStrategyModule`, which
injects the `internal_attachments_get_content` tool per-request via the same DI `@multiprovider`
extension point. Dynamic tool discovery should follow the same pattern.

---

## Decision Points

Three orthogonal decisions drive the design space:

| # | Decision | Choices |
|---|---|---|
| A | **Deferral granularity** | Per-toolset vs per-tool |
| B | **Discovery surface** | Keyword search · Compact manifest · Semantic search |
| C | **How full definitions reach the LLM** | As tool-call result text · Injected into `payload["tools"]` |

---

## Options

### Option 1 — Per-toolset deferred flag + keyword-search discovery tool

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
- Non-breaking opt-in.
- Token savings are immediate (entire toolset suppressed).
- Simple to implement and test.

**Cons:**
- Model must understand and follow the discovery protocol → system-prompt engineering required.
- Two round-trips before a tool can be used for the first time.
- Full definition returned as text; the model cannot use the schema for structured argument
  generation on the same call.

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
- One fewer round-trip than Option 1 when the model knows which tool it wants.

**Cons:**
- Manifest can still be substantial for 100+ tools.
- Requires careful framing: empty-parameter tool entries may confuse some models.
- Full definition is still returned as text (same as Option 1); native schema generation
  not available on the definition-fetch call.

---

### Option 3 — Orchestrator-level dynamic tool injection

**Mechanism:**
A discovery tool (keyword or semantic) returns tool names. The orchestrator intercepts the
discovery tool result and **injects the corresponding full schemas into `payload["tools"]`
on the next LLM call** — not into the message history. The model then uses the tool natively
with proper schema-based argument generation.

**Changes required:**
- Orchestrator maintains `_discovered_tool_names: set[str]` state across iterations.
- `_ChatCompletionConfigBuilder` accepts a per-request "additional tools" override.
- Discovery tool result is processed as a side-effect by the orchestrator before the next
  iteration, not treated as a regular TOOL message.
- Discovered names must optionally be persisted in conversation state for multi-turn continuity.

**Round-trip cost:** +1 (discover call → definitions in tools array → native call).

**Pros:**
- LLM interacts with discovered tools natively (proper argument schema, no prompt workarounds).
- Cleanest UX: from the model's perspective, discovered tools behave identically to pre-loaded ones.

**Cons:**
- Significant orchestrator changes.
- Discovered-tool state must survive across iterations and potentially across conversation turns
  (state serialisation).
- More complex error paths (discovery result processed as side-effect, not normal tool result).

---

### Option 4 — Semantic search (enhancement layer)

Replaces keyword matching in Options 1–3 with vector-similarity search on tool descriptions,
using a DIAL embedding deployment.

**Pros:** better recall for natural-language queries; fewer false positives in large catalogs.  
**Cons:** extra DIAL deployment dependency; per-discovery-call latency; adds significant
complexity for marginal MVP gain.

Treat as a **post-MVP strategy swap** on top of Options 1 or 3.

---

## Comparison

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Orchestrator changes | None | None | Significant |
| Round-trips before first use | +1 | +1 | +1 |
| Native schema on discovery turn | No | No | Yes |
| Full name-space always visible | No | Yes | No (configurable) |
| Implementation complexity | Low | Low–Medium | High |
| Follows existing lazy pattern | Yes | Partial | No |

---

## Recommendation

**MVP: Option 1** (per-toolset `deferred` flag + keyword-search discovery tool).

Rationale:
- Directly mirrors `LazyOnDemandStrategyModule` — the implementation pattern is already proven.
- No orchestrator changes keeps the blast radius small.
- Delivers meaningful token savings (entire toolset suppressed) with an opt-in default.
- Leaves room to upgrade to Option 3 once discovery behaviour is validated in production.

**Follow-on: Option 3** once the MVP is validated. It removes the prompt-engineering dependency
and makes discovered tools first-class.

**Option 4** (semantic) can be offered as an alternative search strategy within either Option 1
or 3 as a configuration toggle.

---

## Open Questions

1. **Granularity:** Should `deferred` live on `BaseToolSet` (per-toolset) or also be settable
   per-tool inside a toolset? Per-toolset is simpler and covers the main use case (defer an
   entire MCP server); per-tool is more surgical for mixed sets.

2. **Discovery tool naming:** One tool per deferred toolset (`{toolset}_discover`) or a single
   global `discover_tools(toolset?: str, query: str)`? A single tool reduces clutter in the
   `tools` array but couples discovery to a specific naming convention.

3. **Search quality:** Is substring keyword match on name + description sufficient for MVP, or
   should we index descriptions (e.g. TF-IDF) for better recall? Keyword match is simple and
   deterministic; TF-IDF adds a build-time index step.

4. **System-prompt alignment:** Should deferred toolset descriptions be injected into the
   system prompt (to help the model decide when to search) or omitted entirely? Including a
   brief catalog summary reduces false-negative discovery calls.

5. **Conversation-turn persistence (Option 3):** Should discovered tool names persist across
   turns (stored in conversation state) so the model does not need to rediscover on every turn?
   This trades discovery latency for state-size growth.

---

## Out of Scope (MVP)

| Item | Reason |
|---|---|
| Semantic / embedding-based search | Post-MVP strategy swap |
| Per-tool granularity within a toolset | Per-toolset is sufficient for initial use case |
| Dynamic schema injection into `payload["tools"]` | Option 3 — follow-on |
| Result caching across turns | State management complexity; defer |
| Provider-specific tool-pagination APIs | Not available via DIAL today |
