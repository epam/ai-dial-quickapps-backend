---
name: dial-memory
description: Use when the user states a fact, preference, or correction about themselves or their work; when the user says "remember that"; when the user references past events not in the current context ("last time", "remember when"); or when a significant decision, bug fix, or workflow is established during the session.
compatibility: Requires the DIAL Memory MCP server to be configured and the store_memory / search_archive tools to be available.
---

# DIAL Memory

## Overview

You have two memory tools: **`store_memory`** for persisting facts and **`search_archive`** for recalling past events. Use them proactively — memory is only useful if you write to it.

## When to call `store_memory`

| Trigger | `memory_type` | Example |
|---------|---------------|---------|
| User states a permanent fact about themselves | `core` | "My name is Alex" |
| User establishes a preference | `core` | "Always generate code in Python" |
| User corrects a fact you stated | `core` | "Actually, I'm in Berlin, not London" |
| User explicitly asks you to remember | `core` | "Remember that I prefer dark mode" |
| Significant decision or workflow established this session | `episodic` | "We agreed to use Postgres for this project" |
| Bug root cause or non-obvious fix discovered | `episodic` | Resolved a tricky auth regression |

**Append-only**: never update or replace. If a fact changes, store the new version — both coexist and retrieval picks the contextually appropriate one.

## When to call `search_archive`

Call it when the user references past events **not visible in the current context window**:
- "Last time we worked on this..."
- "Remember when we fixed that bug..."
- "What did we decide about X?"

Do **not** call it speculatively on every turn — only when past events are clearly referenced.

## Parameters

### `store_memory`

| Parameter | Type | Notes |
|-----------|------|-------|
| `content` | `str` | Clear, self-contained statement of the fact. Write as if injected cold into a future conversation. |
| `memory_type` | `"core"` \| `"episodic"` | See table above. |
| `context` | `str` | Scope label. Use `"user"` for universal facts, `"<project-name>"` for project-specific, `"<app-name>"` for app-specific. |
| `importance` | `float` 0.0–1.0 | See guide below. |

### `importance` guide

| Score | Meaning | Examples |
|-------|---------|---------|
| 0.9–1.0 | Universal — always injected regardless of topic | Name, spoken language, global code language preference |
| 0.7–0.9 | Project/context-specific — injected when relevant | Project stack, team conventions, recurring preferences per app |
| < 0.7 | Low-priority hints | One-off notes, soft preferences |

### `search_archive`

| Parameter | Type | Notes |
|-----------|------|-------|
| `query` | `str` | Natural-language description of what you're trying to recall. Be specific. |

## What NEVER to store

- Intermediate debug steps or speculative ideas
- General knowledge you already have (facts not specific to this user)
- File or document contents (that is RAG's job)
- Anything the user has not stated or agreed to — do not infer facts and store them as certain

## Examples

**User:** "I always write my docs in Markdown."
```
store_memory(
  content="User writes documentation in Markdown.",
  memory_type="core",
  context="user",
  importance=0.85
)
```

**User:** "Remember that project Orion uses a microservices architecture."
```
store_memory(
  content="Project Orion uses a microservices architecture.",
  memory_type="core",
  context="orion",
  importance=0.8
)
```

**User:** "What did we decide about the database last week?"
```
search_archive(query="database decision last week")
```
