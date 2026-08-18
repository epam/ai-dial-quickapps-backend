# Design: MCP Capabilities Extension — Phase 1: Resources

- **Status:** Implemented
- **Scope:** Resources + Capability Negotiation. Prompts and Tool Annotations are deferred to future iterations (see Out of Scope).
- **Dependencies:**
  - None

> **Protocol update pending — MCP RC 2026-07-28**
> The MCP 2026-07-28 release candidate introduces breaking changes that affect
> every section of this document:
> - The `initialize`/`initialized` handshake is **eliminated**. Capabilities
>   and client info will travel in `_meta` on every request. The single-session
>   design described in §3.6 and §3.7 will need to be revisited.
> - A new `server/discover` method replaces capability negotiation (§3.7).
> - Roots, Sampling, and Logging are deprecated.
> - Resources gain `ttlMs` / `cacheScope` caching hints.
> - Tool schemas adopt full JSON Schema 2020-12.
>
> All design decisions here target **MCP 2025-11-25**. Once the RC stabilises,
> a follow-up design will cover the transport and session lifecycle refactor.
> Reference: https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/

---

## Business Use Cases for MCP Resources

MCP distinguishes between two primitives: **tools** (operations with side effects) and
**resources** (read-only data the server wants the LLM to be aware of). The scenarios
below are drawn from real deployments where this distinction addresses concrete business
problems that tools alone cannot solve.

### Grounding SQL agents in live database schema

A SQL agent without schema access guesses column names and produces broken queries.
Each failed query costs an LLM turn, user trust, and in some deployments a real
database round-trip. Exposing the actual table definitions as a resource (`schema://tables`)
lets the agent read the live schema before generating any SQL. The agent produces
correct queries on the first attempt, and the schema tokens are consumed only when
actually needed — a simple aggregation query never fetches the schema at all.

### Eliminating configuration drift in deployed agents

Agents hard-coded with environment assumptions (region, tier, feature flags, rate limits)
silently give wrong answers after any deployment change. Exposing live runtime
configuration as a resource (`config://environment`) and marking it `eager` means every
request begins with the agent knowing the actual deployment state. No manifest update is
required when configuration changes — the agent reads truth from the server on every
request.

### Safe observe-then-act workflows for infrastructure agents

An agent that manages infrastructure (scaling deployments, restarting pods, triggering
rollbacks) is only safe when observation is structurally separated from action. Resources
provide this separation at the protocol level: reading deployment health (`state://deployment/{name}`)
and pod logs (`logs://pod/{name}`) carries no side effects, while scaling and restarts
are tools. The agent is architecturally prevented from taking a destructive action without
first reading evidence — the read/write boundary is enforced by the protocol, not by
prompt instructions.

### Replacing startup hooks with eager resources in MCP services

Integrating DIAL Memory into a QuickApp currently requires two `on_request_start` hooks:
one (`prime_memories`) that fetches relevant memories for the conversation, and one
(`get_skill`) that injects static instructions explaining how the LLM should use the
memory tools. The `get_skill` hook returns a fixed read-only document — exactly what
an MCP resource is designed to provide.

With resource support, the memory MCP server can expose those skill instructions as a
resource (e.g., `memory://skill`). Marking it `eager: true` in the toolset config causes
QuickApps to pre-fetch it at init time and inject it as a synthetic tool call pair, with
the same effect as the hook but without requiring a separate hook configuration. The
integration drops from two hooks to one: only `prime_memories` remains as a hook,
while the static skill instructions move into the toolset config.

The pattern generalises to any MCP service that currently relies on a startup hook to
inject static guidance or metadata. If the content is read-only and server-owned, it
belongs in a resource — not in a hook that the QuickApp author must wire manually.

### Context-efficient RAG over internal documentation

Embedding all internal API documentation in the system prompt bloats every request with
content irrelevant to most queries and exhausts context for the actual task. Exposing
documentation as resources (`docs://api/{service}`) enables a RAG pattern where the agent
retrieves only what it needs, when it needs it. A query about one service reads one
document; a multi-service task reads several; simple questions read none. Context usage
scales with query complexity rather than knowledge base size.

---

## Problem Statement

QuickApps uses MCP servers exclusively for tool invocation (`tools/list` + `tools/call`).
The remaining capabilities defined by the MCP 2025-11-25 specification — Resources,
Prompts, and tool annotations — are silently ignored.

As a result:

- MCP servers that expose contextual data (database schemas, documentation, configuration)
  via Resources provide no value beyond their tools. The LLM operates without context
  the server explicitly makes available.
- MCP servers that encode reusable instruction sets via Prompts cannot contribute to the
  agent's skill repertoire. Users have no way to activate these prompts through QuickApps.
- Tool annotations (`title`, `readOnlyHint`, `destructiveHint`) are discarded at
  initialization time. The LLM receives no hints about tool safety or intent, which
  degrades its decision-making when choosing between destructive and read-only operations.
- `structuredContent` in tool call results is only referenced in error-path logging
  (`_MCPTool._run_in_stage_async`). When a server returns structured output alongside
  empty text blocks, the response surfaces as blank content.
- The `InitializeResult` returned by `session.initialize()` is discarded entirely.
  Server-advertised capabilities (`resources`, `prompts`, `tools`) are never consulted,
  so QuickApps cannot adapt its behaviour to the server's actual feature set and may
  attempt to invoke capabilities the server does not support.

## Design Goals

- MCP servers that declare the `resources` capability surface their resource list as
  attribution cards in the system context — the LLM sees what data is available and how
  to request it, without bearing the token cost of all content upfront.
- The LLM fetches resource content on demand by calling `read_mcp_resource`, mirroring
  how predefined skills are read via `read_skill`.
- Users can opt specific resources into eager loading: their content is pre-fetched at
  init time and injected as synthetic tool call pairs — the natural in-context
  representation for tool-based operations, and the preferred over direct system prompt injection.
- Users can restrict which resources are listed by URI.
- Existing `MCPToolSet` and `DialMCPToolSet` manifests without the new fields behave
  identically to today. No migration is required.
- Server-advertised capabilities from `InitializeResult` are captured and stored per
  toolset. Each capability is only invoked when the server explicitly declares support for it.

---

## Use Cases

### UC-1: LLM reads a resource on demand

**Trigger:** A toolset config has `resources.enabled: true`. The MCP server exposes
`schema://tables` (name: "Database Schema", description: "Table definitions for the
orders database"). No resources are marked `eager`.

**Behavior:** During request initialization, QuickApps calls `resources/list`. Resource
metadata is injected into the system context as a frontmatter card:

```
--- Resource: Database Schema (database-assistant) ---
URI: schema://tables
Table definitions for the orders database.
```

When the LLM decides it needs the schema, it calls `read_mcp_resource(uri="schema://tables")`.
QuickApps opens a session to the server and calls `resources/read`. The content is returned
as the tool result.

**Outcome:** The LLM received the resource exactly when it needed it, without the schema
content occupying system-prompt tokens on queries that don't need it.

---

### UC-2: Eagerly loaded resource injected as synthetic tool call

**Trigger:** A toolset config specifies `resources.items: [{uri: "config://app-settings", eager: true}]`.

**Behavior:** During initialization, QuickApps fetches the resource content within the
same init session that loads tools. Before the LLM's first invocation, a synthetic tool
call pair is prepended to the message history:

```
[assistant] → read_mcp_resource(uri="config://app-settings")
[tool result] → {content of config://app-settings}
```

**Outcome:** The LLM sees the resource content as if it had already called the tool.
Configuration that is always needed is available from the start of the conversation
without bloating the system prompt.

---

### UC-3: Filtering resources by URI

**Trigger:** A server exposes 20 resources. The user specifies
`resources.items: [{uri: "schema://tables"}, {uri: "schema://indexes"}]`.

**Behavior:** QuickApps fetches the full resource list from the server and injects
frontmatter cards for only the two listed URIs. All others are ignored.

**Outcome:** The system context exposes only the two relevant resources.

---

### UC-4: Existing config unchanged

**Trigger:** An existing `MCPToolSet` manifest with no `resources` field.

**Behavior:** `resources` defaults to `None`. Initialization runs exactly as
today — only `tools/list` is called.

**Outcome:** Zero behavioral change for existing deployments.

---

### UC-5: Capability negotiation guards resource loading

**Trigger:** A toolset config has `resources.enabled: true`. The MCP server returns an
`InitializeResult` with `capabilities.resources = null`.

**Behavior:** QuickApps captures `InitializeResult`, sees that `capabilities.resources`
is absent, skips `resources/list`, and logs a warning: `"Toolset 'X' has resources.enabled=true
but server does not advertise resources capability — skipping"`.

**Outcome:** No error. Tools are loaded as normal.

---

## Proposed Design

### 3.1 Config extension

Two new frozen Pydantic models in `config/toolsets/mcp.py`:

```python
class MCPResourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    uri: str
    eager: bool = Field(
        default=False,
        description=(
            "Pre-fetch this resource at init time and inject its content as a "
            "synthetic read_mcp_resource tool call pair before the first LLM invocation."
        ),
    )

class MCPResourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = Field(default=False)
    items: list[MCPResourceConfig] | None = Field(
        default=None,
        description=(
            "Resources to expose. None = expose all resources the server declares, all lazy. "
            "Provide a list to restrict to specific URIs and/or mark some as eager."
        ),
    )
```

`MCPToolSet` and `DialMCPToolSet` each gain:

```python
resources: MCPResourcesConfig | None = Field(default=None)
```

---

### 3.2 Resource metadata model

A new frozen model `MCPResourceMeta` (in `mcp_tooling/_mcp_resource_meta.py`) carries
server-side metadata for a listed resource. No content is stored here.

| Field | Source |
|---|---|
| `toolset_name` | `MCPToolSet.name` |
| `toolset_description` | `MCPToolSet.description` |
| `resource_name` | `Resource.name` |
| `resource_uri` | `Resource.uri` |
| `resource_description` | `Resource.description` (optional) |
| `mime_type` | `Resource.mimeType` (optional) |

Eager content is modeled as a discriminated union in `mcp_tooling/_mcp_eager_resource.py`
to leave room for blob support in Phase 2:

```python
class MCPEagerTextResource(MCPResourceMeta):
    content_type: Literal["text"] = "text"
    text: str

# Phase 2 will add:
# class MCPEagerBlobResource(MCPResourceMeta):
#     content_type: Literal["blob"] = "blob"
#     dial_url: str  # uploaded to DIAL via AttachmentService

MCPEagerResource = MCPEagerTextResource  # | MCPEagerBlobResource in Phase 2
```

`_MCPToolingContext` gains:

```python
resource_metas: list[MCPResourceMeta] = []    # all listed resources (text + blob)
eager_resources: list[MCPEagerResource] = []   # eager text resources only in Phase 1
server_capabilities: list[MCPServerCapabilities] = []
```

With matching thread-safe helpers following the existing `extend_tools` / `append_exception` pattern.

---

### 3.3 System context injection (frontmatter cards)

A new component `_MCPResourceCardProvider` (in `mcp_tooling/_mcp_resource_card_provider.py`)
implements `PromptPartProvider`. It reads `_MCPToolingContext.resource_metas` and renders
one attribution card per resource:

```
--- Resource: {resource_name} ({toolset_name}) ---
URI: {resource_uri}
MIME type: {mime_type}           (omitted when not provided by the server)
{resource_description or toolset_description}
```

When both `resource_description` and `toolset_description` are present, `resource_description`
takes precedence (more specific to the individual resource). When neither is present, the
description line is omitted. `mime_type` is rendered only when the server provides it — for
blob resources it lets the LLM infer that content is binary before attempting to read it.

The instruction on how to load resource content lives exclusively in the `read_mcp_resource`
tool description — not repeated per card, consistent with how `<available_skills>` lists
skill metadata without embedding "call `read_skill`" in every entry.

Both text and blob resources are included in the card list — the LLM sees they exist
regardless of content type. The `mime_type` field in the card allows the LLM to infer the
content type. Whether content can be fetched is a runtime concern handled by the tool.

Registered in `MCPToolingModule.configure` via `@multiprovider` as `list[PromptPartProvider]`,
consistent with how `SkillsRegistry` contributes to the system prompt. Returns `""` when
`resource_metas` is empty.

---

### 3.4 `read_mcp_resource` internal tool

A new internal tool `_ReadMcpResourceTool` (in `mcp_tooling/_read_mcp_resource_tool.py`),
registered in `MCPToolingModule`. The module provides it conditionally: a provider inspects
`ApplicationConfig` and includes the tool in the tool registry only when at least one
toolset has `resources: {enabled: true}`. This mirrors the pattern used by other
conditional tools in `MCPToolingModule` and avoids exposing the tool in requests where no
resources are configured.

**Tool schema:**

```python
{
  "name": "read_mcp_resource",
  "description": "Read the content of an MCP resource by its URI.",
  "input_schema": {
    "type": "object",
    "properties": {
      "uri": {
        "type": "string",
        "description": "URI of the resource to read."
      },
      "toolset": {
        "type": "string",
        "description": (
            "Name of the toolset that owns the resource. "
            "Required when multiple toolsets expose the same URI; "
            "visible in the resource card header as '--- Resource: ... ({toolset}) ---'."
        )
      }
    },
    "required": ["uri"]
  }
}
```

**Semantics:**

1. Filter `_MCPToolingContext.resource_metas` by `uri`. If `toolset` is provided, also
   filter by `toolset_name`.
2. If no match: return `"No resource registered with URI '{uri}'"`.
3. If multiple matches (same URI across toolsets) and `toolset` was not provided: return
   `"Multiple toolsets expose URI '{uri}': {names}. Specify the 'toolset' parameter."`.
4. Obtain a per-request session via `_MCPSessionManager` for the owning toolset. The MCP
   protocol places no restriction on which request types share a session — `resources/read`
   is issued on the same `ClientSession` already used for `tools/call` for that toolset.
   No separate session key or pool is needed.
5. Call `resources/read(uri)` and return `TextResourceContents.text`.

Blob resources (`BlobResourceContents`) are skipped in Phase 1. If the server returns only
blob content, the tool returns: `"Resource '{uri}' contains binary content (blob). Binary
resources are not supported in this version."` A follow-up design covers blob upload via
`AttachmentService`.

The tool appears as a single shared entry in the tool list alongside MCP tools. The `toolset`
parameter is the LLM's disambiguation handle — its value is always visible in the resource
card header, so the LLM can supply it whenever needed.

---

### 3.5 Eager loading via synthetic tool call injection

**Owner:** `mcp_tooling/_mcp_eager_resource_transformer.py`

A new `MessagesTransformer`, `_MCPEagerResourceTransformer`, prepends synthetic tool call
pairs for eager resources that are not yet present in the message history.

**Per-turn deduplication:**

Before inserting, the transformer scans the full message history and collects all
`(uri, toolset_name)` pairs that already appear as assistant tool-call messages where the
tool name is `read_mcp_resource` — extracting `uri` and `toolset` from the call arguments.
This covers both synthetic pairs from previous turns and real LLM-initiated calls. A pair
already in this set is skipped; only new `(uri, toolset_name)` combinations get a synthetic
pair injected.

This covers the multi-turn case naturally:

- **Turn 1** — history has no `read_mcp_resource` calls; eager resources = [A, B] →
  pairs for A and B are prepended.
- **Turn 2, same resources** — history already contains A and B → transformer is a no-op.
- **Turn 2, new resource C added** — history has A and B; server now returns [A, B, C] →
  only a pair for C is prepended.
- **Resource removed from server** — its pair remains in history from a prior turn;
  stale content is acceptable since the conversation already proceeded with it.

Each pair:

1. An **assistant message** containing a tool call to `read_mcp_resource` with
   `{"uri": "<resource_uri>", "toolset": "<toolset_name>"}` as the input.
2. A **tool result message** with the pre-fetched `text` as the tool result content.

New pairs are inserted **after the first user message** (consistent with the
`_after_first_user_idx` convention used elsewhere in the codebase — LLM APIs require
conversations to start with a user turn), in declaration order (the order items appear
in `toolset.resources.items` across all toolsets, in toolset registration order). When
`toolset.resources.items` is `None` (all resources exposed, all lazy) there are no eager
items and the transformer is always a no-op for that toolset. When all eager URIs are
already covered by history, the transformer is also a no-op.

**Rationale for synthetic injection over direct prompt injection:**
The content arrives in the position the LLM expects for tool results, rather than embedded
in the system prompt. The LLM understands that it "already called" the tool, which is more
semantically accurate than presenting resource content as authorless system context. This
also avoids system-prompt bloat for resources whose content can be large.

**Eager content loading at init time:**

Within `_MCPToolInitializer._process_toolset`, after the resource metadata pass, for each
item with `eager: True`:

1. Call `read_resource(session, uri)` on the already-open init session (no extra sessions).
2. If the result is `TextResourceContents`: construct `MCPEagerTextResource` and append to
   `_MCPToolingContext.eager_resources`.
3. If the result is `BlobResourceContents`: skip with `log.warning` — blob eager loading
   is deferred to Phase 2.

Failures on individual eager reads are caught independently and recorded as
`ToolInitializationException` entries, consistent with tool-loading failures.

---

### 3.6 Resource listing at init

`_MCPToolsetClient` gains two new session-accepting helpers:

- `get_resources_list(session: ClientSession) -> list[Resource]` — paginates `resources/list`
  with the same `nextCursor` loop and `MAX_ITERATIONS = 1000` guard as `get_tools_list`.
- `read_resource(session: ClientSession, uri: str) -> ResourceContents` — calls `resources/read`.

The existing `get_tools_list` is refactored to accept `session: ClientSession` and no
longer opens its own session internally. All callers pass the session from the enclosing
`open_init_session` span — consistent with how `get_resources_list` and `read_resource` work.

`_MCPToolInitializer._process_toolset` is extended: after tools are loaded, if
`toolset.resources.enabled` and the server advertised `capabilities.resources`:

1. Call `get_resources_list(session)`.
2. When `toolset.resources.items` is a non-empty list, filter to those URIs only.
3. Build `MCPResourceMeta` for each resource and append to `_MCPToolingContext.resource_metas`.
4. For each item with `eager: True`: call `read_resource(session, uri)`, build
   `MCPEagerResource`, append to `_MCPToolingContext.eager_resources`.

All resource operations reuse the same `open_init_session` span that loads tools.

```mermaid
sequenceDiagram
    participant Init as _MCPToolInitializer
    participant Client as _MCPToolsetClient
    participant Ctx as _MCPToolingContext
    participant CardProvider as _MCPResourceCardProvider
    participant Transformer as _MCPEagerResourceTransformer
    participant LLM

    Init->>Client: open_init_session()
    Client-->>Init: (session, InitializeResult)
    Init->>Client: get_tools_list(session) → register MCPTool objects
    Init->>Client: get_resources_list(session)
    Client-->>Init: [Resource, ...]
    Init->>Ctx: store MCPResourceMeta × N
    Note over Init: for eager items:
    Init->>Client: read_resource(session, uri) × M
    Client-->>Init: ResourceContents × M
    Init->>Ctx: store MCPEagerResource × M

    Note over CardProvider,Transformer,LLM: At request time — before first LLM call
    CardProvider->>Ctx: read resource_metas
    CardProvider->>LLM: inject frontmatter cards into system prompt
    Transformer->>Ctx: read eager_resources
    Note over Transformer: skip URIs already in message history
    Transformer->>LLM: prepend synthetic tool call pairs for new URIs only
```

---

### 3.7 Capability negotiation

**Data model**

A new frozen model `MCPServerCapabilities` (in `mcp_tooling/_mcp_server_capabilities.py`):

| Field | Source |
|---|---|
| `toolset_name` | `MCPToolSet.name` |
| `server_name` | `InitializeResult.serverInfo.name` |
| `server_version` | `InitializeResult.serverInfo.version` |
| `protocol_version` | `InitializeResult.protocolVersion` |
| `supports_tools` | `InitializeResult.capabilities.tools is not None` |
| `supports_resources` | `InitializeResult.capabilities.resources is not None` |
| `supports_prompts` | `InitializeResult.capabilities.prompts is not None` |

`server_capabilities` has no direct consumer in Phase 1 beyond the capability gating logic
in `_process_toolset` itself. It is stored on `_MCPToolingContext` for two reasons: (a) to
make capability decisions inspectable in logs and tests without re-parsing `InitializeResult`,
and (b) so Phase 2 (Prompts, tool annotations) can read `supports_prompts` without reopening
this design.

**Session refactor**

`_MCPToolsetClient` gains `open_init_session()` — an `@asynccontextmanager` that yields
`(session, InitializeResult)`, capturing the currently-discarded initialize result. Reuses
the same connection setup as the existing session context to avoid duplication.

`_MCPToolInitializer._process_toolset` uses a **single** `open_init_session` span for the
entire toolset initialization (tools + resource metadata + eager reads), resolving the
N+1 session issue.

`DialMCPToolSet` → `MCPToolSet` conversion: when `_process_toolset` resolves a
`DialMCPToolSet` into a plain `MCPToolSet`, the `resources` field must be explicitly
copied — `MCPToolSet(..., resources=dial_toolset.resources)`. Without this, the field
defaults to `None` and resource loading is silently skipped.

**Capability gating**

| Condition | Behaviour |
|---|---|
| `capabilities.tools is not None` | Load tools (existing behaviour) |
| `capabilities.tools is None` | Skip tools; log warning |
| `resources.enabled AND capabilities.resources is not None` | List resources |
| `resources.enabled AND capabilities.resources is None` | Skip; log warning |

---

### 3.8 Structured output (success path)

**Owner:** `_MCPTool._run_in_stage_async`

**Change:** In the success path, if `text_parts` is empty and
`tool_call_result.structuredContent` is non-None, serialize it as a JSON string and use
it as `tool_content`. This matches the MCP spec's backward-compatibility recommendation
for servers that return structured output without a text serialization.

---

## Secondary Fixes

### Independent error handling per capability

Resource metadata listing, eager content reads, and tool loading are wrapped in independent
`try/except` blocks inside `_process_toolset`. Failures are recorded as
`ToolInitializationException` entries in `_MCPToolingContext.exceptions`; a resource
failure never prevents tools from being registered.

### `get_resources_list` pagination

Follows the same `nextCursor` loop and `MAX_ITERATIONS = 1000` guard as `get_tools_list`.

---

## Out of Scope

**MCP Prompts (deferred to Phase 2)**
Loading and integrating MCP server prompts (`prompts/list` + `prompts/get`) is deferred.
`MCPServerCapabilities.supports_prompts` is stored now so Phase 2 can use it without
reopening this design.

**Tool annotations (deferred to Phase 2)**
Surfacing `title`, `readOnlyHint`, and `destructiveHint` in tool descriptions exposed to the LLM.

**Blob resources (deferred to Phase 2)**
Binary resource contents require DIAL attachment upload via `AttachmentService`. In Phase 1,
blob resources are skipped with `log.warning` in both listing and eager reads.

**Resource subscriptions (`resources/subscribe`)**
Requires a persistent client session for push notifications — incompatible with the current
request lifecycle.

**Resource templates (`resources/templates/list`)**
Parameterized URIs require user input to materialize. No UI mechanism exists.

**Elicitation**
Requires a pause/resume mechanism in the orchestrator and DIAL-side UI.

**Stateless protocol (RC 2026-07-28)**
Capability negotiation (§3.7) and the single-session approach will need redesigning once
the RC stabilises. Reference: https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/

**Logging capability**
Deprecated in the 2026-07-28 RC; not implemented.

**Roots and Sampling**
Both deprecated in the 2026-07-28 RC; not implemented.

---

## Configuration / Usage Examples

### Lazy loading — all resources from server

```json
{
  "type": "mcp",
  "name": "database-assistant",
  "description": "PostgreSQL access tools for the orders database",
  "mcp_server_info": {
    "url": "https://my-mcp-server/mcp",
    "protocol": "streamable_http"
  },
  "resources": {"enabled": true}
}
```

All resources the server declares are listed as frontmatter cards. The LLM calls
`read_mcp_resource` to fetch any content it needs.

### Lazy loading with URI filter

```json
"resources": {
  "enabled": true,
  "items": [
    {"uri": "schema://tables"},
    {"uri": "schema://indexes"}
  ]
}
```

Only these two resources are exposed. Both are lazy.

### Mixed: one eager, one lazy

```json
"resources": {
  "enabled": true,
  "items": [
    {"uri": "config://app-settings", "eager": true},
    {"uri": "schema://tables"}
  ]
}
```

`config://app-settings` is pre-fetched at init and injected as a synthetic tool call pair
before the first user message. `schema://tables` appears as a frontmatter card only —
fetched when the LLM calls `read_mcp_resource`.

### All resources eager

```json
"resources": {
  "enabled": true,
  "items": [
    {"uri": "config://app-settings", "eager": true},
    {"uri": "schema://tables", "eager": true}
  ]
}
```

Both resources are pre-fetched. Two synthetic tool call pairs are injected.

### `DialMCPToolSet` — same fields apply

```json
{
  "type": "dial-mcp",
  "deployment_id": "toolsets/abc123/MyServer",
  "resources": {"enabled": true}
}
```

### Existing config — no change required

```json
{
  "type": "mcp",
  "name": "my-server",
  "mcp_server_info": {"url": "...", "protocol": "streamable_http"}
}
```

`resources` defaults to `None`. Behaviour is identical to the current implementation.

---

## Migration

### Breaking changes

None. All new fields are optional with `enabled: false` defaults.

### Non-breaking changes

Running `make dump_app_schema` after this change regenerates the JSON manifest schema to
include `resources` as an optional object on `MCPToolSet` and `DialMCPToolSet`. Existing
manifests that omit this field continue to validate and behave identically.

---

## Summary of Changes

### `config/toolsets/`

| Change | Detail |
|---|---|
| ✚ `MCPResourceConfig` in `mcp.py` | New frozen model: `uri`, `eager: bool = False` |
| ✚ `MCPResourcesConfig` in `mcp.py` | New frozen model: `enabled`, `items: list[MCPResourceConfig] \| None` |
| ~ `MCPToolSet` in `mcp.py` | Add `resources: MCPResourcesConfig \| None = None` |
| ~ `DialMCPToolSet` in `dial_mcp.py` | Add `resources: MCPResourcesConfig \| None = None` |

### `mcp_tooling/`

| Change | Detail |
|---|---|
| ✚ `_mcp_resource_meta.py` | New frozen model `MCPResourceMeta` (URI, name, description, mime_type, toolset attribution — no content; covers text and blob resources) |
| ✚ `_mcp_eager_resource.py` | `MCPEagerTextResource(MCPResourceMeta)` with `text: str`; `MCPEagerResource` type alias (union, blob variant added in Phase 2) |
| ✚ `_mcp_server_capabilities.py` | New frozen model `MCPServerCapabilities` |
| ✚ `_mcp_resource_card_provider.py` | Implements `PromptPartProvider`; renders frontmatter cards for all listed resources; registered via `@multiprovider` |
| ✚ `_mcp_eager_resource_transformer.py` | Implements `MessagesTransformer`; prepends synthetic `read_mcp_resource` tool call pairs for eager resources |
| ✚ `_read_mcp_resource_tool.py` | Internal tool; resolves URI to toolset via `_MCPToolingContext.resource_metas`; fetches content via `_MCPSessionManager` on demand |
| ~ `_mcp_tooling_context.py` | Add `resource_metas`, `eager_resources`, `server_capabilities` fields with thread-safe helpers |
| ~ `_mcp_toolset_client.py` | Add `open_init_session()` context manager; refactor `get_tools_list` to accept `session: ClientSession`; add `get_resources_list(session)`, `read_resource(session, uri)` helpers |
| ~ `_mcp_tool_initializer.py` | Use `open_init_session`; capability gating via `InitializeResult`; copy `resources` field when converting `DialMCPToolSet → MCPToolSet`; list resources and read eager content in `_process_toolset` |
| ~ `mcp_tooling_module.py` | Register `_MCPResourceCardProvider`, `_MCPEagerResourceTransformer`; provide `_ReadMcpResourceTool` conditionally when any toolset has `resources.enabled` |
| ~ `_mcp_tool.py` | Surface `structuredContent` as text in success path when no text blocks present |

---

## Review Notes — Round 1

- **Reviewer:** Claude (quickapps-design-review skill)
- **Date:** 2026-07-22

### Verdict

`Blocking issues must be addressed`

The design is well-structured and detailed. The Mermaid diagram, table-driven capability gating, and out-of-scope justifications are all clear. Two blocking issues need resolving before approval: a `resources` field propagation gap in `DialMCPToolSet` resolution, and an underspecified on-demand session strategy for `_ReadMcpResourceTool`. Several non-blocking suggestions would improve robustness and clarity.

### Blocking issues

1. **§3.1 / §3.7 — `resources` field lost during `DialMCPToolSet` resolution** — `_MCPToolInitializer._process_toolset` (lines 261–279 of `_mcp_tool_initializer.py`) constructs a plain `MCPToolSet` from the resolved `DialMCPToolSet`, copying only `name`, `description`, `enabled`, `allowed_tools`, `attachment`, `fallback_configuration`, and `mcp_server_info`. The new `resources` field on `DialMCPToolSet` is **not listed** in `MCPToolSet(...)` constructor call that replaces it. As designed, the `Configuration / Usage Examples` section shows `DialMCPToolSet` using `resources.enabled: true`; without copying the field, `DialMCPToolSet` resource config is silently dropped. The design must either (a) add `resources=toolset_info.resources` to the `MCPToolSet(...)` constructor call in `_process_toolset`, or (b) pass the resource config separately and thread it through outside the resolution step.
   **Suggestion:** Add `resources=toolset_info.resources` to the `MCPToolSet(...)` construction in `_process_toolset` and document this copying explicitly in §3.6.

2. **§3.4 — On-demand session strategy for `_ReadMcpResourceTool` unresolved** — The tool description says "Obtain a per-request session via `_MCPSessionManager` for the owning toolset." During tool listing (`get_tools_list`), the current codebase opens a **short-lived init session** that is discarded after listing (see `_MCPToolsetClient.get_tools_list` docstring: "Listing deliberately uses its own short-lived session"). The long-lived `_MCPSessionManager` session is opened lazily on the first `call_mcp_tool` call. The design proposes `open_init_session()` for the init path, but does not clarify whether `_ReadMcpResourceTool` reuses the existing `_MCPSessionManager` session (which runs `tools/call`, not `resources/read`) or whether a separate session key is needed. Without this, there is ambiguity about whether the same session can multiplex both `call_tool` and `resources/read`, and whether `MCPToolSetClient` needs a new session-facing method or the existing one is reused directly.
   **Suggestion:** Add a paragraph to §3.4 clarifying the session reuse strategy: either state that `_MCPSessionManager` sessions support both `call_tool` and `resources/read` on the same `ClientSession` (which the MCP SDK does allow), or add a separate session key strategy for resource reads, and specify the method signature on `_MCPToolsetClient` that `_ReadMcpResourceTool` will call.

### Suggestions

1. **§3.2 / §3.5 — `eager` filtering interaction with `items: None`** — §3.2 shows that `items: None` means "expose all resources the server declares, all lazy." §3.5 says eager items are those with `eager: True` in `toolset.resources.items`. When `items` is `None`, there are no eager entries by definition — but this falls out implicitly. The doc should make it explicit (one sentence): "When `items` is `None`, no resources are pre-fetched; eager loading requires an explicit `items` list."

2. **§3.4 — Missing: behavior when the same URI appears in multiple toolsets** — The `_ReadMcpResourceTool` looks up `MCPResourceMeta` by URI in `_MCPToolingContext.resource_metas`. If two toolsets expose a resource with the same URI (e.g. `config://app-settings`), the lookup is ambiguous. The design should state whether the first match wins, whether an error is raised at listing time, or whether URIs are assumed globally unique.

3. **§3.5 — Insertion point for eager pairs is ambiguous** — The transformer is described as prepending pairs "before the first user message," but `SyntheticToolCallInjector._after_first_user_idx` (used by the existing skill injector) inserts **after** the first user message. If `_MCPEagerResourceTransformer` inserts **before** the first user message, some LLM providers reject a conversation that starts with an assistant message. Clarify the exact insertion position and confirm it is compatible with the same constraint the skills injector already handles.

4. **§3.7 — `MCPServerCapabilities` field `server_capabilities: list[MCPServerCapabilities]`** — In §3.2 the design adds a field `server_capabilities: list[MCPServerCapabilities]` to `_MCPToolingContext`, but in the Summary of Changes table (§Summary), this field appears only in the `_mcp_tooling_context.py` row without being explicitly named. More importantly, the design never shows where `MCPServerCapabilities` objects are consumed after being stored. If they are only stored for Phase 2 use, say so explicitly; if they gate Phase 1 behavior beyond the capability-check in §3.7, name the consumer.

5. **Migration — Non-breaking changes section has unnecessary prose** — "Running `make dump_app_schema` after this change regenerates the JSON manifest schema..." is a developer workflow instruction, not backward-compatibility information. This sentence belongs in the implementation notes of the PR, not the design doc's Migration section. Per project rubric, Migration should describe what changes for existing users; developer tasks are out of place here.

### Nits

1. **§3.1 — `MCPResourcesConfig` field declaration** — The design declares `resources: MCPResourcesConfig | None = Field(default=None)` on both `MCPToolSet` and `DialMCPToolSet`, but the `Design Goals` say "Existing manifests without the new fields behave identically to today." Behaviorally `None` and `MCPResourcesConfig(enabled=False)` are equivalent but the design does not say so explicitly. A note in §3.1 confirming `None` is treated as disabled would remove any reader doubt.

2. **Title / header — "Phase 1" is not in the filename** — The doc's title is "Phase 1: Resources" and the scope line says "Prompts and Tool Annotations are deferred to future iterations", but the filename is `mcp_capabilities_extension.md` with no phase marker. Future Phase 2 will need a distinct file. This is fine as-is, but a sentence in the scope or a note in Out of Scope pointing to where Phase 2 will live would help readers orient themselves.

---

## Review Notes — Round 2

- **Reviewer:** Claude (quickapps-design-review skill)
- **Date:** 2026-07-22

### Verdict

`Blocking issues must be addressed`

The rewrite is a major improvement: Prompts and Tool Annotations are cleanly deferred, the eager-loading and deduplication model is well-specified, the session ambiguity from Round 1 is addressed in §3.4, and the DialMCPToolSet copy requirement is now documented in §3.7. One blocking issue remains (the insertion-point description in §3.5 contradicts LLM API requirements and existing codebase behavior). Two suggestions from Round 1 are still open, and one new blocking issue was introduced by the deduplication section.

### Blocking issues

1. **§3.5 — "before the first user message" contradicts LLM API requirements and existing behavior** — The section states pairs are "inserted before the first user message." The current `_after_first_user_idx` (in `common/synthetic_injection/synthetic_tool_call_injector.py:174`) returns `i + 1`, inserting **after** the first user message — the convention used by every other `SyntheticToolCallInjector` in the codebase. Inserting assistant+tool messages before any user message produces a conversation that starts with `role=assistant`, which the OpenAI Chat Completions API and most DIAL-proxied providers reject with a 400 error. The multi-turn deduplication examples ("Turn 1 — history has no `read_mcp_resource` calls") confirm the design expects pairs to precede user messages, but that is the wrong position. The design must specify insertion **after** the first user message (matching `_after_first_user_idx`) and update the deduplication examples accordingly.
   **Suggestion:** Change "inserted before the first user message" to "inserted after the first user message, consistent with `_after_first_user_idx`." Update the Turn 1 example to show pairs between the first user message and any subsequent content.

2. **§3.5 — Per-turn deduplication scans for `tool_use` blocks, but the message format uses `tool_calls` on assistant messages** — The deduplication logic "collects all URIs that already appear as `tool_use` blocks with `name == 'read_mcp_resource'`." In the aidial-sdk message format (used throughout this codebase — see `_build_pair` in `synthetic_tool_call_injector.py:209`), synthetic pairs are represented as `Message(role=Role.ASSISTANT, tool_calls=[ToolCall(...)])` and `Message(role=Role.TOOL, tool_call_id=...)` — not as `tool_use` blocks. The term "tool_use blocks" is Anthropic's raw API representation and is not the SDK's internal model. The scan logic should be described in terms of `Role.ASSISTANT` messages with `tool_calls` containing `FunctionCall.name == "read_mcp_resource"`, or equivalently, `Role.TOOL` messages whose `tool_call_id` matches a known pattern. As written, an implementer will not know which field to inspect.
   **Suggestion:** Replace "collects all URIs that already appear as `tool_use` blocks with `name == 'read_mcp_resource'"` with language referencing the SDK message model: "collects all URIs already present as `FunctionCall.name == 'read_mcp_resource'` in assistant messages' `tool_calls`, or equivalently as `tool_call_id`s matching prior synthetic injections."

### Suggestions

1. **§3.4 — Duplicate URI across toolsets still unaddressed** — Round 1 Suggestion 2 is still open. When two toolsets expose the same URI (e.g. `config://app-settings`), the lookup in step 1 of `_ReadMcpResourceTool` is ambiguous. The doc added "The lookup in step 1 determines which toolset's session is used; the tool is not duplicated per toolset" but does not state the disambiguation rule. Add one sentence: first-registered URI wins (i.e., the first `MCPResourceMeta` match in `resource_metas` order), or raise at listing time if duplicate URIs are detected.

2. **§3.2 / §3.5 — `items: None` and eager loading still implicit** — Round 1 Suggestion 1 is partially addressed by the `items` field description in §3.1 ("None = expose all resources the server declares, all lazy"), but §3.5 says eager items come from `toolset.resources.items` with `eager: True` without noting the `None` case explicitly. One sentence in §3.5 eliminates any ambiguity: "When `items` is `None`, no eager items exist and the transformer is a no-op."

3. **§3.2 — `server_capabilities` list purpose still opaque** — `_MCPToolingContext.server_capabilities: list[MCPServerCapabilities]` is stored at init time, but the only consumer named in the doc is the capability-gating check in `_process_toolset` — which reads `InitializeResult` directly, not the stored list. If `server_capabilities` is reserved for Phase 2 consumers (e.g., a Phase 2 prompts initializer reading `supports_prompts`), say so explicitly. If it serves no Phase 1 consumer, note it as "stored for Phase 2 use" in the §3.7 data model table.

### Nits

1. **Migration — Non-breaking changes** — Round 1 Nit 5 is still open. "Running `make dump_app_schema` after this change regenerates the JSON manifest schema..." is a developer task, not backward-compatibility information for users. Remove or move to PR implementation notes.

2. **§3.5 — `tool_use` vs `tool_calls` terminology** — The blocking issue above addresses the functional problem; even after the fix, ensure the section uses the codebase's terminology consistently (`tool_calls` / `FunctionCall` / `ToolCall`) rather than Anthropic raw API terms (`tool_use`).

### Changes since previous round

1. **Blocking 1 (DialMCPToolSet resources field lost)** — **resolved**. §3.7 now explicitly states the `resources` field must be copied in the `DialMCPToolSet → MCPToolSet` constructor call, with a named fix: `resources=toolset_info.resources`.
2. **Blocking 2 (on-demand session strategy unresolved)** — **resolved**. §3.4 now states that `resources/read` is issued on the same `ClientSession` already used for `tools/call`, with no separate session key needed.
3. **Suggestion 1 (items: None / eager interaction)** — **partially addressed**. §3.1 field description covers it; §3.5 still lacks an explicit sentence.
4. **Suggestion 2 (duplicate URI across toolsets)** — **still open**. §3.4 added context about the single tool entry but does not state the disambiguation rule.
5. **Suggestion 3 (insertion point ambiguity)** — **still open** and now a blocking issue (new Blocking 1 above). The text changed from implicit to explicit "before the first user message," which makes the problem clearer but also clearly incorrect.
6. **Suggestion 4 (server_capabilities consumer)** — **still open** as Suggestion 3 above.
7. **Nit 5 (migration developer prose)** — **still open** as Nit 1 above.
8. **Nit 1 (None vs disabled)** — **resolved**. "Existing config — no change required" example now explicitly states "`resources` defaults to `None`. Behaviour is identical to the current implementation."
9. **Nit 2 (Phase 2 filename)** — **still open** but remains minor.

---

## Review Notes — Round 3

- **Reviewer:** Claude (quickapps-design-review skill)
- **Date:** 2026-07-22

### Verdict

`Ready for approval pending minor suggestions`

The two Round 2 blocking issues have been resolved: the insertion-point bug is corrected ("after the first user message"), and the `tool_use` terminology has been replaced with "assistant tool-call messages invoking `read_mcp_resource`." Two suggestions and one nit from Round 2 are still open, but none are blocking. The doc is in good shape.

### Blocking issues

None.

### Suggestions

1. **§3.5 — Deduplication scan field still underspecified** — The description "collects all URIs that already appear as assistant tool-call messages invoking `read_mcp_resource`" is improved over Round 2 but still leaves an implementer guessing which SDK field to inspect. The codebase uses `Role.ASSISTANT` messages with `tool_calls: list[ToolCall]` where `ToolCall.function.name == "read_mcp_resource"` (see `_build_pair` in `common/synthetic_injection/synthetic_tool_call_injector.py:209`). Name the field explicitly: "scans `Role.ASSISTANT` messages for `ToolCall.function.name == 'read_mcp_resource'` in their `tool_calls`." One sentence eliminates the ambiguity that caused Round 2's blocking finding.

2. **§3.4 — Duplicate URI across toolsets still unresolved** — Carried over from Round 2 Suggestion 1 (and Round 1 Suggestion 2). The tool lookup in step 1 is a list scan; when two toolsets expose the same URI, the first match in `resource_metas` order wins silently. Add one sentence stating the rule: "If the same URI appears in multiple toolsets, the first `MCPResourceMeta` match in `resource_metas` registration order is used."

3. **§3.2 / §3.7 — `server_capabilities` field purpose not stated for Phase 1** — `_MCPToolingContext.server_capabilities: list[MCPServerCapabilities]` is stored at init time but no Phase 1 consumer reads from it (the capability-gating check in `_process_toolset` reads `InitializeResult` directly, not this list). The data model table in §3.7 says `supports_prompts` is "stored for Phase 2" but does not say the same for the list as a whole. Add a note to the §3.2 snippet or the §3.7 data model: "`server_capabilities` has no Phase 1 consumer — it is stored for Phase 2 use (e.g., prompts initializer reading `supports_prompts`)."

### Nits

1. **§3.5 — `items: None` and eager loading still implicit** — When `items` is `None`, no eager entries exist by definition, but this is never stated in §3.5. One sentence closes the gap: "When `items` is `None`, no eager items exist and the transformer is a no-op."

2. **Migration — Non-breaking changes** — "Running `make dump_app_schema` after this change regenerates the JSON manifest schema..." is a developer workflow instruction, not backward-compatibility information. This sentence belongs in the PR implementation notes, not the Migration section. Remove or replace with a single line: "Existing manifests that omit `resources` continue to validate and behave identically."

### Changes since previous round

1. **Blocking 1 (insertion point "before" → "after")** — **resolved**. §3.5 line now reads "after the first user message (consistent with the `_after_first_user_idx` convention)."
2. **Blocking 2 (`tool_use` terminology / scan field ambiguity)** — **partially addressed**. "tool_use blocks" replaced with "assistant tool-call messages invoking `read_mcp_resource`." The functional correctness concern is resolved; the implementation-level field specificity remains as Suggestion 1 above.
3. **Suggestion 1 (duplicate URI disambiguation)** — **still open** as Suggestion 2 above.
4. **Suggestion 2 (items: None / eager in §3.5)** — **still open** as Nit 1 above.
5. **Suggestion 3 (server_capabilities consumer opaque)** — **still open** as Suggestion 3 above.
6. **Nit 1 (migration developer prose)** — **still open** as Nit 2 above.
