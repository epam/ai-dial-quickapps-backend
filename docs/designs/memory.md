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


### Concern 4: How memory is stored in DIAL file storage?


### Concern 5: How user can view and manage memory?


### Concern 6: How memory is scoped?


### Concern 7: How user provides consent for saving information to memory?


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
