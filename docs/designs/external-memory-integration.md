# Design: External Memory Provider Integration

- **Status:** Draft
- **Dependencies:**
  - [Config-Driven Hooks](config_driven_hooks.md)
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
- The predefined memory skill works across backends, or at least a clear path exists to achieve that.
- Adding support for a new provider in the future requires minimal effort.

---

## Background: How QuickApps Memory Works Today

QuickApps memory uses three interlocking mechanisms:

**1. MCP toolset** — the memory server is declared in `ApplicationConfig.tool_sets` as a `dial-mcp` entry.
The agent calls `store_memory` and `search_archive` tools during conversation.

**2. Hook-based context injection** — the `on_request_start` hook calls a retrieval tool before the first
LLM turn and injects the result as a synthetic `(ASSISTANT tool_call / TOOL response)` pair into the
message history via `_ConfigDrivenToolCallHook`. TTL caching prevents redundant calls.

**3. Skill** — a predefined Markdown skill tells the LLM which tools exist and when to use them.

**User isolation** is implicit: the memory MCP server authenticates via the user's DIAL API key, which
scopes all reads and writes to that user's DIAL file storage bucket. No `user_id` appears in tool
arguments — isolation is handled entirely by the auth layer.

```
Request arrives (DIAL API key = user A)
  → MCPToolInitializer connects to memory-server via DIAL (DIAL forwards user's key)
  → Hook fires → calls memory-server_get_memories → injects top-N memories into history
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

**Multi-user isolation is not a built-in property of these providers.** It must be layered on top — either
through an adapter (Model 1, Approach A), injected via config variables (Model 1, Approach B), or solved
structurally by giving each user their own isolated server instance (Model 2: containers).

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

The **list** tool is the correct hook point for `on_request_start` context injection — it requires no
query and returns the most relevant memories for the current user.

### Provider storage backends

For the container model (see Model 2), storage type is the deciding factor: only file-based providers
can write to a mounted DIAL bucket and survive container restarts.

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

Today, QuickApps runs as a single shared deployment: one process serves all users. When an external
memory provider is connected, it too is a shared service — a single mem0 or Graphiti server handling
requests from many different DIAL users simultaneously.

```
DIAL
  ├── User A ──► QuickApps backend (shared) ──► Memory server (shared)
  ├── User B ──►                                       │
  └── User C ──►                               must isolate A/B/C
```

The central challenge: the memory server must never let one user's memories bleed into another's context.
This requires explicit `user_id` scoping at every tool call.

Two approaches address this.

---

### Approach A: Memory Adapter (recommended for Model 1)

Build a thin MCP server for each provider that wraps the provider's native API and handles user identity
propagation internally. QuickApps always connects to the adapter using the same standard tool names,
regardless of which backend is underneath.

```
QuickApp config (identical for all backends)
  └── tool_sets: [{ type: "dial-mcp", dial_id: "memory-adapter" }]
  └── hooks:    [{ tool: "memory-adapter_memory_get_context" }]
  └── skills:   ["memory"]   ← single portable skill

DIAL routes the call → adapter receives X-DIAL-API-Key header
  └── Adapter resolves user_id from header
  └── Calls backend (mem0 / basic-memory / …) with user_id
  └── Returns standardised response
```

**Confirmed:** `DialMCPToolSet` forwards the user's DIAL API key in request headers to the upstream MCP
server. The adapter can extract user identity from these headers with no changes to QuickApps core.

#### Standard tool contract

| Tool | Parameters | Description |
|---|---|---|
| `memory_get_context` | *(none)* | Top-N memories for context injection. Called by the hook. |
| `memory_store` | `content: str` | Store a new fact. Called by the agent. |
| `memory_search` | `query: str`, `limit?: int` | Semantic search. Called by the agent. |
| `memory_delete` | `memory_id: str` | *(optional)* Delete a specific memory. |
| `memory_clear` | *(none)* | *(optional)* Wipe all memories for the current user. |

The predefined memory skill references only these names. Every compliant adapter gets the same skill.

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
  "tool_sets": [{ "type": "dial-mcp", "dial_id": "memory-adapter-mem0" }],
  "hooks": [{
    "kind": "tool_call",
    "event": "on_request_start",
    "toolset_name": "memory-adapter-mem0",
    "tool_name": "memory_get_context",
    "arguments": {},
    "frequency": "append_if_changed",
    "refresh_condition": { "kind": "ttl", "ttl_minutes": 5 }
  }],
  "skills": ["memory"]
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
  }],
  "skills": ["memory-mem0"]
}
```

The skill (`memory-mem0`) must hardcode mem0's tool names. Different providers require different skill
variants. The LLM must also pass `"user_id": "{{dial_user_id}}"` correctly in write and search calls —
this relies on prompt engineering, not infrastructure.

#### Open problems in Approach B

1. **Template variable support doesn't exist yet** — code change required in QuickApps core.
2. **Skill is not portable** — each provider needs its own skill variant with its own tool names.
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
| Memory skill | Single portable skill | Per-provider variant |
| User isolation | Strong — enforced in adapter | Weak — trusts config |
| QuickApps code changes | None | Yes — template expansion in hooks |
| New provider support | Build an adapter (~150 lines) | Write skill variant + document config |
| Risk of user data leak | Low | Higher — wrong template = data leak |

---

## Model 2: Future Container Deployment

In the planned container model, each user session runs in its own isolated container: **one container =
one user × one QuickApp**. The user's DIAL storage bucket is mounted as a volume.

This changes everything.

### How the container model eliminates the multi-tenancy problem

A memory server running inside a per-user container is, by definition, serving exactly one user. It is
back to being the single-user tool it was designed to be. There is no shared state, no `user_id` needed
anywhere, no isolation machinery.

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

### Which providers fit the container model

Only file-based providers that can point their data directory at a configurable mount path are compatible.
Providers requiring external database services (PostgreSQL, Neo4j, FalkorDB) cannot participate — they
need a long-running server outside the container, which reintroduces multi-tenancy and defeats the purpose.

| Provider | Fits container model? | Data path config | Notes |
|---|---|---|---|
| **Official MCP Memory** | ✅ Yes | `MCP_MEMORY_FILE_PATH=/data/memory/graph.json` | Simplest option; no LLM needed; keyword search only |
| **basic-memory** | ✅ Yes | Vault path env var | Markdown notes; keyword search; no LLM needed |
| **mem0** (Chroma + SQLite) | ✅ Yes (non-default config) | `path: /data/memory/chroma` + `path: /data/memory/mem0.db` | Semantic search; LLM needed for fact extraction |
| **mem0** (default pgvector) | ❌ No | — | PostgreSQL lives outside the container |
| **Graphiti** | ❌ No | — | Neo4j / FalkorDB lives outside the container |
| **Zep** | ❌ No | — | Zep server has its own persistent storage |
| **mcp-obsidian** | ❌ No | — | Requires Obsidian desktop app — incompatible with headless containers |

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

2. **Standard tool names still help** — even without `user_id` concerns, a common tool interface
   (`memory_store`, `memory_search`, `memory_get_context`) means the same predefined skill works for all
   sidecar providers. Otherwise each provider needs its own skill variant.

3. **Startup latency** — the memory sidecar must be ready before QuickApps' first `on_request_start` hook
   fires. The container orchestrator needs a health-check / readiness gate before routing traffic.

---

## Recommendation: Sequencing

The container model is the simpler and cleaner long-term path. The multi-tenancy machinery in Model 1
(adapters or dynamic variables) becomes dead weight once containers ship.

| Option | Build now | Consequence when containers ship |
|---|---|---|
| **Wait for containers** | Nothing for external memory | Implement sidecar model once, cleanly |
| **Model 1 bridge now** | Adapter (A) or dynamic vars (B) | Multi-tenancy code becomes dead weight |
| **Define sidecar interface now, implement later** | Spec the config format + tool contract | Smooth handoff; no wasted code |

**Suggested path:** define the sidecar interface today (provider image, data path convention,
`memory_store` / `memory_search` / `memory_get_context` contract), implement Model 1 bridge only if
external memory is needed before containers ship. If the container timeline is within one or two
quarters, the bridge is unlikely to be worth the investment.

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

1. **Model 1 bridge: is it needed at all?** If containers ship within one or two quarters, building
   Approach A adapters or Approach B dynamic variables may not be worth the investment.

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
