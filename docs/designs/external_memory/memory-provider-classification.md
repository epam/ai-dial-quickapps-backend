# Memory Provider Classification

- **Status:** Draft
- **Related:** [External Memory Integration](external-memory-integration.md)

---

## Purpose

The external memory integration document established that there is no single generic solution for all
memory providers — isolation model, storage topology, and deployment assumptions differ too much across
providers. This document classifies known open-source memory providers into integration classes, with a
proposed generic solution for each class.

---

## Note on hooks and retrieval patterns

QuickApps' current memory implementation uses an `on_request_start` hook to proactively inject memories
into the conversation context before the first LLM turn. **This is not a requirement for external memory
integration.** Hooks are one optional pattern; the standard alternative is reactive retrieval — the LLM
calls memory tools (search, list) when it decides it needs past context, exactly as every other MCP
memory client (Claude Code, Cursor, etc.) works.

Both patterns are valid and can be mixed:

| Pattern | How it works | When to use |
|---|---|---|
| **Reactive** | LLM calls `memory_search` / `memory_get_context` when it needs context | Simpler integration; works with every provider out of the box |
| **Proactive (hook)** | `on_request_start` hook calls a retrieval tool and injects result before first turn | Guarantees relevant context is always present; requires a `list`/`get_context` tool on the provider |

The classification below does not assume proactive injection. Where relevant it notes whether the
provider's tool set supports it.

---

## Classification Dimensions

The classification uses four dimensions that determine the integration effort in QuickApps:

| Dimension | Why it matters |
|---|---|
| **Isolation model** | Determines what user-isolation work QuickApps must do |
| **Storage paradigm** | Determines how user data is persisted and whether DIAL bucket storage is usable |
| **Deployment topology** | Determines how the service is positioned relative to QuickApps |
| **LLM dependency** | Determines operator cost and operational complexity |

---

## Class 1 — File-Based Personal Providers

### Characteristics

- Store all data in local files or an embedded SQLite/file-based vector store
- Designed for **one user, one instance** — no multi-tenancy concept
- Zero external service dependencies — start/stop like any process
- Data path is configurable via an environment variable

### Providers

| Provider | Storage | Search | LLM needed? | MCP native? |
|---|---|---|---|---|
| **Official MCP Memory** | Single JSONL file (`memory.jsonl`) | Keyword (entity/observation text) | No | ✅ Yes |
| **basic-memory** | Markdown files + SQLite / Postgres | Hybrid (FastEmbed semantic + full-text) | No | ✅ Yes |
| **mem0** (Chroma + SQLite config) | Chroma vector DB + SQLite (both on local disk) | Semantic | Yes — LLM call on `add_memory` for fact extraction | ✅ Yes (via mem0 MCP server) |

### Fit with deployment models

| Model | Fit | Notes |
|---|---|---|
| **Model 1 — shared service (current)** | ✅ Viable today | QuickApps already has per-user access to DIAL file storage. The MCP server is configured to use a per-user DIAL bucket path — isolation is structural, not credential-based |
| **Model 2 — containers** | ✅ Natural fit | Same principle; the DIAL bucket is mounted as a volume. No `user_id` needed in either case |

The critical point: **DIAL already provides per-user isolated storage.** Any file-based MCP server that
accepts a configurable data path gets user isolation for free by pointing at the user's DIAL bucket. This
is exactly how QuickApps' own memory implementation (LanceDB) already works — it writes `memory.lance/`
into the user's DIAL bucket today, without containers.

### Generic solution

The MCP server is started (or addressed) with a data path that resolves to this user's DIAL file storage.
No `user_id` parameter, no adapter, no credential forwarding. The DIAL storage layer enforces isolation.

```
Request arrives (user A)
  ├── QuickApps resolves user A's DIAL bucket path
  ├── Starts / connects to MCP memory server with data_path = <user A's bucket path>
  │     (basic-memory vault, Official MCP Memory JSONL, mem0 Chroma dir, …)
  └── Agent calls memory tools reactively — or hook pre-injects if configured
```

Config sketch (same shape for any file-based provider):

```json
{
  "tool_sets": [{
    "type": "dial-mcp",
    "dial_id": "basic-memory",
    "env": { "BASIC_MEMORY_VAULT": "{{dial_bucket_path}}/memory/basic-memory" }
  }]
}
```

No adapter needed. No normalized tool contract required unless proactive hook injection is desired
(in which case the provider must expose a `list` / `get_context` tool).

### Open questions for this class

- How does QuickApps launch a per-user MCP server process (or route to a per-user instance)? Today,
  `dial-mcp` connects to a pre-deployed DIAL service — per-user process lifecycle is not yet modelled.
- mem0's LLM fact extraction: route through DIAL's LLM gateway or require separate endpoint config?
- If proactive hook injection is used: provider must expose a no-argument `list`/`get_context` tool;
  not all Class 1 providers have this (Official MCP Memory uses `read_graph` which returns the full graph).

---

## Class 2 — Multi-Tenant Server Services

### Characteristics

- A **single service instance** serves all users simultaneously
- User isolation is explicit: each API call carries a `user_id` / `namespace` parameter
- Backed by a persistent vector store (pgvector, Qdrant, proprietary) that partitions data per user
- Designed for server deployment — Docker Compose, Kubernetes, or a managed cloud

### Providers

| Provider | Storage | Search | LLM needed? | MCP native? | Multi-tenancy |
|---|---|---|---|---|---|
| **mem0** (default — pgvector / Qdrant) | PostgreSQL + pgvector **or** Qdrant | Semantic + BM25 hybrid | Yes — LLM call on `add_memory` for fact extraction | ✅ Yes | `user_id` / `agent_id` / `run_id` |
| **Supermemory** (self-hosted) | Proprietary (Ollama local or external LLM) | Hybrid (RAG + personalized memory) | Optional — local Ollama or external LLM | ✅ Yes (`https://mcp.supermemory.ai/mcp`) | `containerTag` isolation |

### Fit with deployment models

| Model | Fit | Notes |
|---|---|---|
| **Model 1 — shared service** | ✅ Natural fit | Designed for this. One deployed instance, `user_id` scopes each user's memories |
| **Model 2 — containers** | ❌ Wasteful | Running a fresh server-class database per container is over-engineered; use Class 1 instead |

### Generic solution (Model 1 — adapter pattern)

QuickApps connects through a thin **memory adapter** (one per provider), which reads the user identity
from the `X-DIAL-API-Key` header and injects it as `user_id` into every API call (see Approach A in the
integration doc). The adapter exposes a normalized tool contract identical across all providers:

| Tool | Parameters | Notes |
|---|---|---|
| `memory_store` | `content: str` | Core write tool — always required |
| `memory_search` | `query: str`, `limit?: int` | Core search tool — always required |
| `memory_get_context` | *(none)* | Optional — top-N memories without a query; needed only if proactive hook injection is configured |

No skill is required — the LLM understands the adapter's tools from their MCP descriptions, exactly as
in Claude Code and Cursor. A skill can be added optionally by operators who need to enforce specific
memory behaviors (e.g. "always save facts at end of every turn").

```
QuickApp agent
  └── memory_store / memory_search / memory_get_context
        ↓
  Class 2 Adapter  ← reads X-DIAL-API-Key → resolves user_id
        ↓
  mem0 / Supermemory backend  ← calls API with user_id
        ↓
  pgvector / Qdrant / proprietary storage  ← partitioned per user_id
```

### Open questions for this class

- mem0's LLM cost: every `add_memory` triggers ~1–2 s LLM inference + API charges. Should the adapter
  expose a `verbatim: true` mode that bypasses fact extraction?
- Supermemory self-hosted: requires either Ollama (local LLM) or external API. Operator must supply.
- Adapter maintenance: build one adapter per provider (~150 lines Python each). Org question: same repo
  as QuickApps, or separate adapters repo?

---

## Class 3 — Graph-Database Services

### Characteristics

- Memory is modelled as a **temporal knowledge graph** (entities + relations + time-validity windows)
- Requires a dedicated graph database (**Neo4j** or **FalkorDB**) as the storage engine
- Provides the richest retrieval semantics (graph traversal + semantic + BM25) but at high operational cost
- Multi-tenancy is possible but requires developer-managed namespace/group scoping in the graph

### Providers

| Provider | Storage | Search | LLM needed? | MCP native? | Multi-tenancy |
|---|---|---|---|---|---|
| **Graphiti** | Neo4j or FalkorDB (no file-based option) | Semantic + BM25 + graph traversal | Yes — LLM call for entity/relation extraction | ✅ Yes | Group-level scoping (developer-managed) |
| **Zep** (commercial) | Proprietary (built on Graphiti) | Same as Graphiti | Yes | ✅ Yes | Built-in (managed SaaS) |

### Fit with deployment models

| Model | Fit | Notes |
|---|---|---|
| **Model 1 — shared service** | ⚠️ Possible but complex | Shared Neo4j with group-scoped namespaces per user; developer must implement isolation |
| **Model 2 — containers** | ❌ No fit | Neo4j / FalkorDB cannot run per-user as a lightweight file-based sidecar |

### Generic solution

Class 3 is **not a candidate for a generic solution** in the same sense as Classes 1 and 2:

- The graph DB infrastructure cost is prohibitive for a lightweight integration.
- User isolation requires custom developer work at the graph level — no simple `user_id` parameter.
- The LLM dependency (entity extraction) adds latency and cost on every write.

**Recommendation:** Defer Class 3 integration until there is explicit operator demand. The adapter
pattern (Class 2) could technically wrap Graphiti, but the operational overhead undermines the value.

If Graphiti is ever needed, the integration path is: shared Graphiti instance → group/namespace scoping
per DIAL user → adapter layer exposing a consistent tool interface.

---

## Class 4 — Agent-Framework-Embedded Memory

### Characteristics

- Memory is an internal subsystem of a **full agent framework** — it cannot be detached and run as a
  standalone service
- The framework controls the LLM loop, tool calling, and memory management as a unified system
- Exposing memory as an external API is non-trivial or explicitly unsupported

### Providers

| Provider | Storage | Notes |
|---|---|---|
| **Letta / MemGPT** | Relational DB (PostgreSQL via alembic) | Memory blocks are part of the Letta agent runtime; no standalone memory MCP server |
| **LangMem** | Pluggable (InMemory / AsyncPostgresStore) | Library for LangGraph — memory is wired into the graph; no standalone service |
| **Agno** | Operator-configured | Built-in memory within the Agno agent platform; not extractable |

### Fit with deployment models

Neither model applies — these are **competing agent platforms**, not composable memory providers.

### Generic solution

**Out of scope.** Integrating these would mean replacing QuickApps' own orchestration with a third-party
framework, which is the inverse of the QuickApps design goal (operator chooses the memory backend, not
the entire agent stack).

---

## Class 5 — Document Retrieval / RAG Systems

### Characteristics

- Designed to **index and retrieve documents**, not to accumulate conversation-level memories
- Typically batch-ingested content (files, web pages, emails) rather than agent observations
- May overlap with memory conceptually but serve a different interaction pattern

### Providers

| Provider | Storage | Notes |
|---|---|---|
| **Kernel Memory** (.NET) | Azure AI Search, Postgres, Elasticsearch, Qdrant, Redis, local | Multi-tenancy via security filters; no MCP; ChatGPT plugin + Semantic Kernel integration |
| **OpenSearch ml-commons** | OpenSearch cluster | Full text + vector search over indexed documents; requires OpenSearch infrastructure |
| **mcp-apple-notes** | LanceDB (local) | Semantic search over a personal Apple Notes vault — personal RAG, not memory |

### Fit with deployment models

These providers can be wired into QuickApps as **knowledge base tool sets** (already supported via
`dial-mcp` or `mcp_http`), but they serve a different purpose from the memory hooks discussed in the
integration doc.

### Generic solution

**Out of scope for the memory integration pattern.** Use existing toolset configuration to connect
document retrieval systems. The `on_request_start` hook pattern does not apply here — retrieval should
be reactive (agent calls search when needed), not proactively injected at turn start.

---

## Summary

| Class | Examples | Model 1 fit | Model 2 fit | Generic solution |
|---|---|---|---|---|
| **1 — File-based personal** | Official MCP Memory, basic-memory, mem0 (Chroma) | ✅ Viable today | ✅ Natural | MCP server pointed at user's DIAL bucket path; isolation is structural |
| **2 — Multi-tenant server** | mem0 (pgvector), Supermemory | ✅ Natural | ❌ Wasteful | Adapter propagates user_id from DIAL auth header; no skill required |
| **3 — Graph-database** | Graphiti, Zep | ⚠️ Complex | ❌ | No generic solution; per-operator custom integration if ever demanded |
| **4 — Framework-embedded** | Letta, LangMem, Agno | ❌ | ❌ | Out of scope — competing agent platforms |
| **5 — Document RAG** | Kernel Memory, OpenSearch | n/a | n/a | Out of scope — use existing toolset config; not conversation memory |

---

## Implications for the Integration Roadmap

### Short term (current shared-service model)

**Both Class 1 and Class 2 providers are viable today.**

- **Class 1** (file-based): viable because QuickApps already has per-user DIAL bucket access, which is
  exactly the isolation mechanism these providers need. The main open question is how QuickApps starts or
  addresses a per-user MCP server process. This needs design work but no external infrastructure.
- **Class 2** (multi-tenant server): viable as a shared service with an adapter that propagates `user_id`
  from the DIAL auth header. Requires deploying the provider (e.g. mem0 with pgvector) separately.

For Class 1, no proactive hook injection is required — the LLM can call memory tools reactively. This
makes the initial integration even simpler: just expose the provider's MCP tools as a toolset. No skill
needed — the LLM reads the tools' native MCP descriptions, exactly as in Claude Code and Cursor.

### Long term (container model)

Class 1 providers become the natural default in the container model — the DIAL bucket is mounted as a
volume and the sidecar writes to it directly. Class 2 remains relevant for operators who run
shared-service deployments or require richer semantic search.

### Which provider to ship first

| Priority | File-based (Class 1) | Multi-tenant server (Class 2) |
|---|---|---|
| **First** | basic-memory — no LLM, Markdown files + SQLite, native MCP, hybrid search | mem0 (pgvector) — richest semantics, good self-hosting story |
| **Second** | Official MCP Memory — even simpler, keyword-only, zero dependencies | Supermemory — simpler API, optional local LLM |
| **Defer** | mem0 (Chroma) — LLM dependency adds operational complexity | Graphiti — high infra cost |
