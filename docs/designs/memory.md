# Design: [Title]

**Status:** Draft | Approved | Implemented | Superseded

## Problem Statement

What is broken, missing, or inadequate today? Describe the current behavior and why it's a problem.
Focus on observable symptoms (bugs, duplication, semantic mismatches) rather than jumping to solutions.

## Design Goals

Address:
- How AI agents interact with memory?
- How UI clients interact with memory?
- What is memory in terms of DIAL entities?
- How memory is stored in DIAL file storage?
- How user can view and manage memory?
- How memory is scoped?
- How user provides consent for saving information to memory?
  - user, user-app, smth else?
- How memory is structured?
  - Facts, their lifecycle
- How the system can be adjusted what is saved to memory and what is not?
- How can we later improve and evolve the system?

## Use cases

What is DIAL memory for? What are the use cases we want to support?

### Use case 1: Basic facts about the user and their preferences

We'd like the system to remember basic facts about the user, such as their:
- name
- age
- location
- time zone
- interests
- preferencies

That will be useful for the personalization if the experience in interactions with AI Agents.

Certain attributes may be available via the user profile. In that case the system should be able to pull that information
and take it into account.

However, certain attributes won't be there, but can be extracted from what user tells the system in conversations.
For example, if the user says `Provide all code examples in Python`, the system can extract that the user prefers
Python and save it as a fact in memory.

### Use case 2: Application-specific preferences and facts

The system should be able to remember facts and preferences related to particular applications. For example, if the user says
`If you generate code - generate code in Python` - the system should be able to extract that preference and apply it when the user asks to generate code.

Another use-case: some important or key facts found during the conversation, or some restrictions that should be applied
when working with particular application. In such cases agent should be able to react to that and save that information in memory for future interactions.

### Use case 3: Direct ask from user to save some information in memory

The system should be able to save information in memory based on direct ask from user. For example, if the user says
`Remember that I always prefer Python for code examples`, the system should be able to extract that preference and save
it as a fact in memory.

### Use case 4: Workflows for particular applications - OUT OF SCOPE

The system should be able to remember user's workflows in working with particular application. For example, if the user says
"Follow this process when you work on this task", the system should be able to extract the process and use it in future
interactions.

### Use case 5: Adjust what is saved in memory and what is not

System administrators and application administrators should be able to adjust what information is saved in memory and
what is not. For example, they may want to exclude certain types of information from being saved in memory for privacy reasons.

---

## Proposed Design

The core of the document. Break this into subsections that map to the distinct concerns or components being changed.

For each concern, cover:

- **What** is being introduced or changed (field, class, method).
- **Owner** — which component is responsible for this behavior.
- **Semantics** — how it works at runtime.
- **Change** — what specifically changes relative to the current codebase.


### Concern 1: How AI agents interact with memory?

Agents interact with memory through two complementary mechanisms: a **memory skill** that governs decision-making, and **MCP tools** that perform the actual read/write operations.

#### Memory Skill

A skill file (`config/predefined/skills/memory/SKILL.md`) is loaded by the existing `AgentSkillsProvider` + `PredefinedContentProvider` pipeline — no changes to the skills loader are needed. It instructs the agent **when** and **how** to use the memory tools:

- **`store_memory` with `memory_type=core`** — when the user states a permanent fact, corrects a fact, or establishes a preference. Facts are always appended (never overwritten); retrieval handles context disambiguation.
- **`store_memory` with `memory_type=episodic`** — when a significant decision, bug fix, or repeatable workflow is established during the session and should be recallable in a future one.
- **`search_archive`** — when the user references past events ("last time", "remember when") and the answer is not in the current context window.
- **Never store**: intermediate debug steps, general knowledge, or file contents (that is RAG's job).

Importance guide for core facts stored by the agent:

| Importance | Meaning |
|------------|---------|
| 0.9 + | Universal facts (name, language preference) — always injected regardless of topic |
| 0.7 – 0.9 | Project/context-specific facts — injected when contextually relevant |
| < 0.7 | Low-priority hints |

#### MCP Tools

The Memory MCP server is deployed as a **DIAL application** with an MCP endpoint, registered in DIAL Core's application schema (enabled by [epam/ai-dial-core#1382](https://github.com/epam/ai-dial-core/issues/1382), already shipped). This is a no-code, admin-level configuration — no changes to quickapps-backend code are needed to wire the tools.

Because the Memory MCP server is a proper DIAL application, it participates in the same access-control, routing, and observability as any other DIAL entity. A single deployed instance can serve multiple QuickApps simultaneously.

| Tool | Description | Arguments |
|------|-------------|-----------|
| `store_memory` | Append a new memory row. Strictly append-only — never overwrites. | `content: str`, `memory_type: Literal["core","episodic"]`, `context: str`, `importance: float` |
| `search_archive` | Search episodic history. Use when user references past events not in the current context. | `query: str` |

**Append-only invariant**: if the agent stores "project-alpha is in Python" and later "project-alpha is in Rust", both rows coexist. Retrieval surfaces the contextually appropriate one. If the model sees two conflicting facts injected for the same query, it asks the user to clarify — which is the correct behavior.


### Concern 2: How UI clients interact with memory?

UI clients (e.g. DIAL Chat, custom frontends) interact with memory through **custom REST API routes** exposed by the Memory MCP server. Memory creation is intentionally excluded — only agents create memories via `store_memory`. The UI role is limited to **read, update, and delete**.

#### Why no Create from UI?

Facts stored in memory carry semantic metadata (`importance`, `context`, `embedding`) that the agent computes at storage time based on conversation context. A UI form cannot reproduce that reasoning reliably. The agent is the only writer.

#### REST Routes

The Memory MCP server exposes management routes alongside its MCP endpoint. Per [epam/ai-dial-core#1382](https://github.com/epam/ai-dial-core/issues/1382) (already shipped), DIAL applications can declare custom HTTP routes in their application schema — these are routed through DIAL Core and subject to the same access control as any other DIAL entity.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/memory?path=` | List all memory rows for the given scope path. Supports filtering by `memory_type`. |
| `GET` | `/memory/{id}?path=` | Get a single memory row by ID. |
| `PATCH` | `/memory/{id}` | Update `content`, `importance`, or `context` of an existing row. Embedding is re-computed on update if a vector model is configured. |
| `DELETE` | `/memory/{id}?path=` | Hard-delete a memory row. |

The `path` parameter determines the memory scope (app-scoped or user-scoped) — the same path-agnostic contract used by the MCP tools and the HTTP management API.

#### Access Control

Routes are proxied through DIAL Core. The caller's identity is resolved by DIAL Core and forwarded to the Memory MCP server via a header. The server validates that the requested `path` belongs to the authenticated user — cross-user access is rejected.

#### Relationship to Concern 5

The route design here is the **server contract**. How the UI surfaces these operations (memory panel, inline editing, bulk delete) is addressed in Concern 5.


### Concern 3: What is memory in terms of DIAL entities?

Memory maps to three distinct DIAL entities: a shared application, per-user storage objects, and a per-user config object.

#### 3.1 Memory MCP Server — DIAL-native application (single instance)

The Memory MCP server is registered in DIAL Core as a **DIAL-native application without a schema** — a single deployment shared across all users. There is no per-user or per-QuickApp instance. User isolation is achieved entirely through storage paths, not through separate server instances.

The application registers three interfaces in DIAL Core:

| Interface | Purpose |
|-----------|---------|
| MCP endpoint | Agent-callable tools (`store_memory`, `search_archive`) — Concern 1 |
| Custom REST routes | User-facing CRUD API for memory rows — Concern 2 |
| `viewerUrl` | Memory management UI shown inside DIAL Chat — Concern 5 |

A full **Application Type** (schema-rich, with no-code wizard) is intentionally not used. Memory is infrastructure — users do not create memory instances. The `viewerUrl` gives the necessary UI footprint without the schema overhead.

#### 3.2 Per-user memory data — DIAL file storage objects

Each user's memory is stored as a **LanceDB table** (`memory.lance/`) inside their personal bucket in DIAL file storage. The server never touches another user's bucket.

| Scope | Path in DIAL file storage |
|-------|--------------------------|
| App-scoped memory | `users/{user_id}/apps/{quickapp_id}/memory/memory.lance/` |
| Global user memory | `users/{user_id}/memory/memory.lance/` |

These objects are standard DIAL file storage entries — no special DIAL entity type. The Memory MCP server syncs them down before read/write and syncs up after write, keeping the server stateless.

#### 3.3 Per-user memory config — DIAL file storage object

Each user also has a **memory config file** stored in their bucket:

```
users/{user_id}/memory/config.json
```

This config controls memory behavior for that specific user — what categories of information may be saved, consent flags, scope enablement, and future adjustment knobs. It is readable and writable via the viewer UI (Concern 5) and constrains what the Memory MCP server will accept at write time (Concern 9).

Admins can define deployment-level defaults and hard restrictions that take precedence over the per-user config — see Concern 9.


### Concern 4: How memory is stored in DIAL file storage?

DIAL does not require a centralized database. The Memory MCP server follows the same principle — all persistent state lives in DIAL file storage (cloud-agnostic BLOB). The server itself is fully stateless.

#### 4.1 BLOB storage — LanceDB tables and config

DIAL file storage is cloud-agnostic: AWS S3, Google Cloud Storage, Azure Blob Storage, or a local file system for self-hosted deployments. The Memory MCP server stores two types of objects per user in DIAL file storage:

| Object | Path | Description |
|--------|------|-------------|
| Memory table | `users/{user_id}/apps/{quickapp_id}/memory/memory.lance/` | App-scoped LanceDB table (core facts + episodic history) |
| Memory table | `users/{user_id}/memory/memory.lance/` | Global user-scoped LanceDB table |
| User config | `users/{user_id}/memory/config.json` | Per-user memory config (consent, scope flags, adjustment knobs) |

No external database is required. All state is in BLOB storage and the server can be restarted or scaled without data loss.

#### 4.2 LanceDB sync pattern — stateless server

LanceDB operates on local files. Since BLOB storage is not a local filesystem, the Memory MCP server uses a **sync-down / sync-up** pattern:

1. **Before read or write**: sync the relevant `memory.lance/` directory from BLOB to a local `/tmp` cache.
2. **Perform the LanceDB operation** (query or append) locally.
3. **After write**: sync the modified `memory.lance/` directory back up to BLOB storage.

This keeps the server stateless — any instance can handle any request by syncing from BLOB first.


### Concern 5: How user can view and manage memory?

Memory management is surfaced to the user as a **dedicated section in DIAL Chat's settings/configuration area** — not inside a conversation. This section has two responsibilities:

1. **Memory config** — user-facing controls for their personal `config.json` (scope enablement, consent flags, and other adjustment knobs defined in Concern 9).
2. **Memory browser** — a UI to read, update, and delete individual memory rows, backed by the REST routes defined in Concern 2.

The section is rendered via the `viewerUrl` registered on the Memory MCP server DIAL application (Concern 3). DIAL Chat loads it as an embedded view within the settings panel.

> Detailed UI design (layout, components, interaction flows) is deferred to a separate UI design pass.


### Concern 6: How memory is scoped?

**Scope is defined entirely by the path to the `memory.lance/` file in DIAL file storage.** The Memory MCP server is path-agnostic — it never interprets what a path means semantically. Scope resolution is the sole responsibility of the caller (quickapps-backend).

| Scope | Path | Computed by |
|-------|------|-------------|
| App-scoped | `users/{user_id}/apps/{quickapp_id}/memory/` | quickapps-backend combines user identity + QuickApp ID |
| Global user | `users/{user_id}/memory/` | quickapps-backend resolves user identity only |

This means:
- Adding a new scope requires no changes to the Memory MCP server — only the caller changes how it computes the path.
- There is no cross-user sharing at any scope level. Every path is rooted under the user's own folder.
- When both scopes are active, quickapps-backend calls the server twice (once per path), then merges and deduplicates results by `id` before injection.


### Concern 7: How user provides consent for saving information to memory?

Two options are on the table:

| Option | When consent is given | UX cost | Risk |
|--------|-----------------------|---------|------|
| **One-time** | User enables memory in settings (Concern 5). From that point the agent stores silently. | Low — one action, no interruptions. | User may be surprised by what gets stored. |
| **Per-store** | Agent asks the user for confirmation each time it decides to call `store_memory`. | High — interrupts the conversation every time. | None, but poor UX at scale. |

> Decision deferred. Both options are viable; the right choice depends on regulatory requirements and UX research. The per-user `config.json` (Concern 3.3) is the natural place to store the consent flag whichever option is chosen.


### Concern 8: How memory is structured? (Facts, their lifecycle)


### Concern 9: How the system can be adjusted about what is saved to memory and what is not?


### Concern 10: How can we later improve and evolve the system?


...

---

## Secondary Fixes

Smaller changes that naturally follow from the core design but are not the main focus.
Each should be a self-contained subsection with a brief description and the fix.

---

## Out of Scope

Items that were considered but intentionally deferred. For each, briefly explain **why** it's deferred
and what would be needed to address it in a future design pass.

### Search past conversations

Functionality to search past conversation for the info that was not saved in memory is out of scope for now.

The only thing that is searched - memory.

### Preferences in working with particular applications

This concern should be better addressed by introduction of extended support for agents skills: user may be able to dynamically
create and update skills, and reuse them across different agents.

---

## Configuration / Usage Examples

Concrete examples showing how the new design is used in practice.
Use tables, config snippets, or step-by-step walkthroughs — whatever makes the patterns clearest.

---

## Migration

### Breaking changes

Describe any breaking changes and the backward-compatibility strategy (warnings, coercion, migration scripts).

### Non-breaking changes

Note changes that are safe by default and require no action from existing users.

## Summary of Changes

A concise reference of all fields, classes, or interfaces added, removed, or modified.
Group by component. This section should be scannable without reading the full doc.
