# Design: External Memory Provider Integration

- **Status:** Draft
- **Dependencies:**
  - [Config-Driven Hooks](../config_driven_hooks.md)
  - [Memory Architecture](memory_architecture.md) *(feat/memory_desighn_doc)*

---

## Problem Statement

QuickApps has its own memory implementation (LanceDB + DIAL file storage). Operators currently have no
way to substitute a different memory backend — they're locked into the QuickApps-native implementation.

The goal is to let operators choose any open-source or self-hosted memory provider (mem0, basic-memory,
Graphiti, etc.) and wire it into a QuickApp without modifying application code.

---

## Design Goals

- An operator can configure an external memory backend by editing the app's JSON manifest only.
- User isolation is preserved: each DIAL user's memories are separate regardless of the backend.
- No skill is required for basic integration — the LLM understands provider tools from their native MCP descriptions, as in Claude Code and Cursor. Skills remain available as an optional layer for operators who need to enforce specific memory behaviors.
- Adding support for a new provider in the future requires minimal effort.

---

## Background: How QuickApps Memory Works Today

QuickApps memory uses three mechanisms:

**1. MCP toolset** — the memory server is declared in `ApplicationConfig.tool_sets` as a `dial-mcp` entry.
The agent calls `store_memory` and `search_archive` tools during conversation.

**2. Hook-based context injection** *(optional pattern)* — the `on_request_start` hook calls a retrieval
tool before the first LLM turn and injects the result as a synthetic `(ASSISTANT tool_call / TOOL
response)` pair into the message history via `_ConfigDrivenToolCallHook`. TTL caching prevents redundant
calls.

**3. Skill** *(optional)* — a predefined Markdown skill tells the LLM which tools exist and when to
use them. For QuickApps' own memory server this is predefined. For external providers it is not
required — the LLM infers tool purpose from native MCP descriptions, the same way Claude Code and
Cursor work with MCP memory servers without any skill.

The hook-based injection is **one retrieval pattern, not a requirement**. The alternative is reactive
retrieval: the LLM calls memory tools (`search`, `list`) when it decides past context is relevant. This
is how every standard MCP client (Claude Code, Cursor) works. Both patterns can be used with external
providers; hooks add value but are not a prerequisite for integration.

**User isolation** is implicit: the memory MCP server authenticates via the user's DIAL API key, which
scopes all reads and writes to that user's DIAL file storage bucket. No `user_id` appears in tool
arguments — isolation is handled entirely by the auth layer.

```
Request arrives (DIAL API key = user A)
  → MCPToolInitializer connects to memory-server via DIAL (DIAL forwards user's key)
  → [Optional] Hook fires → calls memory-server_get_memories → injects top-N memories into history
  → Agent runs, calls store_memory / search_archive as needed
  → Memory server reads/writes user A's DIAL bucket (enforced by auth)
```

---

## Background: The External Memory Ecosystem

### These are single-user tools, not multi-tenant services

Every open-source memory provider surveyed — mem0-mcp, mcp-obsidian, basic-memory, Official MCP Memory,
Graphiti — was designed for **one person using one IDE**. In a typical Claude Code or Cursor setup, one
instance of the memory server equals one person's memory. The server runs as a local process or a personal
Docker container.

```
Typical usage (Claude Code / Cursor):

  Developer's machine
  ┌──────────────────────────────────────────┐
  │  Cursor IDE                              │
  │    └── MCP client                        │
  │          └── connects to mem0-mcp        │  ← one instance
  │                └── stores to ~/mem0.db   │  ← one user's data
  └──────────────────────────────────────────┘
```

The `user_id` / `group_id` parameters that some providers expose were added as an afterthought for managed
cloud tiers (mem0 cloud serves thousands of customers), not for the typical local use case. Several
providers (Official MCP Memory, basic-memory) have no user scoping at all.

**Multi-user isolation is not a built-in property of these providers.** For providers that run as a
shared server (mem0, Graphiti), isolation must be layered on top — through an adapter (Approach A) or
injected via config variables (Approach B). For file-based providers (basic-memory, Official MCP Memory),
isolation is already available today: DIAL already provides per-user file storage, and pointing the
provider's data path at the user's DIAL bucket is sufficient. Containers make this even simpler (the
bucket is mounted as a volume) but are not a prerequisite.

### MCP has no pre-turn injection

The MCP specification defines no mechanism for a server to push context before each user turn. All memory
retrieval in Claude Code and Cursor is **reactive** — the LLM calls memory tools when it judges past
context is relevant. There is no automatic injection.

**QuickApps' hooks system already does more than the MCP ecosystem standard.** The `on_request_start` hook
that calls a retrieval tool and synthetic-injects the result is a capability no standard MCP client has.

### Tool interface across providers

There is no naming standard. Three semantic roles appear consistently across all providers:

| Role | What it does | Example names |
|---|---|---|
| **Write** | Store a new fact or observation | `add_memory`, `add_memories`, `write_note`, `add_observations` |
| **Search** | Retrieve by semantic query | `search_memories`, `search_nodes`, `search` |
| **List** | Get all/top memories without a query | `get_memories`, `list_memories`, `read_graph`, `get_user_context` |

The **list** tool is the correct hook point if proactive `on_request_start` injection is configured — it
requires no query and returns the most relevant memories for the current user. It is not required for
reactive retrieval, where the LLM calls **search** directly when it needs context.

### Provider storage backends

Storage type determines whether a provider can use DIAL's per-user file storage for isolation. File-based
providers can write to a path inside the user's DIAL bucket — this works both today (current shared-service
model) and in the future container model. Providers backed by external databases cannot use DIAL file
storage and require a separate isolation mechanism.

| Provider | Storage | File-based? | Notes |
|---|---|---|---|
| **Official MCP Memory** | Single JSON file | ✅ Yes | Path via `MCP_MEMORY_FILE_PATH` |
| **basic-memory** | Markdown files | ✅ Yes | Vault path configurable |
| **mem0** (Chroma + SQLite config) | Files on disk | ✅ Yes | Non-default; requires config change |
| **mem0** (default Docker) | PostgreSQL + pgvector | ❌ No | Needs external persistent DB |
| **Graphiti** | Neo4j or FalkorDB | ❌ No | Requires external graph DB service |
| **Zep** | Proprietary DB | ❌ No | Long-running server with own storage |
| **mcp-obsidian** | Obsidian vault files | ❌ No† | †Requires Obsidian desktop app running |

---

## Model 1: Current Shared-Service Deployment

Today, QuickApps runs as a single shared deployment: one process serves all users.

The integration approach depends on the provider's storage model:

**File-based providers** (basic-memory, Official MCP Memory, mem0 with Chroma) — user isolation is
already solved by DIAL's per-user file storage. QuickApps already writes `memory.lance/` into each
user's DIAL bucket for its own memory implementation; the same mechanism applies to any external
file-based provider. No `user_id`, no adapter. The provider is configured with a data path inside the
user's DIAL bucket, and the DIAL auth layer enforces isolation.

```
DIAL
  ├── User A ──► QuickApps ──► file-based memory server (path = user A's DIAL bucket)
  ├── User B ──► QuickApps ──► file-based memory server (path = user B's DIAL bucket)
  └── ...          ← isolation is structural; no user_id in tool calls
```

**Server-based providers** (mem0 with pgvector, Graphiti) — a single shared service instance handles
requests from many different DIAL users simultaneously. The memory server must never let one user's
memories bleed into another's context. This requires explicit `user_id` scoping at every tool call.

```
DIAL
  ├── User A ──► QuickApps backend (shared) ──► Memory server (shared)
  ├── User B ──►                                       │
  └── User C ──►                               must isolate A/B/C
```

Two approaches address server-based isolation.

---

### Approach A: Memory Adapter (recommended for Model 1)

Build a thin MCP server for each provider that wraps the provider's native API and handles user identity
propagation internally. QuickApps always connects to the adapter using the same standard tool names,
regardless of which backend is underneath.

```
QuickApp config (identical for all backends)
  └── tool_sets: [{ type: "dial-mcp", dial_id: "memory-adapter" }]
  └── hooks:    [{ tool: "memory-adapter_memory_get_context" }]  ← optional

DIAL routes the call → adapter receives X-DIAL-API-Key header
  └── Adapter resolves user_id from header
  └── Calls backend (mem0 / basic-memory / …) with user_id
  └── Returns standardised response
```

**Confirmed:** `DialMCPToolSet` forwards the user's DIAL API key in request headers to the upstream MCP
server. The adapter can extract user identity from these headers with no changes to QuickApps core.

#### Standard tool contract

The adapter exposes a normalized interface so every Class 2 backend looks identical to QuickApps.
No skill is needed — the LLM understands these tools from their MCP descriptions.

| Tool | Parameters | Description |
|---|---|---|
| `memory_store` | `content: str` | Store a new fact. |
| `memory_search` | `query: str`, `limit?: int` | Semantic search. |
| `memory_get_context` | *(none)* | *(optional)* Top-N memories without a query. Only needed if proactive hook injection is configured. |
| `memory_delete` | `memory_id: str` | *(optional)* Delete a specific memory. |
| `memory_clear` | *(none)* | *(optional)* Wipe all memories for the current user. |

Normalization here serves a different goal than skills: it means every Class 2 adapter is wired by
the same one-line toolset config, and a single optional skill covers all of them if the operator
wants to enforce specific behavior.

#### Example: mem0 adapter

```
[ QuickApp agent ]
      │  memory_get_context / memory_store / memory_search
      ▼
[ mem0 Adapter ]  ← DIAL deployment
      │  reads X-DIAL-API-Key → resolves user_id
      │  calls mem0 REST API with user_id
      ▼
[ mem0 server ]   ← Docker: FastAPI + pgvector
      │  data partitioned per user_id in pgvector
      ▼
[ PostgreSQL + pgvector ]
```

Adapter sketch (~100 lines Python):

```python
from mcp.server.fastmcp import FastMCP
import httpx, os

mcp = FastMCP("mem0-adapter")
MEM0_URL = os.environ["MEM0_URL"]

def get_user_id(ctx) -> str:
    return ctx.request_context.headers.get("x-dial-api-key", "anonymous")

@mcp.tool()
async def memory_get_context(ctx) -> str:
    uid = get_user_id(ctx)
    r = await httpx.get(f"{MEM0_URL}/memories", params={"user_id": uid, "limit": 20})
    return format_memories(r.json()["results"])

@mcp.tool()
async def memory_store(content: str, ctx) -> str:
    uid = get_user_id(ctx)
    await httpx.post(f"{MEM0_URL}/memories", json={
        "messages": [{"role": "user", "content": content}],
        "user_id": uid
    })
    return "Stored."

@mcp.tool()
async def memory_search(query: str, ctx, limit: int = 5) -> str:
    uid = get_user_id(ctx)
    r = await httpx.post(f"{MEM0_URL}/search", json={
        "query": query, "filters": {"user_id": uid}, "limit": limit
    })
    return format_memories(r.json()["results"])
```

QuickApp config (same for every operator using any compliant adapter):

```json
{
  "tool_sets": [{ "type": "dial-mcp", "dial_id": "memory-adapter-mem0" }]
}
```

Optionally, add a hook for proactive injection and/or a skill for enforced behaviors:

```json
{
  "tool_sets": [{ "type": "dial-mcp", "dial_id": "memory-adapter-mem0" }],
  "hooks": [{
    "kind": "tool_call",
    "event": "on_request_start",
    "toolset_name": "memory-adapter-mem0",
    "tool_name": "memory_get_context",
    "arguments": {},
    "frequency": "append_if_changed",
    "refresh_condition": { "kind": "ttl", "ttl_minutes": 5 }
  }]
}
```

> **mem0's LLM dependency:** mem0 calls an LLM on every `add_memory` to extract structured facts from raw
> text. The adapter deployment must include an LLM endpoint (OpenAI, Anthropic, or a local Ollama/vLLM).
> This cannot be eliminated without forking mem0.

#### Open problems in Approach A

1. **Adapter maintenance** — each new provider needs a new adapter (~150 lines each). Adapters must be
   built, tested, and deployed. Organisational question: separate repo vs. bundled with QuickApps.
2. **mem0's LLM cost** — every write triggers an LLM inference pass (~1–2 s, API cost). Operators must
   supply an LLM endpoint.
3. **Graphiti/Zep** — require Neo4j or FalkorDB as the graph DB. High operational complexity.

---

### Approach B: Dynamic Variable Injection in Hooks

No adapter layer. QuickApps connects directly to a provider's MCP server. The hooks configuration is
extended with template variables resolved from the DIAL request context at runtime.

```
QuickApp config (provider-specific)
  └── hooks: [{ tool: "mem0_get_memories",
                arguments: {"filters": {"user_id": "{{dial_user_id}}"}} }]

Request arrives
  → Hook resolves {{dial_user_id}} → "user-abc-123"
  → Calls mem0_get_memories(filters={user_id: "user-abc-123"})
```

Proposed variables:

| Variable | Value |
|---|---|
| `{{dial_user_id}}` | Authenticated DIAL user identifier |
| `{{app_id}}` | The QuickApp's DIAL deployment ID |
| `{{session_id}}` | Current conversation session ID |

Code change in `_ConfigDrivenToolCallHook` — backwards-compatible, existing static configs unaffected:

```python
def _resolve_arguments(self, arguments: dict, context: RequestContext) -> dict:
    variables = {
        "dial_user_id": context.user_id,
        "app_id": context.app_id,
        "session_id": context.session_id,
    }
    return json.loads(Template(json.dumps(arguments)).substitute(variables))
```

#### Example: mem0 direct

```json
{
  "tool_sets": [{
    "type": "mcp_http",
    "url": "http://mem0-server:8888/mcp",
    "name": "mem0",
    "allowed_tools": ["add_memory", "get_memories", "search_memories"]
  }],
  "hooks": [{
    "kind": "tool_call",
    "event": "on_request_start",
    "toolset_name": "mem0",
    "tool_name": "get_memories",
    "arguments": { "filters": { "user_id": "{{dial_user_id}}" }, "limit": 20 },
    "frequency": "append_if_changed",
    "refresh_condition": { "kind": "ttl", "ttl_minutes": 5 }
  }]
}
```

No skill required — the LLM understands mem0's tools from their MCP descriptions. The LLM must pass
`"user_id": "{{dial_user_id}}"` correctly in write and search calls; this relies on the tool
descriptions making the argument mandatory and obvious, not on a skill.

#### Open problems in Approach B

1. **Template variable support doesn't exist yet** — code change required in QuickApps core.
2. **No skill portability** — without a normalized adapter, each provider has different tool names
   and argument shapes. If an operator wants a skill, they must write one per provider.
3. **Nested JSON injection** — mem0's `user_id` lives inside `{"filters": {"user_id": "..."}}`. Simple
   string substitution risks JSON injection if the user ID contains special characters.
4. **Weak isolation** — the memory server trusts whatever `user_id` the caller sends. A misconfigured
   hook silently accesses the wrong user's data. Approach A validates against the DIAL auth header.
5. **Providers without `user_id` argument** — OpenMemory bakes `user_id` in the SSE URL path. Supporting
   it would also require URL-level templating in the toolset config.

---

### Comparison: Approach A vs B in Model 1

| Dimension | Approach A: Adapter | Approach B: Dynamic Variables |
|---|---|---|
| Operator config | Identical for all backends | Different per provider |
| Skill required | No (optional) | No (optional, but non-portable across providers) |
| User isolation | Strong — enforced in adapter | Weak — trusts config |
| QuickApps code changes | None | Yes — template expansion in hooks |
| New provider support | Build an adapter (~150 lines) | Document config per provider |
| Risk of user data leak | Low | Higher — wrong template = data leak |

---

## Model 2: Future Container Deployment

In the planned container model, each user session runs in its own isolated container: **one container =
one user × one QuickApp**. The user's DIAL storage bucket is mounted as a volume.

This changes everything.

### How the container model works for file-based providers

A memory server running inside a per-user container is, by definition, serving exactly one user. It is
back to being the single-user tool it was designed to be. There is no shared state, no `user_id` needed
anywhere, no isolation machinery.

Note: the isolation principle is not new — DIAL's per-user file storage already enforces it in the
current shared-service model. The container model makes it structurally impossible to misconfigure
(a wrong data path can't accidentally reach another user's bucket), and removes the need for any process
lifecycle management to keep per-user server instances separated.

```
User starts a QuickApp session
        │
        ▼
Container spins up (this user × this QuickApp only)
┌─────────────────────────────────────────────────────┐
│  quickapps-backend    memory-sidecar                │
│       │               (basic-memory, Official MCP,  │
│       └───────────────  or mem0 with Chroma)        │
│                              │                      │
│                        /data/memory/ ◄── mounted    │
│                         ├── graph.json   from this  │
│                         ├── notes/       user's     │
│                         └── ...          DIAL bucket│
└─────────────────────────────────────────────────────┘
        │
Session ends → container stops → data in DIAL bucket
Next session → new container → same mount → memory intact
```

The memory sidecar is **stateless between sessions** — it writes to the mounted volume, not its own
filesystem. Spinning it up and down has zero data loss.

**QuickApps' own memory implementation already follows this exact pattern** — LanceDB stores
`memory.lance/` in the user's DIAL bucket. The container model makes this the universal convention for
any provider.

### Which providers fit the file-based / DIAL-bucket pattern

File-based providers that accept a configurable data path can use DIAL's per-user file storage for
isolation. This applies to both the current shared-service model (path resolves to the user's DIAL
bucket) and the container model (path is a mounted volume from the same bucket). Providers backed by
external database services cannot participate.

| Provider | File-based? | Data path config | Notes |
|---|---|---|---|
| **Official MCP Memory** | ✅ Yes | `MCP_MEMORY_FILE_PATH=<dial-bucket>/memory.jsonl` | Simplest option; no LLM needed; keyword search only |
| **basic-memory** | ✅ Yes | Vault path env var | Markdown notes; hybrid search; no LLM needed |
| **mem0** (Chroma + SQLite) | ✅ Yes (non-default config) | `path: <dial-bucket>/chroma` + `path: <dial-bucket>/mem0.db` | Semantic search; LLM needed for fact extraction |
| **mem0** (default pgvector) | ❌ No | — | PostgreSQL lives outside QuickApps' storage model |
| **Graphiti** | ❌ No | — | Neo4j / FalkorDB lives outside QuickApps' storage model |
| **Zep** | ❌ No | — | Zep server has its own persistent storage |
| **mcp-obsidian** | ❌ No | — | Requires Obsidian desktop app — incompatible with any server deployment |

### mem0 with file-based backends

mem0 can be made container-compatible by swapping its default PostgreSQL backend for local file-based
alternatives:

```python
config = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "memories",
            "path": "/data/memory/chroma"   # ← mounted from DIAL bucket
        }
    },
    "db": {
        "provider": "sqlite",
        "config": {
            "path": "/data/memory/mem0.db"  # ← same mount
        }
    }
}
```

This preserves mem0's semantic search and LLM-based fact extraction. Chroma's local mode is less
battle-tested than pgvector under concurrent writes, but in a single-user sidecar this is not a concern.
The LLM dependency remains: every `memory_store` call triggers an LLM inference pass for fact extraction.
The natural choice is to route this through DIAL's own LLM deployment.

### What the container model still needs

Even in the container model, there are open design questions:

1. **How does the operator declare a memory sidecar?** Options:
   - A dedicated `memory` field in `ApplicationConfig` (`"memory": {"enabled": true, "provider": "basic-memory"}`)
   - Extending the existing toolset config with a `"type": "sidecar-mcp"` variant
   - The orchestration layer (whatever manages containers) handles sidecar injection separately from the app config

2. **Standard tool names help for Class 2 adapters, not required for sidecars** — in the container
   model, the sidecar's native tool names are sufficient: the LLM reads their MCP descriptions and
   uses them without a skill. Normalized names only matter if the operator wants a single optional
   skill that works across multiple providers.

3. **Startup latency** — if proactive hook injection is configured, the memory sidecar must be ready
   before the first `on_request_start` hook fires. With reactive retrieval only, startup latency is
   less critical — the first tool call simply fails gracefully if the sidecar is still initialising.

---

## Recommendation: Sequencing

Three paths exist, with meaningfully different cost profiles:

| Option | Build now | Works today? | Becomes dead weight? |
|---|---|---|---|
| **File-based provider via DIAL bucket** | Per-user process lifecycle mechanism; provider config | ✅ Yes | No — same mechanism works in container model |
| **Server-based adapter (Approach A)** | Adapter per provider (~150 lines each) | ✅ Yes | Partially — adapter becomes unnecessary once containers ship; but low code volume |
| **Wait for containers, then sidecar** | Spec the config format + tool contract | ❌ Not yet | No — cleanest long-term path |

**Suggested path:**
- If external memory is needed today: start with a **file-based provider** (basic-memory or Official
  MCP Memory) wired to the user's DIAL bucket. No `user_id`, no adapter, no QuickApps core changes.
  This investment carries forward cleanly to the container model.
- If a server-based provider (mem0 pgvector) is specifically required: build an adapter. It is a small
  investment and the multi-tenancy isolation is straightforward.
- The Dynamic Variable Injection approach (Approach B) is the highest-risk option and adds a
  QuickApps core change; avoid unless there is a strong reason to connect directly to a provider's
  native API without an adapter.

---

## Out of Scope

- **Building memory backends** — mem0, Graphiti, etc. are external projects. This document covers the
  integration layer only.
- **UI for memory management** — viewing and deleting memories from the DIAL UI is covered separately.
- **Storage-native approach** — wrapping providers at the storage layer requires forking. Ruled out.
- **Zep Cloud / managed SaaS** — does not fit the self-hosted operator model.
- **Letta / MemGPT** — an agent framework, not a drop-in memory provider. Its memory tools are internal
  to its own agent runtime.
- **Obsidian** — requires a running desktop application. Not suitable for any server deployment model.

---

## Open Questions

1. **Which integration path first?** File-based providers (basic-memory, Official MCP Memory) are viable
   today via DIAL bucket access, with no adapter and no QuickApps core changes. Server-based adapters
   (Approach A) are still worth building if a provider with richer semantics (mem0 pgvector) is
   specifically requested. Approach B (dynamic variables) is the highest-risk option and should be
   deprioritised.

2. **Container granularity:** confirmed as per-user (one container = one user × one QuickApp). This
   completely eliminates the `user_id` problem for Model 2.

3. ~~**Does `DialMCPToolSet` forward the DIAL API key to the upstream server?**~~ **Resolved — yes.**
   Approach A's user isolation model is sound without changes to QuickApps core.

4. **Sidecar config format:** should memory be a first-class field in `ApplicationConfig`
   (`"memory": {"provider": "basic-memory"}`), or expressed through the existing toolset + hook
   mechanism with a new `"type": "sidecar-mcp"` variant?

5. **mem0's LLM cost:** every `memory_store` triggers an LLM inference for fact extraction (~1–2 s,
   API cost). Should the adapter / sidecar expose an `infer: false` mode that stores verbatim text
   and skips extraction?

6. **Reference provider for v1:** mem0 (with Chroma config) offers the best balance of semantic
   search quality and container compatibility. basic-memory is simpler (no LLM dependency) but
   keyword-only. Which is the right default to ship first?
