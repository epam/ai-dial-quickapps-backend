# Design: Matching Skills from Free Text, Across All Sources

- **Status:** Draft
- **Issue:** [epam/ai-dial-quickapps-backend#567](https://github.com/epam/ai-dial-quickapps-backend/issues/567)
- **Dependencies:**
    - [`skill_invocation.md`](skill_invocation.md) — the chip mechanism (`custom_content.skills`),
      `SkillsRegistry`, `generate_skills_xml`, and the `read_skill` tool all stay as they are and are
      reused, not replaced. As actually implemented in `src/quickapp/skills/invocation/` today, the
      chip path resolves **several** skills per message, up to
      `SKILL_INVOCATION_MAX_SKILLS_PER_MESSAGE`
      (`_skill_reference.collect_picks` → `ConversationPicks.by_ordinal`, up to that many URLs per
      ordinal) and injects **one synthetic assistant turn with N parallel `read_skill` calls** per
      turn (`_SkillInvocationInjector`, built on `MultiSyntheticToolCallInjector`). That primitive —
      one assistant message carrying N parallel tool calls plus N tool results — is exactly what
      concern 3 below proposed; it now already exists in
      `common/synthetic_injection/multi_synthetic_tool_call_injector.py` and just needs a second,
      free-text-driven producer of the calls list, not a new mechanism.
    - `src/quickapp/tool_discovery/` — `_AnonymousAgent` / `_ToolSearchTool`, the existing
      LLM-classification pattern this design mirrors for matching.
    - `src/quickapp/skills/dial_resource/` — `DialSkillResolver`, `DialSkillReader`,
      `_DialSkillsClient` — the per-URL manifest/file resolution this design reuses unchanged for
      every source.
    - `ai-dial-core` — an aggregate "list every skill readable by this user" capability (own +
      shared-with-me + public in one call) is **not confirmed to exist**. `aidial_client`'s
      `AsyncSkillsRef.list()` only lists one bucket at a time (the caller's own, when unqualified),
      via `GET /v2/metadata/skills/{bucket}/`. This is an open external dependency — see
      [Open Questions](#open-questions--external-dependencies).

## Problem Statement

[`skill_invocation.md`](skill_invocation.md) solves *explicit* invocation: the user picks one or more
skills from a Chat palette, and they are sent as `custom_content.skills[]` chips. That closes the
access gap for the user's own skills, but leaves two things unsolved:

1. **No way to invoke a skill by naming it in the message itself.** "Review this PR with my review
   checklist and write it up in my report style" names two skills in prose. There is no palette chip
   here — the user just wrote what they meant, the way they'd ask a colleague. Today this only works
   if the model happens to decide, on its own, to call `read_skill` for something in
   `<available_skills>` (true only for the agent's own declared skills, and not guaranteed — UC-2 in
   the dependency doc). It does not work at all for skills the user owns but the app never declared,
   because the model has no way to know they exist.
2. **No unified view across sources.** A skill relevant to one message can live in any of: the app's
   predefined skills, its declared DIAL prompt/skill resources, the user's own Core bucket, a skill
   shared with the user, or a published one. Each has a different discovery cost — the first two are
   already resolved per request with zero extra I/O; the Core-backed ones require first *listing*
   what exists before anything can be matched, and that listing is scoped to `(user, source)`, not
   global, so it cannot be cached the way the deployment/application caches are (`common/cache.py`'s
   two existing consumers are singleton-scoped and keyed only by a global `deployment_id`).

This design covers finding and deterministically loading the right skill(s) — possibly more than
one, possibly from different sources, in a single turn — when the user only wrote about them.

## Design Goals

1. A skill named in the message text is matched and loaded **deterministically** — the same
   guarantee [`skill_invocation.md`](skill_invocation.md) gives the chip, extended to free text.
2. **All sources are eligible**, and each is independently toggleable by the app author: predefined
   skills, the app's declared DIAL prompt/skill resources, the user's own Core skills, skills shared
   with the user, and public skills.
3. **More than one skill can be matched and loaded from a single message**, because that is the
   ordinary case once free text is the trigger (the goal example names two).
4. Matched skills are injected as **one coherent assistant turn**: one assistant message issuing all
   matched tool calls in parallel, followed by their results — the same shape a model-initiated
   parallel tool call turn has, not one bolted-on pair per mechanism.
5. The added cost is bounded and mostly opt-in: zero extra network I/O for declared sources; Core
   catalog lookups are cached and gated behind an explicit per-source toggle, off by default.
6. No path fails the request. A classification failure, a disabled source, or a Core outage all
   degrade to "no match," not an error.
7. `<available_skills>` and `read_skill` keep their existing contract. Full skill content is never
   cached across requests — it is resolved fresh via the existing `DialSkillResolver` every turn,
   exactly as the chip path already does, so a revoked share or an edited skill is reflected
   immediately.

---

## Use Cases

### UC-1: Two skills named in one message, from two sources

**Trigger:** The agent declares a `pr-review` skill. The user also owns a `report-style` skill in
their own Core bucket, never declared by the app. The user writes "Review this PR with my review
checklist and write it up in my report style."  
**Behavior:** The matcher is given the union of the enabled sources' catalogs (name + description),
classifies the message, and returns both names. The injector builds one synthetic assistant message
with two parallel `read_skill` calls and two tool results, inserted after the user message.  
**Outcome:** The model starts its turn with both manifests already in context, in one assistant
turn, and answers using both.

### UC-2: No skill is named

**Trigger:** An ordinary message with no skill reference.  
**Behavior:** The prefilter (see [Latency and Cost](#latency-and-cost)) or the classifier returns no
matches. Nothing is injected.  
**Outcome:** Identical to today — no visible artifact, no extra stage, no change to
`<available_skills>`.  

### UC-3: A Core-backed source is disabled

**Trigger:** The app has `features.skill_matching.sources.user_own = false`. The user still writes
"use my report-style skill."
**Behavior:** The user's own-bucket catalog is never fetched; the matcher only sees the enabled
sources' catalogs, so nothing matches.
**Outcome:** No injection. Because this is a silent, cost-driven scope cut rather than a failure, it
is not reported as an "Initialization issues" entry — the app simply didn't opt into that source.

### UC-4: The classifier names a skill that isn't real

**Trigger:** The classification call hallucinates a name not present in any enabled catalog.
**Behavior:** The name is dropped with a warning log, mirroring `_ToolSearchTool`'s existing handling
of an unknown tool name.
**Outcome:** The rest of the batch, if any, still injects normally.

### UC-5: A message carries both a chip and a free-text mention

**Trigger:** The user picks `code-review` from the palette (a chip) and also writes "...and use my
report-style skill for the write-up."
**Behavior:** Both the chip pick and the free-text match feed the same "skills to inject this turn"
list, and one multi-call assistant turn is built for all of them together.
**Outcome:** One assistant turn, two parallel `read_skill` calls — not a chip-pair followed by a
separate match-pair.

---

## Proposed Design

```mermaid
sequenceDiagram
    participant User as User message
    participant Cat as Catalog assembly (per enabled source)
    participant LLM as Classifier (cheap, history-less)
    participant Res as DialSkillResolver
    participant Inj as Multi-call injector
    participant Orch as Orchestrator LLM

    User->>Cat: last user message text
    Cat->>Cat: declared sources: already resolved, in-memory, free
    Cat->>Cat: Core sources (if enabled): cached listing (names+descriptions), TTL-bounded
    Cat->>LLM: query + merged catalog (name, description, source)
    LLM-->>Cat: 0..N matched names (fail-open on error/timeout/malformed output)
    Cat->>Res: resolve each matched name's URL (declared: local; Core: 2 round-trips, uncached)
    Res-->>Inj: resolved skill content, or a failure reason per name
    Inj->>Inj: build ONE assistant message with N parallel read_skill calls + N tool results
    Inj->>Orch: inserted after the triggering user message
```

The design has five concerns.

### 1. Skill sources and the per-source config toggle

Every existing `SkillsProvider` source stays exactly as it resolves today; what's new is a
**matching catalog** assembled from whichever sources are enabled for matching:

| Source | Provider | Resolution cost | Matching default |
|---|---|---|---|
| Predefined | `AgentSkillsProvider` | Loaded at startup, free | On |
| Declared DIAL prompt skills | `_DialPromptSkillsContext` | Resolved per request already, no extra cost | On |
| Declared DIAL skill resources | `_DialSkillsContext` | Resolved per request already, no extra cost | On |
| User's own Core skills | new — `client.skills.list()` on the caller's own bucket | New: one cached listing call | Off |
| Skills shared with the user | new, **capability unconfirmed** | Unknown — see Open Questions | Off |
| Public skills | new, **capability unconfirmed** | Unknown — see Open Questions | Off |

Declared sources default **on** because they're already fully visible in `<available_skills>` today
at zero extra cost — matching them just makes the model's existing, non-guaranteed choice
deterministic. Core-backed sources default **off** because they add network I/O and broaden what's
disclosed to the matching step; an app author opts in per source.

Config shape, modeled on `ToolDiscoveryConfig`'s `PreviewField`-wrapped pattern
(`src/quickapp/config/tool_discovery.py`):

```python
class SkillMatchingSources(BaseModel):
    declared: bool = True
    user_own: bool = False
    user_shared: bool = False
    public: bool = False

class SkillMatchingConfig(BaseModel):
    enabled: bool = False
    service_model: str | None = None  # falls back to the orchestrator deployment
    sources: SkillMatchingSources = SkillMatchingSources()
```

`Features.skill_matching: SkillMatchingConfig | None`, `PreviewField`-wrapped like `web_fetch` and
`tool_discovery`. One flag gates the whole capability; the `sources` block scopes it per source
without needing separate top-level toggles.

### 2. Matching mechanism — one shared LLM classification call

Mirrors `tool_discovery` exactly (`_AnonymousAgent`, `_ToolSearchTool`): a single, non-streaming,
history-less `chat.completions.create` call against `ORCHESTRATOR_AZURE_CLIENT` (or
`skill_matching.service_model` if set), given the message text and the merged catalog
(`name`, `description`, and enough to resolve later — `source` and `url`), returning a bare JSON
array of matched names. Same fail-open contract: any `openai.OpenAIError`, timeout, or malformed
response becomes an empty match list, never an error surfaced to the user.

`_AnonymousAgent.route` today has **no explicit timeout** — this design calls that a gap worth
closing when the pattern is mirrored (and arguably in `tool_discovery` itself, though that's outside
this design's scope).

No embeddings or vector search are used or proposed: none exist anywhere in this codebase today, and
the LLM-classification approach is already an established, working pattern here
(`tool_discovery`) rather than new infrastructure.

### 3. Injection — one assistant turn, N parallel tool calls

This concern is **already solved and shipped**, not proposed here. The chip path
([`skill_invocation.md`](skill_invocation.md)) needed exactly this shape for its own multi-chip
support and built it first; skill matching just becomes a second producer of the same primitive.

**Existing primitive, decoupled from skills entirely:** `MultiSyntheticToolCallInjector`
(`common/synthetic_injection/multi_synthetic_tool_call_injector.py`), generalizing the single-call
`SyntheticToolCallInjector` in the same package. A subclass implements two methods —

```python
async def get_calls(self, messages: list[Message]) -> list[SyntheticCall]: ...
async def get_content(self, call: SyntheticCall, index: int, messages: list[Message]) -> str: ...
```

— and `transform()` does the rest: it hashes the whole call set into a **batch signature**
(tool name + arguments only, independent of content and of each call's `payload`), builds the N
results in parallel, and produces exactly the shape a real model-initiated parallel tool call turn
has — **one assistant message carrying N `tool_calls`, followed by N tool result messages**. This is
skill-agnostic; `_SkillInvocationInjector` is just today's one consumer, and a future
`_SkillMatchingInjector` would be a second.

How the settled design points actually work, for this design to build on:

- **Call-id generation is per batch, not per call.** A call's id is
  `{prefix}b_{signature_hash6}_i_{index}_c_{content_hash6}` — the *batch* signature (every call's
  tool name + arguments together) plus that call's own index and content hash. This, not a
  per-call sorted-arguments hash, is what makes the whole set collide-or-not as one unit (see
  `transform()`'s docstring for the three cases: identical set/identical content is a no-op,
  identical set/changed content appends a fresh copy, no occurrence inserts after the first user
  message).
- **Dedup is per batch, not per call.** The unit of identity is the whole call set returned by
  `get_calls`, not each call independently — a *different* set (e.g. this turn matches a different
  combination of skills than an earlier turn did) never collides with an earlier occurrence, but a
  turn that repeats the exact same set is a no-op regardless of which individual skills in it were
  also picked elsewhere. A matcher that wants "skip only the skills already injected, inject only the
  new ones" builds that filtering into its own `get_calls`, before the set reaches the shared
  primitive — the primitive itself does not do per-call dedup.
- **Ordering** of the N calls within the one assistant message is whatever order `get_calls` returns
  them in — classifier output order vs. catalog order is a decision this design still has to make
  for its own `get_calls` implementation (see [Open Questions](#open-questions--external-dependencies)).
- **Staging** already piggybacks on the ordinary stage-display machinery: the synthetic turn renders
  exactly like a real multi-tool-call assistant turn would.
- **Unifies chip and free-text matches** is still open: today each `MultiSyntheticToolCallInjector`
  subclass produces its own independent turn, so a chip pick and a free-text match on the same
  message currently become *two* synthetic turns, not one merged turn as UC-5 wants. Merging them
  into a single `get_calls` result — one injector call site combining both sources — is scope this
  design still owns.

### 4. Catalog assembly and caching

- **Declared sources** contribute their already-resolved `name`/`description` at zero extra cost —
  no new cache needed; this is the same data already going into `<available_skills>` today.
- **Core-backed sources** (currently only "own bucket" is confirmed feasible) need a **listing** step
  before anything can be matched: `client.skills.list()` on the caller's own bucket via
  `AsyncSkillsRef`. Only the listing (names + descriptions) is cached — never full content, which
  must keep resolving fresh every turn through the unchanged `DialSkillResolver`, preserving the
  revocation-safety property already established for the chip path.
    - Cache with the existing generic `CacheService[T]` (`common/cache.py`); no change to that class
      is needed, only a new caller-built compound key.
    - TTL: a short, explicit setting (default proposed: 5 minutes) rather than the existing
      `LONG_CACHE_TTL`, trading a little re-fetch cost for a newly created or renamed skill becoming
      matchable within a human-noticeable window.
    - Cache key must be scoped by the caller's identity. **Gap found while researching this
      design:** no `user_id`/subject field exists anywhere in `_di_types.py` or `_RequestContext`
      today. This design proposes resolving the caller's own Core bucket id and using that as the
      cache-key dimension, but whether that resolution is already cheap/local or itself a Core call
      needs verifying — see Open Questions.
- **Shared-with-user and public sources** have no confirmed listing capability at all today — see
  Open Questions. Until confirmed, their toggles exist in the config shape but have no working
  implementation; enabling them should be a no-op (empty catalog) rather than an error.

### 5. Latency and cost

| Scenario | Added cost |
|---|---|
| No Core sources enabled | One LLM classification call per eligible message; no network I/O beyond it |
| A Core source enabled, cache warm | + 0 Core calls for the catalog (cache hit); + one `DialSkillResolver.resolve` round-trip pair per matched skill, in parallel |
| A Core source enabled, cache cold | + one Core listing call (amortized by the TTL) |

To avoid firing the classification call on every single turn, a prefilter skips matching when the
message has no text content at all (attachment-only or chip-only turns) or is trivially short. A
weaker heuristic — skip when no candidate name/description shares any token with the message — is
noted as an option but flagged as risky (it can silently drop a paraphrase with no literal overlap)
and is not proposed as a default.

---

## Failure Modes

Extends, does not replace, [`skill_invocation.md`](skill_invocation.md)'s existing table.

| Condition | Result |
|---|---|
| Message has no text, or the prefilter rejects it | Matching is skipped entirely; identical to today |
| Message text matches no skill in any enabled source | No injection, no exception, no visible artifact |
| Message text matches two or more skills (goal use case) | One multi-call assistant turn, all matches as parallel `read_skill` calls |
| Classification call times out, errors, or returns malformed output | Treated as zero matches (fail-open); logged as a warning; request still served |
| `features.skill_matching.enabled = false` (default) | Neither matching nor any extra call runs; exactly today's behavior |
| A specific source's toggle is off | That source's catalog is never fetched or matched against; not reported as a failure |
| Core catalog listing call fails (cache cold) | Treated as an empty catalog for that source this turn; nothing cached, next turn retries |
| A matched name doesn't exist in any enabled catalog (hallucination) | Dropped with a warning log; the rest of the batch still injects |
| A matched skill's resolve fails after a successful catalog match (deleted / bad manifest) | Same as an existing chip-resolution failure: fixed error result injected, reported in "Initialization issues", not listed |
| Two matched skills share a name across sources | Existing `SkillsRegistry` order-based collision rule applies unchanged |
| The model also calls `read_skill` itself for an already-matched skill | Extra, low-cost, idempotent lookup; not suppressed |
| Shared-with-user / public source enabled but no listing capability exists yet | Empty catalog for that source; no error |

---

## Alternatives Considered

| Alternative | Why not |
|---|---|
| Embedding/vector search over the skill catalog | No such infrastructure exists anywhere in this codebase; LLM-based classification is already an established, working pattern here (`tool_discovery`), so it needs no new infra. |
| Keep the pair-per-mechanism model (one pair for the chip, a separate pair for matches) | Free-text matching routinely needs to load more than one skill per turn; stacking separate pairs from separate mechanisms doesn't reflect how a real parallel tool call turn looks, and complicates history/dedup for no benefit. |
| Cache full skill content across requests, not just the catalog listing | Breaks the revocation-safety property [`skill_invocation.md`](skill_invocation.md) already established: a revoked share or edited skill must be reflected on the very next turn. |
| A single global cache for "all skills," like the deployment/app caches | The candidate set is scoped per `(user, source)`, not global — a shared key would either leak one user's catalog to another or thrash on every request. |

---

## Open Questions / External Dependencies

1. **Core aggregate listing capability (blocking for shared/public sources).** No evidence in this
   repo or the vendored `aidial_client` SDK of a "list every skill readable by this user" call (own +
   shared + public in one shot) — only per-bucket listing is confirmed. Needs confirmation from the
   `ai-dial-core` team, in the same posture the dependency doc used for Core PR #1956.
2. **User identity in the request pipeline (blocking for the Core cache key).** No `user_id`/subject
   field exists in `_di_types.py`/`_RequestContext` today. Needs a decision on whether to expose the
   caller's resolved Core bucket id as a new context value (and whether that resolution is already
   cheap/local), or to key the cache off the request's API key/bearer instead.
3. **Match ordering.** When the classifier returns multiple names, does injection order follow the
   classifier's output order or catalog order? Needs a decision before implementation.
4. **Default enablement per source**, beyond the "declared on, Core off" split proposed here — is a
   finer-grained default warranted (e.g. shared skills defaulting differently than public ones once
   their capability exists)?

---

## Summary of Changes

This is a design only; the free-text matching itself is not implemented. What §3 depends on —
`MultiSyntheticToolCallInjector`, the shared multi-call injection primitive — already is, built for
the chip path's own multi-skill support; this design's implementation pass reuses it as-is rather
than adding it. Anticipated shape, for a future implementation pass:

- `quickapp/skills/matching/` (or a similarly-scoped new sibling package under `quickapp/skills/`) —
  the free-text matcher(s), one per catalog-cost tier (declared vs. Core-backed), a
  `SkillMatchingConfig`-driven catalog assembler, and a `MultiSyntheticToolCallInjector` subclass
  whose `get_calls` returns the matched skills as `read_skill` calls.
- `quickapp/skills/dial_resource/` — a new own-bucket listing method on `_DialSkillsClient`, wrapping
  `client.skills.list()`.
- `quickapp/common/cache.py` — reused as-is; the new compound cache key is built by the caller.
- `quickapp/config/` — `SkillMatchingConfig` / `SkillMatchingSources`, wired into `Features`.
- `ai-dial-core` — request/confirm an aggregate shared/public skill listing capability (Open
  Question 1).
