# File-Based Memory Providers

- **Status:** Draft
- **Related:** [Memory Provider Classification](memory-provider-classification.md)

---

## Scope

This document covers memory providers that store data in local files and expose an MCP interface.
Their defining property: isolation is structural — point the provider at user A's directory and it is
physically incapable of reading user B's data.

QuickApps already uses this model for its own memory (LanceDB writes `memory.lance/` into the user's
DIAL bucket). All file-based external providers follow the same pattern.

---

## Providers

### 1. Official MCP Memory

**Maintained by:** Anthropic / MCP steering group  
**Repo:** `modelcontextprotocol/servers` — `src/memory/`  
**Runtime:** Node.js (`npx -y @modelcontextprotocol/server-memory`)  

**Storage:** Single JSONL file. Every entity, relation, and observation is one line.

**Data path config:**

```
MEMORY_FILE_PATH=/path/to/memory.jsonl   (default: ./memory.jsonl)
```

**MCP tools:**

| Tool | Key parameters | Description |
|---|---|---|
| `create_entities` | `entities[]` | Add entities with name, type, observations |
| `create_relations` | `relations[]` | Add directed edges between entities |
| `add_observations` | `entityName`, `contents[]` | Append facts to an existing entity |
| `delete_entities` | `entityNames[]` | Remove entities and their relations |
| `delete_observations` | `entityName`, `observations[]` | Remove specific facts |
| `delete_relations` | `relations[]` | Remove specific edges |
| `read_graph` | — | Return the **entire** graph as JSON |
| `search_nodes` | `query: str` | Keyword search across entity names, types, observations |
| `open_nodes` | `names[]` | Retrieve specific entities by name |

**Search type:** Keyword-only. `search_nodes` does substring matching on text fields — no embeddings,
no semantic similarity.

**LLM dependency:** None.

**Proactive injection:** `read_graph` returns the full graph. Suitable for `on_request_start` hook
only if the memory is small (entire graph is injected). No `get_context` / top-N tool exists.

**Notes:**
- Simplest possible implementation; good for basic use cases and prototyping.
- No concept of memory importance or recency — everything is equally ranked.
- Duplicate relations are silently skipped. Deleting non-existent items silently succeeds.
- Single file means the entire memory is read/written on every operation — does not scale to
  thousands of facts, but fine for personal conversation memory.

---

### 2. basic-memory

**Maintained by:** Basic Machines Co.  
**Repo:** `basicmachines-co/basic-memory`  
**Runtime:** Python (`uv tool install basic-memory`, then `basic-memory mcp`)  

**Storage:** Markdown files in a vault directory + SQLite index (`~/.basic-memory/` by default).
Files are human-readable and can be version-controlled.

**Data path config:**

```
BASIC_MEMORY_HOME=/path/to/vault     # overrides default ~/basic-memory
BASIC_MEMORY_CONFIG_DIR=/path/to/cfg # isolates config dir (useful per-user/per-process)
```

Projects can also be registered at startup via `basic-memory project add <name> <path>`.
The project is **selected at server startup** — it cannot be switched per-request in a running process.

**MCP tools (selected):**

| Tool | Description |
|---|---|
| `write_note` | Create or overwrite a Markdown note |
| `read_note` | Read a note by title or permalink |
| `edit_note` | Partial update to a note section |
| `delete_note` | Remove a note |
| `search` / `search_notes` | Hybrid search (semantic + full-text) |
| `recent_activity` | Most recently modified notes |
| `list_directory` | Browse vault structure |
| `build_context` | Follow `memory://` wikilinks recursively, building a context blob |
| `get_current_project` | Returns the active project name and path |

**Search type:** Hybrid — FastEmbed semantic embeddings (local, no external API) + SQLite full-text.
FastEmbed model (`bge-small-en-v1.5` by default) runs on CPU; first run downloads the model (~50 MB).

**LLM dependency:** None for storage. Embeddings are local (FastEmbed).

**Proactive injection:** `recent_activity` returns the most recently modified notes — usable as a
no-query "what's relevant now" injection point. Alternatively, `search` with a broad query.

**Notes:**
- The richest file-based option: semantic search + graph navigation + human-readable files.
- Notes structure aligns well with conversation memory (title = topic, body = observations).
- No built-in `user_id`; isolation is entirely via data path.
- FastEmbed model download adds ~1–3 s to first startup per installation.
- `build_context` is a powerful tool for multi-hop retrieval — the agent can traverse related notes.

---

### 3. Obsidian Vault (filesystem-direct MCP)

**Context:** An Obsidian vault is a plain directory of Markdown files with an optional `.obsidian/`
metadata folder. No Obsidian desktop app is required to read or write vault files — they are
ordinary files on disk.

Multiple MCP servers access vault files directly:

| Server | Repo | Notes |
|---|---|---|
| **obsidian-mcp** | `StevenStavrakis/obsidian-mcp` | 12 tools, vault path as CLI arg, no app needed |
| **seekstone** | — | "575× smaller payloads, no app required" |
| **vault-cortex** | — | Plugin-free, full vault access |

**Data path config** (obsidian-mcp as reference):

```
# path passed as CLI argument:
npx -y obsidian-mcp /absolute/path/to/vault
```

**MCP tools (obsidian-mcp):**

| Tool | Description |
|---|---|
| `read-note` | Read note contents |
| `create-note` | Create a new note |
| `edit-note` | Modify existing note |
| `delete-note` | Remove a note |
| `move-note` | Rename/relocate |
| `search-vault` | Full-text search across all notes |
| `add-tags` / `remove-tags` | Tag management |
| `list-available-vaults` | Multi-vault support |

**Search type:** Full-text (keyword). No semantic search in standard servers; some third-party servers
add embeddings.

**LLM dependency:** None.

**Proactive injection:** No direct "get recent / get all" tool in standard servers; would need a
`search-vault` call with an empty or broad query.

**Relationship to basic-memory:** Conceptually very similar — both are Markdown-based knowledge
graphs. Key differences:

| | basic-memory | Obsidian vault |
|---|---|---|
| Linking style | `memory://` permalinks | Wikilinks `[[Note Name]]` |
| Search | Hybrid (semantic + full-text) | Full-text only (standard servers) |
| Index | SQLite | File system only |
| Primary audience | AI memory tool | Human note-taking tool |
| Use case in QuickApps | Fresh conversation memory | Access to user's existing knowledge base |

**Notes:**
- Best fit when the user already maintains an Obsidian vault and wants the agent to read/write it.
- As a **from-scratch** conversation memory store, basic-memory is a better choice (richer search,
  AI-native structure).
- Vault path is a positional CLI argument, not an env var — requires different startup wiring than
  the other providers.

---

### 4. mem0 (local / Chroma + SQLite)

**Maintained by:** mem0ai  
**Repo:** `mem0ai/mem0`  
**Runtime:** Python library; no standalone MCP server for local mode (see notes)  

**Storage:** Chroma vector DB (local files) + SQLite for history. Paths configurable via Python config
or `MEM0_DIR` env var.

**Data path config:**

```python
config = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "memories",
            "path": "/path/to/chroma"    # local Chroma data dir
        }
    }
}
# SQLite history: controlled by MEM0_DIR env var (default ~/.mem0/)
# or set directly: memory = Memory(config=config, history_db_path="/path/to/mem0.db")
```

```
MEM0_DIR=/path/to/mem0-data    # controls history.db location
```

**MCP situation:** The official `mem0-mcp-server` package connects to the **mem0 cloud API** and
requires `MEM0_API_KEY`. There is no official standalone MCP server for the open-source local mode.
Using mem0 locally in QuickApps requires either:

- A **custom MCP wrapper** (~100 lines Python) that imports the `mem0` library and exposes tools
- Or running mem0's **self-hosted server** (Docker Compose with REST API) and connecting via HTTP —
  but that is the pgvector path (Class 2), not file-based

**Effective tools (if custom wrapper is written):**

| Tool | Parameters | Description |
|---|---|---|
| `add_memory` | `content: str` | Store; triggers LLM fact extraction |
| `search_memories` | `query: str`, `limit?: int` | Semantic search via Chroma |
| `get_memories` | — | List all memories |
| `delete_memory` | `memory_id: str` | Delete by ID |

**Search type:** Semantic (Chroma + embedding model). Default embedding: OpenAI `text-embedding-3-small`
(can be swapped to local model).

**LLM dependency:** Yes, **required on every write**. mem0 calls an LLM to extract structured facts
from raw text before storing. This cannot be disabled without forking the library. Adds ~1–2 s latency
and API cost per `add_memory`.

**Proactive injection:** `get_memories` lists all memories — usable as a no-query injection point.

**Notes:**
- Richest semantic memory of the four, but the LLM write dependency is a significant operational cost.
- No official local MCP server — requires custom wrapper to use file-based mode.
- For most QuickApps use cases, basic-memory provides comparable quality with no LLM dependency.
- Relevant if operators need mem0's specific fact-extraction behaviour (deduplication, contradiction
  resolution, structured entity graph alongside vector store).

---

## Summary Comparison

| | Official MCP Memory | basic-memory | Obsidian vault | mem0 (local) |
|---|---|---|---|---|
| **Storage** | Single JSONL file | Markdown + SQLite | Markdown directory | Chroma + SQLite |
| **Path config** | `MEMORY_FILE_PATH` | `BASIC_MEMORY_HOME` | CLI arg (`/path`) | `MEM0_DIR` / Python config |
| **Search** | Keyword | Hybrid (semantic + FTS) | Full-text | Semantic |
| **LLM on write** | No | No | No | Yes (required) |
| **Local embeddings** | No | Yes (FastEmbed, ~50 MB) | No | Optional (or OpenAI) |
| **Native MCP** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Needs custom wrapper |
| **`list`/`get_context` tool** | `read_graph` (full graph) | `recent_activity` | No standard tool | `get_memories` |
| **Runtime** | Node.js | Python (uv) | Node.js | Python |
| **Complexity** | Minimal | Low | Low | Medium + LLM setup |
| **Best for** | Prototyping, simple memory | General-purpose AI memory | Existing Obsidian users | Rich semantic memory |

---

## How providers are distributed and run

File-based providers are ordinary CLI tools published as packages — there is no source code to pull,
no build step, no custom deployment. They are installed into the QuickApps Docker image alongside
QuickApps itself, and the subprocess just calls the installed command by name.

```dockerfile
# Dockerfile — QuickApps image
FROM python:3.13

# basic-memory — Python package, installs `basic-memory` CLI
RUN uv tool install basic-memory

# Official MCP Memory — npm package, installs command in PATH
RUN npm install -g @modelcontextprotocol/server-memory

# obsidian-mcp
RUN npm install -g obsidian-mcp
```

After that, starting a provider is just:

```python
# MCP Python SDK — stdio_client spawns the process and speaks MCP over stdin/stdout
from mcp.client.stdio import stdio_client, StdioServerParameters

params = StdioServerParameters(
    command="basic-memory",          # CLI command installed in the image
    args=["mcp"],
    env={"BASIC_MEMORY_HOME": bucket_path}  # user's DIAL bucket path
)
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # agent calls tools through session normally
```

`stdio_client` spawns the subprocess, pipes stdin/stdout, and wraps everything in the MCP protocol.
This is exactly how Claude Desktop connects to MCP servers. No HTTP server, no DIAL deployment,
no wrapper needed — the provider runs as a local process.

**The user's bucket path** is resolved at request time via the existing DIAL client API:

```python
bucket_resp = await self.__dial_client.bucket.get_raw()
bucket_path = bucket_resp.appdata or bucket_resp.bucket
```

Isolation is structural: each subprocess gets a different `bucket_path` in its environment, so it
is physically incapable of reading another user's data.

**Constraint:** the set of supported providers is determined by what is installed in the Docker image.
An operator cannot add an arbitrary provider without a new image build. This is an intentional
tradeoff — providers are vetted and pre-packaged, not pulled from the internet at runtime.

---

## The Generic Integration Challenge

### Only one real problem: subprocess lifecycle

Given the above, the only remaining design question is how QuickApps manages the subprocess lifetime.

**Shared-service model (current):** QuickApps serves many users from one process. A per-user
subprocess pool is needed — keyed by `(user_id, toolset_name)`, with TTL eviction.

```
User A — first request:
  bucket_path = await dial_client.bucket.get_raw()
  pool.get("user-A", "basic-memory") → miss
  → spawn: basic-memory mcp  (env: BASIC_MEMORY_HOME=<bucket_path>)
  → ClientSession.initialize()
  → store in pool with TTL=10min

User A — next request (within TTL):
  pool.get("user-A", "basic-memory") → hit
  → reuse session, reset TTL

User A — idle > TTL:
  → close session → subprocess exits
  → evict from pool
```

**Container model (future):** one container = one user. The subprocess starts once when the
container starts and lives for its entire lifetime. No pool, no TTL, no keying by user_id —
just `stdio_client` started at toolset initialization and kept alive.

The same `SubprocessMCPToolSet` implementation works in both models — the difference is only
whether a pool is needed. In the container model the pool has exactly one entry that never expires.

---

## Generic Config Format (Sketch)

```json
{
  "tool_sets": [{
    "type": "subprocess-mcp",
    "name": "memory",
    "command": "basic-memory",
    "args": ["mcp"],
    "env": {
      "BASIC_MEMORY_HOME": "{{dial_bucket_path}}/memory/basic-memory"
    },
    "pool_ttl_minutes": 10
  }]
}
```

For Official MCP Memory:

```json
{
  "tool_sets": [{
    "type": "subprocess-mcp",
    "name": "memory",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
    "env": {
      "MEMORY_FILE_PATH": "{{dial_bucket_path}}/memory/memory.jsonl"
    },
    "pool_ttl_minutes": 10
  }]
}
```

Key points:
- `"type": "subprocess-mcp"` — new toolset type; spawns a local process via MCP stdio transport
  instead of connecting to a remote HTTP endpoint.
- `{{dial_bucket_path}}` — template variable resolved at request time from
  `dial_client.bucket.get_raw()`.
- `pool_ttl_minutes` — how long to keep the subprocess alive after the last request. In the
  container model this field is irrelevant (process lives for the container lifetime).
- No skill, no adapter, no tool renaming — provider runs as-is with its native tool names.

---

## Skills: are they needed at all?

In Claude Code and Cursor, these providers work without any skill. The LLM sees the tool names and
their MCP descriptions and decides autonomously when to call `write_note`, `search`, `read_graph`, etc.
This is the standard MCP memory experience — no external instruction file, no normalized contract.

QuickApps can work the same way: connect the provider as a toolset and let the LLM use the tools
based on their native descriptions. No skill required for the integration to function.

A skill adds value only when a specific memory workflow must be **enforced**, not just suggested:

| Behavior | Without skill | With skill |
|---|---|---|
| LLM calls search when it thinks it's needed | ✅ Works via LLM judgment | Same |
| LLM saves facts at its own discretion | ✅ Works via LLM judgment | Same |
| Always save facts at end of every turn | ❌ LLM may omit | ✅ Enforced by instruction |
| Always search memory before answering about user preferences | ❌ LLM may skip | ✅ Enforced |

**Recommendation:** ship without a skill by default. Operators who want tighter control can add a
skill variant themselves via the existing `skills` config field. No normalized tool contract is
required — each provider's native tool names and descriptions are sufficient.

This also eliminates the need for tool renaming, adapter layers, or any normalization infrastructure
for the file-based provider class.

---

## Open Questions

1. **DIAL bucket as local path:** How does `{{dial_bucket_path}}` resolve? Is the DIAL bucket always
   accessible as a local filesystem path, or does QuickApps sync files to/from DIAL storage? The
   answer determines whether subprocess-mcp is straightforward or requires a file-sync step.

2. **Subprocess pool implementation:** Should this be a new core feature in QuickApps, or a
   lightweight standalone module? What eviction policy (TTL, LRU, max size)?

3. **basic-memory startup model:** `basic-memory mcp` starts a stdio MCP server. Does QuickApps'
   existing MCP wiring support stdio transport, or only HTTP/SSE? If only HTTP, a shim is needed.

4. **mem0 local wrapper:** Is it worth writing the ~100-line custom MCP wrapper for mem0 local mode,
   or should mem0 integration always go through the Class 2 adapter (self-hosted server with pgvector)?

5. **Obsidian vault vs. basic-memory:** Obsidian vault MCP is the right tool when users bring their
   own vault. basic-memory is better for fresh-start AI memory. Should QuickApps support both, or
   treat Obsidian as a knowledge-base toolset (not a memory provider)?

6. **Optional skill shape:** If an operator wants to enforce specific memory behaviors via a skill,
   should QuickApps ship a default per-provider skill template, or leave it entirely to the operator?
