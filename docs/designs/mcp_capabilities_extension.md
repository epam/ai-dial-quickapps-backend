# Design: MCP Capabilities Extension — Phase 1: Resources

- **Status:** Draft
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

**Behavior:** `resources` defaults to `enabled: false`. Initialization runs exactly as
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
registered per-request when at least one toolset has `resources.enabled: true`.

**Tool schema:**

```python
{
  "name": "read_mcp_resource",
  "description": "Read the content of an MCP resource by its URI.",
  "input_schema": {
    "type": "object",
    "properties": {
      "uri": {"type": "string", "description": "URI of the resource to read."}
    },
    "required": ["uri"]
  }
}
```

**Semantics:**

1. Look up the `MCPResourceMeta` for the requested URI in `_MCPToolingContext.resource_metas`.
2. If not found: return an error response — `"No resource registered with URI '{uri}'"`.
3. Obtain a per-request session via `_MCPSessionManager` for the owning toolset.
4. Call `resources/read(uri)` and return `TextResourceContents.text`.

Blob resources (`BlobResourceContents`) are skipped in Phase 1. If the server returns only
blob content, the tool returns: `"Resource '{uri}' contains binary content (blob). Binary
resources are not supported in this version."` A follow-up design covers blob upload via
`AttachmentService`.

The tool appears as a single shared entry in the tool list alongside MCP tools. The lookup
in step 1 determines which toolset's session is used; the tool is not duplicated per toolset.

---

### 3.5 Eager loading via synthetic tool call injection

**Owner:** `mcp_tooling/_mcp_eager_resource_transformer.py`

A new `MessagesTransformer`, `_MCPEagerResourceTransformer`, reads
`_MCPToolingContext.eager_resources` and prepends one synthetic tool call pair per eager
resource to the message list before the first user message.

Each pair:

1. An **assistant message** with a `tool_use` block:
   `{"name": "read_mcp_resource", "input": {"uri": "<resource_uri>"}}`
2. A **tool result message** with the pre-fetched `text` as the tool result content.

Pairs are inserted in declaration order (the order items appear in `toolset.resources.items`
across all toolsets, in toolset registration order). When `eager_resources` is empty,
the transformer is a no-op.

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
    Transformer->>LLM: prepend synthetic tool call pairs to messages
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
| `supports_prompts` | `InitializeResult.capabilities.prompts is not None` (stored for Phase 2) |

**Session refactor**

`_MCPToolsetClient` gains `open_init_session()` — an `@asynccontextmanager` that yields
`(session, InitializeResult)`, capturing the currently-discarded initialize result. Reuses
the same connection setup as the existing session context to avoid duplication.

`_MCPToolInitializer._process_toolset` uses a **single** `open_init_session` span for the
entire toolset initialization (tools + resource metadata + eager reads), resolving the
N+1 session issue.

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
| ~ `_mcp_toolset_client.py` | Add `open_init_session()` context manager; add `get_resources_list(session)`, `read_resource(session, uri)` helpers |
| ~ `_mcp_tool_initializer.py` | Use `open_init_session`; capability gating via `InitializeResult`; list resources and read eager content in `_process_toolset` |
| ~ `mcp_tooling_module.py` | Register `_MCPResourceCardProvider`, `_MCPEagerResourceTransformer`, `_ReadMcpResourceTool` |
| ~ `_mcp_tool.py` | Surface `structuredContent` as text in success path when no text blocks present |
