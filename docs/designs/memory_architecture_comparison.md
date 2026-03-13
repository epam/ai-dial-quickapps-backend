# Memory Architecture: Concept Comparison

## Approach A — Profile + Archive Split
_See `memory_architecture.md`_

## Approach B — Unified Semantic Injection
_See `memory_architecture_unified_semantic_injection.md`_

---

## Top-level comparison

### Storage model

| | Approach A | Approach B |
|---|---|---|
| Core facts | Separate `profile.json` (key/value) | Rows in a single `memory.lance/` table (`memory_type=core`) |
| History | Separate `history.lance/` | Rows in the same `memory.lance/` table (`memory_type=episodic`) |
| Files per namespace | 2 (`profile.json` + `history.lance/`) | 1 (`memory.lance/`) |

**A**: Two storage formats to maintain, sync, and reason about.  
**B**: One format, one sync mechanism, one schema regardless of memory type.

---

### How core facts are written

| | Approach A | Approach B |
|---|---|---|
| Mechanism | `update_core_fact(key, value)` — replaces by key | `store_memory(type=core, ...)` — always appends |
| On conflict | Previous value silently lost | Both facts coexist |

**A**: Simple, but "user's project is Python" gets overwritten when user later says "my project is Rust" — even if they meant a different project entirely.  
**B**: Both facts live on. Retrieval surfaces the contextually appropriate one. The model can see both and ask for clarification when genuinely ambiguous.

---

### How core facts are read and injected

| | Approach A | Approach B |
|---|---|---|
| When | Once, at conversation start | Every request |
| What is fetched | Full profile dump | Two tiers: top-N by importance (always) + top-M by match to current message |
| Adapts to topic shifts | No — fixed for the whole conversation | Yes — each turn injects what is relevant now |
| Risk of irrelevant noise | Grows with profile size | Bounded — only relevant facts injected |

**A**: Simple to implement. Works fine when the profile is small and the conversation stays on one topic.  
**B**: More requests to the memory server, but the model always gets the right context for the right topic.

---

### Universal vs context-specific facts

| | Approach A | Approach B |
|---|---|---|
| "User's name is Alex" (always relevant) | Injected as part of full dump | Always injected via Tier 1 (top-N by importance) |
| "Project-alpha is in Python" (context-specific) | Injected as part of full dump, even when off-topic | Injected via Tier 2 only when the message is about that project |

**A**: No distinction — everything or nothing.  
**B**: `importance` field is the single control knob. High importance = always present. Lower importance = surfaces only when relevant.

---

### Agent tool surface

| | Approach A | Approach B |
|---|---|---|
| Read core memory | System-injected (no tool call) | System-injected (no tool call) |
| Write core memory | `update_core_fact(key, value)` | `store_memory(content, type=core, context, importance)` |
| Search history | `search_archive(query)` | `search_archive(query)` |

**A**: Key/value write forces the agent to pick a canonical key name — context gets lost in the key string.  
**B**: Free-text content plus a `context` field. Facts are sentences, not key/value pairs. The agent doesn't need to invent a key schema.

---

### Fact conflict handling

| | Approach A | Approach B |
|---|---|---|
| Same key, different value | New value silently replaces old | Both rows exist; retrieval picks the contextually correct one |
| Multiple projects with similar attributes | Cannot represent — one wins | Represented naturally; `context` field disambiguates |
| Model awareness of conflict | None | Can see both facts and ask user to clarify if needed |

---

### Complexity and trade-offs summary

| | Approach A | Approach B |
|---|---|---|
| Implementation complexity | Lower — simple file read/write | Higher — search logic, two-tier merge, per-request HTTP call |
| Correctness with growing profile | Degrades — noise increases, conflicts silently accumulate | Stays bounded — only relevant facts injected |
| Correctness with multi-context users | Fragile — one fact per key | Sound — facts scoped by context field |
| Latency per request | Lower — one HTTP call per conversation | Slightly higher — one HTTP call per request |
| Operational simplicity | Two storage files per namespace | One storage file per namespace |

---

## When each approach is the right choice

**Approach A** is appropriate when:
- The user profile is small and stable (few facts, rarely contradicted)
- Conversations are short and single-topic
- Implementation speed is the priority over long-term correctness

**Approach B** is appropriate when:
- Users have multiple projects, roles, or contexts that may be mentioned in the same conversation
- The profile is expected to grow over time
- Correctness under conflicting or overlapping facts is a requirement
- The product is long-lived and needs to handle real-world messy input
