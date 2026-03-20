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

Agents interact with memory through **MCP tools** — `store_memory` and `search_archive` — exposed by the Memory MCP server. What the agent decides to store and when is governed by the mechanisms described in Concern 9.

The Memory MCP server is deployed as a **DIAL Application Type** with an MCP endpoint, registered in DIAL Core (enabled by [epam/ai-dial-core#1382](https://github.com/epam/ai-dial-core/issues/1382), already shipped). A single deployed instance serves all users; no code changes are needed to wire the tools.

| Tool | Description | Arguments |
|------|-------------|-----------|
| `store_memory` | Append a new memory row. Strictly append-only — never overwrites. | `content: str`, `memory_type: Literal["core","episodic"]`, `context: str`, `importance: float` |
| `search_archive` | Search episodic history. Use when user references past events not in the current context. | `query: str` |

**Append-only invariant**: if the agent stores "project-alpha is in Python" and later "project-alpha is in Rust", both rows coexist. Retrieval surfaces the contextually appropriate one. If the model sees two conflicting facts injected for the same query, it asks the user to clarify — which is the correct behavior.


### Concern 2: How UI clients interact with memory?

UI clients (e.g. DIAL Chat, custom frontends) interact with memory through **custom REST API routes** exposed by the Memory MCP server. The UI role is limited to **read and delete** — agents are the only writers.

#### Why no Create from UI?

Facts stored in memory carry semantic metadata (`importance`, `context`, `embedding`) that the agent computes at storage time based on conversation context. A UI form cannot reproduce that reasoning reliably. The agent is the only writer.

#### REST Routes

The Memory MCP server exposes management routes alongside its MCP endpoint. Per [epam/ai-dial-core#1382](https://github.com/epam/ai-dial-core/issues/1382) (already shipped), DIAL applications can declare custom HTTP routes in their application schema — these are routed through DIAL Core and subject to the same access control as any other DIAL entity.


| Method   | Path            | Description                                                         |
|----------|-----------------|---------------------------------------------------------------------|
| `GET`    | `/memory`       | List all memory rows for the authenticated user. Supports filtering by `memory_type`. |
| `GET`    | `/memory/{id}`  | Get a single memory row by ID.                                      |
| `DELETE` | `/memory/{id}`  | Hard-delete a memory row.                                           |



#### Access Control

Routes are proxied through DIAL Core. The caller's identity is resolved by DIAL Core. The server uses the identity to derive the correct storage path — cross-user access is structurally impossible.

#### Relationship to Concern 5

The route design here is the **server contract**. How the UI surfaces these operations (memory panel, inline editing, bulk delete) is addressed in Concern 5.

### Concern 3: What is memory in terms of DIAL entities?

Memory maps to two distinct DIAL entities: an Application Type and per-user storage objects.

#### 3.1 Memory MCP Server — DIAL Application Type

The Memory MCP server is registered in DIAL Core as a **schema-rich Application Type**. This gives it first-class participation in DIAL's configuration, access control, and management mechanisms — no custom config file needed. Admins configure the application properties via the DIAL Core API or Admin Panel, and the server reads them at runtime via the DIAL SDK (`request.request_dial_application_properties()`).

There is a single deployed instance shared across all users. User isolation is achieved entirely through storage paths (Concern 6), not through separate server instances. Users do not create memory instances — the Application Type is an admin-managed infrastructure component, not a user-facing template for self-service creation.

The application exposes three interfaces in DIAL Core:

| Interface | Purpose |
|-----------|---------|
| MCP endpoint | Agent-callable tools (`store_memory`, `search_archive`) — Concern 1 |
| Custom REST routes | User-facing read/delete API for memory rows — Concern 2 |
| `applicationTypeViewerUrl` | Memory management UI embedded in DIAL Chat — Concern 5 |

Using an Application Type (over a plain app without schema) brings:
- **Schema-driven configuration** — configuration declared in a JSON schema and managed via DIAL Core without code changes or redeployment.
- **Built-in DIAL management** — the application participates in DIAL's access control, observability, and Admin Panel out of the box.
- **`applicationTypeViewerUrl`** — the standard DIAL mechanism for attaching a custom UI to an application, used here for the memory management panel (Concern 5).

#### 3.2 Per-user memory data — DIAL file storage objects

Each user's memory is stored as a **LanceDB table** (`memory.lance/`) inside their personal bucket in DIAL file storage. The server never touches another user's bucket.

In the first iteration there is a single memory per user:

```
files/{bucket}/memory/memory.lance/
```

where `{bucket}` is the user's opaque bucket identifier, obtained by the Memory MCP server via `GET /v1/bucket` using the caller's identity forwarded by DIAL Core.

These are standard DIAL file storage entries. The Memory MCP server syncs them down before read/write and syncs up after write, keeping the server stateless.


### Concern 4: How memory is stored in DIAL file storage?

DIAL does not require a centralized database. The Memory MCP server follows the same principle — all persistent state lives in DIAL file storage (cloud-agnostic BLOB). The server itself is fully stateless.

#### 4.1 BLOB storage — LanceDB tables and config

DIAL file storage is cloud-agnostic: AWS S3, Google Cloud Storage, Azure Blob Storage, or a local file system for self-hosted deployments. The Memory MCP server stores two types of objects per user in DIAL file storage:


| Object       | Path                                   | Description                                                     |
|--------------|----------------------------------------|-----------------------------------------------------------------|
| Memory table | `files/{bucket}/memory/memory.lance/` | LanceDB table (core facts + episodic history) |


No external database is required. All state is in BLOB storage and the server can be restarted or scaled without data loss.

#### 4.2 LanceDB sync pattern — stateless server

LanceDB operates on local files. Since BLOB storage is not a local filesystem, the Memory MCP server uses a **sync-down / sync-up** pattern:

1. **Before read or write**: sync the relevant `memory.lance/` directory from BLOB to a local `/tmp` cache.
2. **Perform the LanceDB operation** (query or append) locally.
3. **After write**: sync the modified `memory.lance/` directory back up to BLOB storage.

This keeps the server stateless — any instance can handle any request by syncing from BLOB first.

### Concern 5: How user can view and manage memory?

Memory management is surfaced to the user as a **dedicated section in DIAL Chat's settings/configuration area** — not inside a conversation. This section has two responsibilities:

1. **Memory config** — user-facing controls for memory settings (consent flags, scope enablement, and other knobs). These are managed via the Application Type's schema-driven properties (Concern 3.1) rather than a custom config file.
2. **Memory browser** — a UI to read and delete individual memory rows, backed by the REST routes defined in Concern 2.

The section is rendered via the `viewerUrl` registered on the Memory MCP server DIAL application (Concern 3). DIAL Chat loads it as an embedded view within the settings panel.

> Detailed UI design (layout, components, interaction flows) is deferred to a separate UI design pass.

### Concern 6: How memory is scoped?

**Scope is defined entirely by the path to the `memory.lance/` file in DIAL file storage.** The Memory MCP server is path-agnostic — it never interprets what a path means semantically. Scope resolution is the sole responsibility of the caller (quickapps-backend).

In the first iteration there is a single scope per user:

```
files/{bucket}/memory/
```

The Memory MCP server resolves the bucket via `GET /v1/bucket` using the caller's identity forwarded by DIAL Core, then constructs the path. There is no cross-user sharing — every path is rooted under the user's own folder.



### Concern 7: How user provides consent for saving information to memory?

Two options are on the table:


|              | Option                                                                                  | When consent is given                                                             | UX cost                                        | Risk                        |
| ------------ | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------- |
| **One-time** | User enables memory in settings (Concern 5). From that point the agent stores silently. | Low — one action, no interruptions.                                               | User may be surprised by what gets stored.     |                             |
|              | **Per-store**                                                                           | Agent asks the user for confirmation each time it decides to call `store_memory`. | High — interrupts the conversation every time. | None, but poor UX at scale. |


> Decision deferred. Both options are viable; the right choice depends on regulatory requirements and UX research. Whichever option is chosen, the consent flag is declared in the Application Type's JSON schema and managed via DIAL Core's configuration mechanisms (Concern 3.1).

#### Human-in-the-loop (out of scope)

A third option — and the most precise — would be to use a **human-in-the-loop** mechanism: a platform-level capability that allows the agent to pause execution and request explicit confirmation from the user before performing a sensitive action (in this case, calling `store_memory`).

This would give users granular, per-store control without permanently interrupting the conversation flow — the agent would only ask when it is about to store something, not on every turn.

> Human-in-the-loop is **out of scope for this feature**. It requires a dedicated platform mechanism to pause and resume agent execution with user input. Once that mechanism is available in DIAL, it becomes the preferred implementation for per-store consent — superseding second option above.

### Concern 8: How memory is structured? (Facts, their lifecycle)

All memory — both facts and conversation history — lives in a **single LanceDB table** (`memory.lance/`) per user. Memory type is a column value, not a separate table or file.

#### Schema

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `string` | UUID |
| `memory_type` | `string` | `"core"` or `"episodic"` |
| `content` | `string` | Full text of the memory |
| `context` | `string` | Scope hint — e.g. `"project-alpha"`, `"user-prefs"` |
| `importance` | `float32` | 0.0–1.0; drives Tier 1 always-inject threshold and Tier 2 score weighting |
| `embedding_model` | `string` | Model that produced the vector; used to exclude cross-model comparisons |
| `vector` | `list<float32>[N]` | Embedding; null in Phase 1 (FTS only) |
| `timestamp` | `timestamp[us]` | Creation time |
| `access_count` | `int32` | Incremented on retrieval; reserved for future decay logic |

#### Memory types and lifecycle

**Core facts** (`memory_type = "core"`) — permanent facts about the user: name, preferences, project details. Written by the agent via `store_memory`. **Append-only** — a new row is always added, existing rows are never overwritten. If two facts conflict, both coexist and retrieval surfaces the contextually appropriate one. The `context` field disambiguates facts from different domains.

**Episodic memories** (`memory_type = "episodic"`) — a record of past interactions. Written automatically after each turn by quickapps-backend. Searchable by the agent via `search_archive` when the user references past events.

#### Retrieval — two-tier injection for core facts

Before each request, quickapps-backend fetches core facts using two tiers:

**Tier 1 — Always inject** (no query, top-N by importance):
```sql
SELECT * FROM memory WHERE memory_type = 'core'
ORDER BY importance DESC LIMIT 5
```
Guarantees universal facts (name, language preference) are always in context.

**Tier 2 — Context inject** (semantic match to the current user message):
```
FTS (Phase 1) or vector search (Phase 2) over memory_type = 'core'
scored as: final_score = cosine_similarity * (0.5 + importance * 0.5)
LIMIT 10
```
Surfaces facts relevant to the current topic without injecting unrelated noise.

Both tiers are merged and deduplicated by `id` before injection.

#### Retrieval phases

| Phase | `search_archive` | Tier 2 core injection | Embedding storage |
|-------|------------------|-----------------------|-------------------|
| Phase 1 | FTS (keyword match) over episodic rows | FTS over core rows | None — `vector` column is null |
| Phase 2 | Cosine similarity via LanceDB ANN | Cosine similarity, importance-weighted | Per-row float vector |

**Embedding model safety**: every row stores `embedding_model` at write time. If the active model changes, rows with a different `embedding_model` are excluded from vector search and fall back to FTS — preventing cross-model cosine similarity errors.

### Concern 9: How the system can be adjusted about what is saved to memory and what is not?

Three mechanisms control what the agent saves to memory, applied at different layers:

#### 9.1 Memory Skill

A skill file (`config/predefined/skills/memory/SKILL.md`) is loaded by the existing `AgentSkillsProvider` + `PredefinedContentProvider` pipeline — no changes to the skills loader are needed. It is the primary control knob: it tells the agent **when** to call `store_memory`, **what to assign as importance**, and **what never to store**.

Default rules baked into the skill:

- **`store_memory` with `memory_type=core`** — when the user states a permanent fact, corrects a fact, or establishes a preference.
- **`store_memory` with `memory_type=episodic`** — when a significant decision, bug fix, or repeatable workflow is established during the session.
- **`search_archive`** — when the user references past events ("last time", "remember when") not in the current context.
- **Never store**: intermediate debug steps, general knowledge, or file contents (that is RAG's job).

Importance guide:

| Importance | Meaning |
|------------|---------|
| 0.9 + | Universal facts (name, language preference) — always injected regardless of topic |
| 0.7 – 0.9 | Project/context-specific facts — injected when contextually relevant |
| < 0.7 | Low-priority hints |

The skill can be customised per deployment or per QuickApp by replacing or extending `SKILL.md` — no server changes needed.

#### 9.2 System Prompt

The QuickApp's system prompt can further restrict or extend memory behaviour for that specific application. For example:

- "Do not store any information related to financial data."
- "Always remember the user's preferred output format."

Prompt-level instructions augment the skill — they are application-specific and take effect for that QuickApp only.

#### 9.3 User Direct Message

Users can instruct the agent to store a fact directly in conversation:

- "Remember that I always prefer Python for code examples."

The agent interprets these as explicit `store_memory` calls with `memory_type=core`. This is the highest-trust signal — the user is the authority on their own facts. The skill instructs the agent to treat such messages as immediate store triggers, regardless of other heuristics.

### Concern 10: How can we later improve and evolve the system?

#### Multiple memory scopes

The first iteration uses a single per-user memory path — **global user scope**:

```
files/{bucket}/memory/memory.lance/
```

This stores all facts regardless of which QuickApp the conversation happens in. Universal facts (name, language, preferences) belong here — they are useful across all applications.

**App-scoped memory** is the natural next step. It adds a second LanceDB table per QuickApp:

```
files/{bucket}/apps/{quickapp_id}/memory/memory.lance/
```

This allows facts specific to one QuickApp (project details, app-specific preferences, workflow constraints) to be stored separately — not polluting the global user memory and not visible to other QuickApps.

| Scope | Path | What belongs here |
|-------|------|-------------------|
| Global user | `files/{bucket}/memory/` | Name, language, universal preferences — any QuickApp can read |
| App-scoped | `files/{bucket}/apps/{quickapp_id}/memory/` | Project facts, app-specific preferences, workflow rules |

**What changes when app-scope is introduced:**

- **Memory MCP server** — no changes. It is path-agnostic by design.
- **quickapps-backend** — resolves both paths from user identity + QuickApp ID; calls the server twice (once per path); merges and deduplicates results by `id` before injection. App-scoped facts take precedence over global facts when both are injected for the same query.
- **Skill** — updated to instruct the agent to distinguish between universal and app-specific facts when calling `store_memory`, passing the correct scope path accordingly.
- **REST routes (Concern 2)** — may need a `scope` query parameter so the memory browser in the UI can display global and app-scoped memories separately.
- **Viewer UI (Concern 5)** — updated to show both scopes in the memory browser, clearly labelled.

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