# Design: External Memory Provider Integration

- **Status:** Draft
- **Dependencies:**
  - [Config-Driven Hooks](config_driven_hooks.md)
  - [Memory Architecture](memory_architecture.md) *(feat/memory_desighn_doc)*

---

## Problem Statement

QuickApps has its own memory implementation (LanceDB + DIAL file storage). Operators currently have no way to
substitute a different memory backend — they're locked into the QuickApps-native implementation.

The goal is to let operators choose any open-source or self-hosted memory provider (mem0, Graphiti, Zep, Obsidian,
etc.) and wire it into a QuickApp without modifying application code.

---

## Design Goals

- An operator can configure an external memory backend by editing the app's JSON manifest only — no code changes.
- User isolation is preserved: each DIAL user's memories are separate, regardless of the backend.
- The predefined memory skill (system prompt instructions) works across backends without per-operator customisation,
  or at least a clear path to achieving that.
- Adding support for a new provider in the future requires minimal effort.

---

## Background: Current Memory Architecture

QuickApps memory today uses three interlocking mechanisms:

**1. MCP toolset** — the memory server is declared in `ApplicationConfig.tool_sets` as a `dial-mcp` entry.
The agent calls `store_memory` and `search_archive` tools during conversation.

**2. Hook-based context injection** — `on_request_start` hook calls a retrieval tool (`get_memories`) before
the first LLM turn and injects the result as a synthetic `(ASSISTANT tool_call / TOOL response)` pair into
the message history via `_ConfigDrivenToolCallHook`. TTL caching prevents redundant calls across turns.

**3. Skill** — a predefined Markdown skill tells the LLM which tools exist, when to use them, and what the
memory contract is.

**User isolation** is implicit: the memory MCP server authenticates via the user's DIAL API key, which scopes
all reads and writes to that user's DIAL file storage bucket. The tool call arguments carry no `user_id`
parameter — isolation is entirely handled by the auth layer.

```
QuickApp config
  └── tool_sets: [{ type: "dial-mcp", dial_id: "memory-server" }]
  └── hooks:    [{ event: "on_request_start", tool: "memory-server_get_memories" }]

Request arrives (DIAL API key = user A)
  → MCPToolInitializer connects to memory-server via DIAL (DIAL forwards user's key)
  → Hook fires: calls memory-server_get_memories → injects top-N memories into history
  → Agent runs, calls memory-server_store_memory / memory-server_search_archive as needed
  → Memory server reads/writes user A's DIAL bucket (enforced by auth)
```

---

## Background: External Memory Ecosystem

A survey of the major open-source memory providers and their MCP interfaces reveals three paradigms and no
shared standard.

### Tool interface comparison

| Provider | Write tool | Search tool | Context tool | User isolation |
|---|---|---|---|---|
| **mem0** (self-hosted) | `add_memory` | `search_memories` | `get_memories` | `user_id` param |
| **Graphiti** (Zep) | `add_memory`, `add_triplet` | `search_nodes`, `search_memory_facts` | `get_episodes` | `group_id` param |
| **Zep MCP** | *(read-only — write via SDK)* | `search_graph` | `get_user_context` | `user_id` param |
| **OpenMemory** (mem0) | `add_memories` | `search_memory` | `list_memories` | `user_id` in URL path |
| **Official MCP Memory** | `create_entities`, `add_observations` | `search_nodes` | `read_graph` | None (single-user) |
| **mcp-obsidian** | `append_content`, `patch_content` | `search` | `get_file_contents` | By folder convention |
| **basic-memory** | `write_note` | `search` | `build_context` | By project |

### Critical observation: MCP has no pre-turn injection

The MCP specification defines no mechanism for a server to inject context before each user turn. All memory
retrieval in Claude Code, Cursor, and Windsurf is **reactive** — the LLM calls memory tools when it judges
that past context might be relevant. This means those clients get no automatic memory injection.

**QuickApps' hooks system already does more than the MCP ecosystem standard.** The `on_request_start` hook
that calls a retrieval tool and synthetic-injects the result is a QuickApps-specific capability that external
clients don't have.

### User isolation in external providers

External providers use tool-parameter-level isolation: the caller must explicitly pass `user_id` (or
`group_id`) with every tool call. This is fundamentally different from QuickApps' current model, where user
identity travels through the DIAL auth layer and never appears in tool arguments.

This mismatch is the central technical challenge for any integration approach.

---

## Approach A: Memory Adapter Protocol

### Overview

Define a minimal standard tool contract that all memory backends must expose. For each backend, build a
thin adapter — a standalone MCP server that translates the standard interface to the backend's native API
and handles user identity propagation internally.

QuickApps always configures memory the same way, regardless of which backend is underneath.

```
QuickApp config (identical for all backends)
  └── tool_sets: [{ type: "dial-mcp", dial_id: "memory-adapter" }]
  └── hooks:    [{ tool: "memory-adapter_memory_get_context" }]
  └── skills:   ["memory"]   ← same predefined skill for all

DIAL routes the call to the adapter deployment
  └── Adapter receives request with DIAL user context in headers
  └── Adapter extracts user_id from headers
  └── Adapter calls backend (mem0 / Graphiti / Obsidian) with user_id
  └── Returns standardised response
```

### Standard Tool Contract

Three tools are the minimum viable contract:

| Tool | Parameters | Description |
|---|---|---|
| `memory_get_context` | *(none)* | Returns the top-N most important memories for context injection. Called by the hook at request start. |
| `memory_store` | `content: str` | Stores a new fact or observation. Called by the agent during conversation. |
| `memory_search` | `query: str`, `limit?: int` | Semantic search over memories. Called by the agent when retrieving specific past context. |

Optional / extended contract (provider-dependent):

| Tool | Parameters | Description |
|---|---|---|
| `memory_delete` | `memory_id: str` | Deletes a specific memory. |
| `memory_clear` | *(none)* | Wipes all memories for the current user. |

The predefined memory skill references only these five tool names. Operators using any compliant adapter get
the same skill for free.

### User Identity Propagation

Because the adapter is a DIAL deployment, DIAL injects user context into every HTTP call before it reaches
the adapter. The adapter reads identity from standard DIAL headers:

```
X-DIAL-API-Key: <user api key>        ← can be forwarded to backends that accept DIAL auth
api-key: <user api key>               ← alternative header
```

The adapter resolves the DIAL user identifier from these headers (via a lightweight call to DIAL Core's
`/v1/userinfo` or by decoding the JWT), then uses it as the `user_id` / `group_id` for all backend calls.
No `user_id` appears in tool arguments — the operator config carries no user-specific data.

> **Confirmed:** `DialMCPToolSet` forwards the user's DIAL API key in request headers to the upstream MCP
> server. The adapter can reliably extract user identity from these headers without any additional changes
> to QuickApps core.

### Example: mem0 Adapter

**Deployment:** mem0 self-hosted server runs as a Docker Compose stack (FastAPI + pgvector). The adapter is
a separate thin Python MCP server that wraps the mem0 REST API.

```
[ QuickApp agent ]
      │  MCP tools: memory_get_context / memory_store / memory_search
      ▼
[ Memory Adapter MCP Server ]  ← DIAL deployment "memory-adapter-mem0"
      │  reads X-DIAL-API-Key → resolves user_id
      │  calls mem0 REST API  (POST /memories, POST /search, GET /memories)
      ▼
[ mem0 self-hosted server ]    ← Docker: FastAPI + pgvector + LLM for extraction
      │  stores embeddings per user_id
      ▼
[ pgvector database ]
```

**Adapter implementation sketch (Python, ~100 lines):**

```python
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("mem0-adapter")
MEM0_URL = os.environ["MEM0_URL"]  # e.g. http://mem0:8888

def get_user_id(ctx) -> str:
    # Extract from DIAL-forwarded header
    return ctx.request_context.headers.get("x-dial-api-key", "anonymous")

@mcp.tool()
async def memory_get_context(ctx) -> str:
    user_id = get_user_id(ctx)
    r = await httpx.get(f"{MEM0_URL}/memories", params={"user_id": user_id, "limit": 20})
    return format_memories(r.json()["results"])

@mcp.tool()
async def memory_store(content: str, ctx) -> str:
    user_id = get_user_id(ctx)
    await httpx.post(f"{MEM0_URL}/memories", json={
        "messages": [{"role": "user", "content": content}],
        "user_id": user_id
    })
    return "Stored."

@mcp.tool()
async def memory_search(query: str, ctx, limit: int = 5) -> str:
    user_id = get_user_id(ctx)
    r = await httpx.post(f"{MEM0_URL}/search", json={
        "query": query, "filters": {"user_id": user_id}, "limit": limit
    })
    return format_memories(r.json()["results"])
```

**QuickApp config (same for every operator using mem0):**

```json
{
  "tool_sets": [
    { "type": "dial-mcp", "dial_id": "memory-adapter-mem0" }
  ],
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "memory-adapter-mem0",
      "tool_name": "memory_get_context",
      "arguments": {},
      "frequency": "append_if_changed",
      "refresh_condition": { "kind": "ttl", "ttl_minutes": 5 }
    }
  ],
  "skills": ["memory"]
}
```

**Infrastructure requirements:**
- mem0 self-hosted: Docker Compose (FastAPI + pgvector + OpenAI-compatible LLM endpoint)
- mem0 adapter: single Docker container (~100 lines Python)
- Both registered as DIAL deployments in DIAL Core configuration

**Important caveat — mem0's LLM dependency:** mem0 runs its own LLM inference pass on every `add_memory`
call to extract structured facts from raw text. This means the mem0 deployment requires an LLM API key
(OpenAI, Anthropic, or a self-hosted Ollama/vLLM endpoint). This is an operational cost the operator must
plan for. It cannot be eliminated without forking mem0.

### Example: Obsidian Adapter

> **Warning:** Obsidian is a desktop application. The Local REST API plugin runs an HTTPS server inside
> the Obsidian desktop process on `127.0.0.1:27124`. This means the plugin only works while the Obsidian
> app is open on a machine, making it **unsuitable for server-side or multi-user production deployments**.
>
> The Obsidian example below is useful for:
> - Individual developer workflows (one person, one machine)
> - Prototyping / proof-of-concept
> - Understanding the integration pattern before choosing a production backend
>
> For a production note-based memory backend consider **basic-memory** instead — it stores notes as plain
> Markdown files without requiring a running desktop application.

**Concept:** memories live as Markdown files in an Obsidian vault, organised per user under
`/agent-memory/{user_id}/`. The adapter translates the standard contract to Obsidian's Local REST API.

```
[ QuickApp agent ]
      │  MCP tools: memory_get_context / memory_store / memory_search
      ▼
[ Memory Adapter MCP Server ]  ← wraps Obsidian Local REST API
      │  resolves user_id from DIAL headers
      │  user namespace: /agent-memory/{user_id}/
      ▼
[ Obsidian app (desktop) ]     ← Local REST API plugin on 127.0.0.1:27124
      ▼
[ Obsidian vault ]             ← plain .md files on disk
```

**Adapter tool mapping:**

| Standard tool | Obsidian REST API call |
|---|---|
| `memory_get_context` | `GET /vault/agent-memory/{user_id}/context.md` (a curated summary note) |
| `memory_store` | `POST /vault/agent-memory/{user_id}/{timestamp}.md` (new note per fact) |
| `memory_search` | `POST /search/simple/` with `contextLength` + filter by path prefix |

**Key limitations:**
1. **Desktop dependency** — Obsidian must be running. Any server restart, sleep, or crash stops memory access.
2. **No semantic search** — Obsidian's built-in search is full-text keyword only. Semantic retrieval requires
   the Smart Connections plugin (local embedding model). Without it, `memory_search` returns keyword matches
   only, which degrades recall significantly.
3. **No transactional writes** — concurrent writes from multiple agents to the same vault are unsafe.
4. **User isolation by convention** — the adapter enforces folder-per-user, but Obsidian itself has no
   access control; a misconfigured adapter could read or write another user's notes.

### Adapter Fit for the Future Container Model

When QuickApps moves to per-quickapp containers, the memory adapter pattern fits naturally as a sidecar:

```
┌─────────────────────────────────────────────┐
│  QuickApp container                         │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │  quickapps-     │  │  memory-adapter  │  │
│  │  backend        │◄─┤  (sidecar)       │  │
│  └─────────────────┘  └────────┬─────────┘  │
│                                │             │
│                       ┌────────▼─────────┐  │
│                       │  storage mount   │  │ ← user's DIAL bucket
│                       │  /data/memory/   │  │
│                       └──────────────────┘  │
└─────────────────────────────────────────────┘
```

In this model, user isolation is at the container level — the sidecar only ever sees one user's data because
it's mounted from that user's storage. The adapter doesn't need to pass `user_id` to the backend at all;
the backend reads from the mounted path which is already scoped. This is architecturally the cleanest
long-term solution.

### Open Problems in Approach A

1. **User identity header forwarding** — needs verification that `DialMCPToolSet` connections forward the
   DIAL API key to the upstream MCP server. If not, a mechanism must be added.
2. **Adapter maintenance burden** — each new provider needs a new adapter. Adapters are small (~100–200
   lines each) but still need to be built, tested, deployed, and versioned.
3. **Where do adapters live?** — a separate repository (`ai-dial-memory-adapters`), or bundled with
   QuickApps? A monorepo of adapters is probably the right call, but it's an organisational decision.
4. **mem0's LLM dependency** — mem0 calls an LLM on every write to extract facts. This adds latency (~1–2s
   per store operation) and cost. Operators must supply an LLM endpoint; mem0 cannot run standalone.
5. **Graphiti/Zep dependency** — Graphiti requires Neo4j or FalkorDB as the graph database backend.
   Adds operational complexity compared to mem0's pgvector.

---

## Approach B: Dynamic Variable Injection in Hooks

### Overview

No adapter layer. QuickApps connects directly to any MCP-compatible memory server. The hooks configuration
is extended to support template variables that are resolved at request time from the DIAL request context.
Operators configure which provider-specific tools play which role (context injection, write, search).

```
QuickApp config (provider-specific)
  └── tool_sets: [{ url: "http://mem0/mcp", allowed_tools: [...] }]
  └── hooks:    [{ tool: "mem0_get_memories", arguments: {"filters": {"user_id": "{{dial_user_id}}"}} }]
  └── skills:   ["memory-mem0"]   ← provider-specific skill variant

Request arrives
  → Hook resolves {{dial_user_id}} → "user-abc-123"
  → Calls mem0_get_memories(filters={user_id: "user-abc-123"})
  → Injects result into history
```

### Proposed Hook Config Extension

Add template variable support to `ToolCallHookConfig.arguments`. Variables are resolved from the current
request context before the tool is called.

**Available variables:**

| Variable | Value |
|---|---|
| `{{dial_user_id}}` | Authenticated DIAL user identifier |
| `{{app_id}}` | The QuickApp's DIAL deployment ID |
| `{{session_id}}` | Current conversation session ID |

**Change in `_ConfigDrivenToolCallHook`:**

```python
# Before resolving tool arguments, expand template variables
def _resolve_arguments(self, arguments: dict, context: RequestContext) -> dict:
    variables = {
        "dial_user_id": context.user_id,
        "app_id": context.app_id,
        "session_id": context.session_id,
    }
    return json.loads(
        Template(json.dumps(arguments)).substitute(variables)
    )
```

This is a minimal, backwards-compatible change: existing configs without `{{...}}` are unaffected.

### Example: mem0 Direct

**Deployment:** mem0 self-hosted server, registered as a DIAL deployment or accessed directly via HTTP MCP.

**QuickApp config:**

```json
{
  "tool_sets": [
    {
      "type": "mcp_http",
      "url": "http://mem0-server:8888/mcp",
      "name": "mem0",
      "allowed_tools": ["add_memory", "get_memories", "search_memories", "delete_memory"]
    }
  ],
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "mem0",
      "tool_name": "get_memories",
      "arguments": {
        "filters": { "user_id": "{{dial_user_id}}" },
        "limit": 20
      },
      "frequency": "append_if_changed",
      "refresh_condition": { "kind": "ttl", "ttl_minutes": 5 }
    }
  ],
  "skills": ["memory-mem0"]
}
```

**Provider-specific skill (`config/predefined/skills/memory-mem0/SKILL.md`):**

```markdown
## Memory

You have access to a persistent memory system. Use it to remember facts about the user across conversations.

### Tools

- **`mem0_add_memory`** — Store a new fact. Call this when the user states a preference, shares personal
  information, or explicitly asks you to remember something.
  Arguments: `messages` (array of {role, content}), `user_id` (use `{{dial_user_id}}`).

- **`mem0_search_memories`** — Search for relevant past memories before answering questions that may depend
  on prior context.
  Arguments: `query` (string), `filters: {user_id: "{{dial_user_id}}"}`.

- **`mem0_get_memories`** — List all stored memories. Use sparingly; prefer `search_memories` for retrieval.
```

> **Problem:** The skill must hardcode the tool names from the provider (`mem0_add_memory`, etc.) and still
> contains `{{dial_user_id}}` references that the LLM must interpolate correctly. This means the skill is
> not reusable across providers, and the operator must either write a custom skill or choose from a small
> library of provider-specific skills.

### Example: Obsidian Direct (mcp-obsidian)

The standalone `mcp-obsidian` MCP server (MarkusPfundstein/mcp-obsidian) wraps the Obsidian Local REST API
and exposes 7 tools: `list_files_in_vault`, `list_files_in_dir`, `get_file_contents`, `search`,
`patch_content`, `append_content`, `delete_file`.

**QuickApp config:**

```json
{
  "tool_sets": [
    {
      "type": "mcp_http",
      "url": "http://obsidian-mcp:8000",
      "name": "obsidian",
      "allowed_tools": ["search", "append_content", "get_file_contents"]
    }
  ],
  "hooks": [
    {
      "kind": "tool_call",
      "event": "on_request_start",
      "toolset_name": "obsidian",
      "tool_name": "get_file_contents",
      "arguments": {
        "filepath": "agent-memory/{{dial_user_id}}/context.md"
      },
      "frequency": "append_if_changed",
      "refresh_condition": { "kind": "ttl", "ttl_minutes": 10 }
    }
  ],
  "skills": ["memory-obsidian"]
}
```

The hook injects a single "context note" per user. The LLM calls `obsidian_append_content` to write new
facts to the user's memory file, and `obsidian_search` to find past notes.

**Limitations (same as in Approach A):** desktop dependency, no semantic search, no transactional safety,
folder-based isolation only.

### Open Problems in Approach B

1. **Template variable support doesn't exist yet** — `_ConfigDrivenToolCallHook` resolves static arguments
   only. Implementing `{{...}}` expansion is a code change in QuickApps core.

2. **Skill is not portable** — every provider has different tool names. The operator must either write a
   custom skill or pick from a growing library of provider-specific skill variants. If the tool names in
   the skill drift from the actual toolset config, the agent will hallucinate tool calls.

3. **mem0's `user_id` argument is nested** — the `get_memories` and `search_memories` tools accept
   `user_id` inside a `filters` object: `{"filters": {"user_id": "..."}}`. The template must be expanded
   inside a nested JSON structure, which requires careful implementation (simple string substitution risks
   JSON injection if the user_id contains special characters).

4. **No enforcement of user isolation at the adapter level** — the memory server trusts whatever `user_id`
   the caller sends. A misconfigured hook with a wrong `user_id` value silently accesses the wrong user's
   data. Approach A centralises this concern in the adapter where it can be validated against the DIAL auth
   headers.

5. **Providers without `user_id` parameter** — OpenMemory bakes `user_id` into the SSE URL path
   (`/mcp/{client}/{user_id}/sse`), not into tool arguments. To support it, URL-level templating would also
   be needed in the toolset config, e.g. `"url": "http://openmemory/mcp/quickapps/{{dial_user_id}}/sse"`.
   This is a bigger config surface change.

6. **Write path requires LLM cooperation** — the hook handles context injection, but the `store` and
   `search` tools are called only when the LLM decides to. With provider-specific tool names in the skill,
   the LLM may fail to use them correctly if the names are unfamiliar. The predefined standard names in
   Approach A (`memory_store`, `memory_search`) are cleaner for prompting.

---

## Approach Comparison

| Dimension | Approach A: Adapter Protocol | Approach B: Dynamic Variables |
|---|---|---|
| Operator config complexity | Low — identical for all backends | Medium — different per provider |
| Memory skill | Single portable skill | Per-provider skill variants |
| User isolation enforcement | Strong — adapter validates against DIAL headers | Weak — trusts operator config |
| Code changes in QuickApps | None (today) / adapter header forwarding (TBD) | Yes — template variable expansion in hooks |
| New provider support | Build a new adapter (~150 lines) | Write a new skill variant + document config |
| Container model fit | Excellent — adapter becomes a sidecar with mounted storage | Good — works but user isolation moves to volume-mount level |
| Blast radius of mistakes | Low — isolation centralised in adapter | Higher — wrong `user_id` template = data leak |
| mem0 LLM dependency | Present (unavoidable without fork) | Present (same) |
| Obsidian production use | Not recommended (desktop dependency) | Not recommended (same reasons) |

---

## Out of Scope

- **Building the actual memory backends** — mem0, Graphiti, etc. are external projects. This design is
  about the QuickApps integration layer only.
- **UI for memory management** — viewing, editing, and deleting memories from the DIAL UI is covered by the
  main memory design doc.
- **Approach C (storage-native)** — wrapping providers at the storage layer requires forking or deep
  customisation of external projects. Ruled out.
- **Zep Cloud** — managed SaaS; does not fit the self-hosted operator model.
- **Letta / MemGPT** — Letta is an agent framework, not a memory-as-a-service backend. Its memory tools are
  internal to its own agent runtime. Not a drop-in memory provider for QuickApps.

---

## Open Questions for Discussion

1. **Which approach is primary?** A and B are not mutually exclusive — A could be the "official" path for
   supported providers, B could be an escape hatch for operators who want to plug in anything MCP-compatible.

2. ~~**Does `DialMCPToolSet` forward the user's DIAL API key to the upstream MCP server?**~~ **Resolved** —
   confirmed yes. Approach A's user isolation model is sound as described.

3. **Where do adapters live?** Separate repo (`ai-dial-memory-adapters`)? Bundled in this repo? As example
   Docker images in the DIAL marketplace?

4. **How many providers to support at launch?** mem0 is the most MCP-mature and production-ready. Graphiti
   is interesting for knowledge-graph use cases. Obsidian is developer/personal only. Suggestion: mem0 as
   the reference implementation for v1.

5. **mem0's LLM cost**: every `add_memory` call runs an LLM inference to extract facts. Is this acceptable
   for operators? Should the adapter offer a `infer=false` mode (stores verbatim text, skips extraction)?

6. **Container model timeline**: once per-user containers land, the sidecar pattern for Approach A becomes
   much cleaner (no `user_id` needed at all — isolation is at mount level). Does it make sense to defer
   memory provider integration until after the container model is in place?
