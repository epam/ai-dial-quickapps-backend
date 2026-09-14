# Design: Invoking a Skill from a Message

- **Status:** Approved
- **Approved:** 2026-09-14
- **Issue:** [epam/ai-dial-quickapps-backend#549](https://github.com/epam/ai-dial-quickapps-backend/issues/549), a
  sub-issue of [#421](https://github.com/epam/ai-dial-quickapps-backend/issues/421) ([EPIC] Advanced Agent Skills
  support)
- **Scope:** Phase 1a — a picked skill is loaded, listed and readable, under its **own** name. Making a picked skill
  unable to collide with an agent's skill is phase 1b
  ([Follow-up](#follow-up-phase-1b--collision-free-names)).
- **Dependencies:**
  - [`skills_as_dial_resource.md`](skills_as_dial_resource.md) — `DialSkillResolver`, `DialSkillReader`, the
    `<skill_files>` inventory. Branch `feat/418-skills-as-dial-resource`, not yet on `development`.
  - `ai-dial-core` — `CollectRequestSkillsFn` collects `messages[*].custom_content.skills[*]` and auto-shares each skill
    to the per-request key; the field is in the OpenAPI message schemas as `RequestSkill`. **Done:**
    [epam/ai-dial-core#1956](https://github.com/epam/ai-dial-core/pull/1956) (issue #1955), on `development`. It
    rejects a URL the user can't read with `403`, which leaves one gap (see [Known Gaps](#known-gaps)).
  - `ai-dial-chat` — `chat-api` accepts the field (`MessageCustomContentDto`), and the composer emits it from a `/`
    palette of the user's own skills. **Agreed, not started.**

## Problem Statement

A skill reaches a QuickApp agent in exactly one way: the app author lists it in `ApplicationConfig.skills`, QuickApps
advertises it in `<available_skills>`, and the **model** decides whether to call `read_skill`. The user has no say.
They can't tell the agent "use this skill for this message", and they can't use a skill the author never attached.

That leaves two gaps:

1. **No deterministic invocation.** Even when the skill is attached, "please use the code-review skill" is a hint the
   model may or may not act on. Other agent products solve this with a `/skill-name` command whose effect is
   guaranteed: the skill is loaded, every time.
2. **No way in for the user's own skills.** DIAL Chat has a full skill catalog and editor. A user who wrote
   `code-review` for themselves cannot bring it into a conversation with an agent they don't own. Under a per-request
   key, the app cannot read `skills/<user-bucket>/…` at all unless something shares it.

DIAL Core and DIAL Chat have agreed on a wire contract that closes the access half: a user message may carry
`custom_content.skills[*]`, and Core auto-shares each referenced skill to the app's per-request key, as it already
does for `custom_content.attachments[*]`. This design specifies how QuickApps consumes that field.

## Design Goals

1. A skill the user picks is **always** loaded into the model's context on that turn. The model doesn't choose.
2. The user can pick any skill they can read from their own catalog: their own, one shared with them, or a published
   one. It doesn't need to be in the app config.
3. The loaded manifest **stays** in the model's context for the rest of the conversation, without being re-injected
   and without changing after the turn that loaded it.
4. The skill's **bundled files stay readable** on any later turn, through `read_skill(name, file_path)`, exactly as
   for a declared skill.
5. A chip on the current message that fails is visible to both the user and the model. The request is still served.
6. The **shape** of the skills contract doesn't change: `<available_skills>` keeps its fields, `read_skill` keeps its
   parameters, and a request without the field behaves exactly as today. What does change is *which* skills an agent
   ends up with — a picked skill can displace an agent's same-named one. That is a deliberate relaxation, not a
   property this design preserves; see [Known Gaps](#known-gaps).
7. The change is as small as possible. In particular, a picked skill is an ordinary `SkillsProvider` entry — no new
   lookup path, no second read tool, no new collision machinery, and no special case in `SkillsRegistry`.

## Phasing

- **Phase 1a — this design.** A picked skill is resolved, injected as a synthetic `read_skill` pair, and registered
  as an ordinary skill under **its own manifest name**. It wins any name collision with the agent's skills
  ([UC-5](#uc-5-the-users-skill-has-the-same-name-as-one-of-the-agents)).
- **Phase 1b — [follow-up](#follow-up-phase-1b--collision-free-names).** A picked skill gets a name it cannot collide
  on, so it stops shadowing the agent's skills and both stay reachable.
- **Phase 2 — to be designed** ([#550](https://github.com/epam/ai-dial-quickapps-backend/issues/550)). The user can
  pick the agent's own skills too. How the client learns about them is left for that design.

---

## Use Cases

### UC-1: Picking a personal skill from the palette

**Trigger:** The user picks their own `skills/<user-bucket>/sql-style` from the palette.
**Behavior:** Chat sends `content: "/sql-style …"` with `custom_content.skills: [{url: "skills/<user-bucket>/sql-style"}]`.
Core auto-shares the skill to the per-request key. QuickApps resolves it through `DialSkillResolver`, registers it as
`sql-style`, and inserts a synthetic `read_skill` call and result for that name after the user message.
**Outcome:** The model starts its turn with the skill's manifest and its `<skill_files>` inventory already in context.
The response shows the normal "Reading Skill: sql-style" stage.

### UC-2: Reading a bundled file three turns later

**Trigger:** On turn 4 the model calls `read_skill("sql-style", "references/naming.md")` for a skill picked on turn 1.
**Behavior:** The turn-1 user message still carries the chip, so Core shares the skill again and QuickApps resolves
and registers it again under the same name. The manifest itself is not re-injected: it comes back from the turn-1
assistant state like any other tool result.
**Outcome:** The file is returned. The conversation history is byte-identical to what the model saw on turn 1, even if
the user edited the skill in the meantime.

### UC-3: Asking for one of the agent's own skills

**Trigger:** The agent has an `acme-release-notes` skill. The palette doesn't offer it, so the user writes "use the
release notes skill for 0.9.0".
**Behavior:** Nothing new. The message carries no `custom_content.skills`, and QuickApps doesn't parse the text. The
skill is in `<available_skills>` as today, and the model decides whether to call `read_skill`.
**Outcome:** Same as today. Guaranteed invocation of the agent's own skills is phase 2.

### UC-4: The picked skill can't be loaded

**Trigger:** The skill was deleted, or its manifest is invalid.
**Behavior:** The synthetic pair is still inserted, with an error result that names the skill and says it could not
be loaded. The reason is reported to the user in the "Initialization issues" stage. The skill is not registered.
**Outcome:** The model knows the user asked for a skill it doesn't have, and says so. The rest of the answer is
produced normally.

### UC-5: The user's skill has the same name as one of the agent's

**Trigger:** The agent has a predefined `code-review`. The user picks their own `skills/<user-bucket>/code-review`.
**Behavior:** The user's skill wins. It is listed as `code-review`, `read_skill("code-review")` returns it, and the
agent's `code-review` is dropped from the merged set and reported in "Initialization issues" by the existing
`SkillsRegistry` collision path — no new mechanism.
**Outcome:** For that conversation the agent's same-named skill is unavailable. **This is accepted for 1a**, on the
assumption that a user does not pick skills whose names clash with the agent's. Phase 1b removes the possibility;
see [Known Gaps](#known-gaps).

---

## Proposed Design

```mermaid
sequenceDiagram
    participant Chat as DIAL Chat
    participant Core as DIAL Core
    participant QA as QuickApps
    participant LLM as Orchestrator LLM

    Chat->>Core: user msg with content and optional custom_content.skills[].url
    Core->>Core: validate and auto-share every skills[].url to the per-request key
    Core->>QA: chat/completions
    QA->>QA: initializer: collect chips from all user messages and resolve them
    QA->>QA: user skills provider (order -10) joins the SkillsRegistry merge
    QA->>QA: injector: chips of the last user msg become synthetic read_skill pairs
    QA->>QA: strip custom_content.skills from the working copy
    QA->>LLM: system prompt with available_skills + history + synthetic pairs
    LLM-->>QA: answer
    QA-->>Chat: answer + state.tool_execution_history (includes the pair)
```

Four concerns. Nothing below adds a lookup path: a picked skill becomes an ordinary entry in the existing registry,
which is what makes bundled files and later turns work for free (goals 4 and 7).

### 1. Wire contract — `custom_content.skills`

- **What.** An array on a **user** message's `custom_content`:

  ```jsonc
  {
    "role": "user",
    "content": "/code-review focus on auth",
    "custom_content": {
      "skills": [
        { "url": "skills/<bucket>/<path>" }
      ]
    }
  }
  ```

- **Owner.** The client writes it, Core validates and shares what it references, and QuickApps interprets it.
- **Semantics.**
  - In phase 1 the array only ever carries the user's skills, picked from the palette. The agent's own skills never
    go in it.
  - What Core does with each entry (`CollectRequestSkillsFn`), before QuickApps sees the request:
    - an entry that isn't an object, has no `url`, or whose `url` is absolute or not a `skills/` resource → `400` for
      the whole request;
    - a public skill → nothing to share, since any key can read it;
    - a skill the user can read → shared read-only with the per-request key;
    - a skill the user can't read → `403` for the whole request.
  - `url` is the only field QuickApps reads. Anything else (`title`, say) passes Core and is ignored, so the client
    may carry display data.
  - The URL has **no trailing slash**: `skills/<bucket>/<path>`. Core shares exactly that URL and authorises every
    read of the skill (`SKILL.md` and each bundled file) against it, so one share covers the whole skill. A URL ending
    in `/` would be shared under a different key and every read would then be denied. QuickApps strips a trailing `/`
    before use, so the dedup key and the share key stay aligned.
  - The field is **per message**, not per request. An invocation belongs to the turn it was made on. Because it stays
    on that message, Core re-shares the skill on every later turn while the client keeps resending the history, which
    is what keeps bundled files readable (UC-2).
  - `custom_content.skills` on a non-user message is ignored.
  - `content` is opaque. QuickApps never parses it, and the chip is the only invocation signal. The client sends it
    as the user typed it, `/name` token included, so a message with a chip is never empty.
- **Change.** Nothing to parse in the SDK: `CustomContent` is an `ExtraAllowModel`, so the field arrives in
  `model_extra`. A typed `skills` field in `aidial-sdk` is welcome but not required.

### 2. Resolution — `_SkillInvocationInitializer`

- **What.** A `CompletionInitializer` in a new package `quickapp/skill_invocation/`. It fills a request-scoped
  `_InvokedSkillsContext` (concern 3).
- **Owner.** `quickapp/skill_invocation/`.
- **Semantics.**
  1. Walk the user messages **newest to oldest** and collect the `url`s of their `custom_content.skills`, each
     canonicalised by stripping a trailing `/`. Identical chips on one message count once. A malformed entry is
     dropped with a debug log — Core answers such a request with `400`, so reaching here means something upstream
     changed, and refusing the turn over it would be worse.
  2. Deduplicate, keeping each URL's **latest** occurrence: that is what decides its position. The chips of the last
     message are therefore the newest picks and are never dropped by the cap in step 3.
  3. Keep the newest `SKILL_INVOCATION_MAX_SKILLS` distinct URLs, walking newest-first so the cap drops the **oldest**
     picks. A dropped pick's manifest is still in history, but it is no longer registered, so its name stops resolving
     and its files stop being readable.
  4. Wrap each URL in a `DialSkillConfig` and hand the list to the existing `DialSkillResolver`, unchanged. Manifest
     parsing, the `<skill_files>` inventory, byte caps, per-URL failure isolation and warning severities all come for
     free.
  5. Store the resolved skills by position, oldest first, the set of URLs that resolved, and **the chips of the
     message being answered**. The injector reads all three back: the first two to choose between a real result and
     the error sentence, the third to know which chips belong to this turn. Recording "this turn's chips" here rather
     than re-parsing the messages later means the injector does not care whether the scrub has already run.
- **Every historical pick is re-resolved on every turn.** That is what keeps a turn-1 skill registered on turn 4 so
  its files stay readable (goal 4, UC-2). The cost is one Core fetch per picked skill per turn, bounded by the cap.
  Resolving lazily on a `read_skill` miss would remove it but needs an async path through the registry merge; see
  [Out of Scope](#out-of-scope).
- **No dedup against the app config.** A picked URL the app also declares is resolved again and wins its own name by
  order. It is the same content from two sources, and needs no merging logic.
- **Where it gets the messages.** Initializers run **before** `setup_messages`, so `MessagesMixin.messages` is still
  empty. `_RequestContextSetup.setup_context` will also store the raw `request.messages`, and `AppModule` will expose
  them under a new DI alias, `REQUEST_MESSAGES`, next to `DIAL_API_KEY` and `TOOL_CHOICE` in `common/_di_types.py`.
  An initializer rather than a transformer is deliberate: `SkillsRegistry` caches its merge on first call, and that
  call comes from `_AddSystemPromptTransformer`, so populating the provider from another transformer would depend on
  transformer ordering.
- **Change.** A new initializer and the `REQUEST_MESSAGES` alias. `DialSkillResolver` is used as it is.

### 3. Registration — an ordinary skill, under its own name

- **What.** `_InvokedSkillsContext` is an ordinary `SkillsProvider`, like `_DialSkillsContext`, with
  `display_name = "user skills"` and:

  ```python
  order = -10
  ```

- **Owner.** `quickapp/skill_invocation/`.
- **Semantics.**
  - The skills it returns are the resolved skills **as resolved**: the manifest's own `name` and `description`, the
    real `url`, `files` and reader. The only change is one line prepended to `content`, naming the skill as
    user-selected so the model can tell it apart from the agent's own when the user refers to it in words.
  - `order = -10` puts it ahead of every agent source (agent/predefined `0`, dial-prompt `10`, dial-skill `20`), so a
    picked skill **wins** a name collision: it is the one listed, and the one `read_skill` returns. The agent's
    same-named skill is dropped and reported by the existing `SkillsRegistry` collision path. See
    [UC-5](#uc-5-the-users-skill-has-the-same-name-as-one-of-the-agents) and [Known Gaps](#known-gaps).
  - **There is no uniqueness scheme in 1a, and no new collision logic.** A picked skill is named by its own manifest,
    like every other skill, and the two kinds of clash are settled in two different places that both already exist:

    | Clash | Settled by | Winner |
    |---|---|---|
    | A pick vs. an agent's skill | `SkillsRegistry._get_merged`, by provider `order` | The pick (`order = -10`) |
    | A pick vs. another pick | `DialSkillResolver.resolve`'s name dedup, **before** the provider is populated | The **oldest** pick — the resolver keeps the first occurrence, and step 5 hands it the list oldest-first |

    The second row is the one worth reading twice: two picks live in the *same* provider, so the registry never sees
    the loser. `DialSkillResolver` drops it and emits `Duplicate skill name '<name>'; keeping first occurrence`, which
    reaches "Initialization issues" with the resolver's wording rather than the registry's, and does so on **every**
    turn — the *Reporting* rule below cannot suppress it, because the exception is produced inside the resolver and
    flows straight into the context's exception list.

    Three further consequences follow, all **accepted** for 1a:

    - The dropped pick's URL is not among the URLs that resolved, so the injector's table classifies it as *failed to
      resolve* and the model is told it could not be loaded. That is misleading about the cause but correct about the
      outcome: the skill genuinely is not available to the model.
    - A user who re-picks a same-named skill from a different URL keeps the **older** one.
    - That re-pick produces **nothing at all** — no pair, no stage, no error. Its chip derives the same
      `{"skill_name": "<name>"}` arguments as the first pick, so the skip check in concern 4 matches the earlier
      pair and skips it before anything is reported.

    **All three are unreachable under the assumption this phase rests on: picked skills have names that don't clash.**
    It is the user's to keep, nothing enforces it, and 1b removes the need for it. Reporting the duplicate distinctly
    was considered and rejected — see [Alternatives](#alternatives-considered).
  - Everything downstream then works unchanged, which is the point of registering rather than special-casing:
    - the `SkillsRegistry` merge sees one more provider;
    - `generate_skills_xml` renders the skill like any other;
    - `read_skill("sql-style", …)` is the same dictionary lookup;
    - bundled files are read by `skill.url` through `DialSkillReader.read_bundled_file`, which the entry keeps.
- **Change.** The provider class. No change to `SkillsRegistry`, `generate_skills_xml`, `read_skill` or
  `_SkillReaderStageWrapper`.

### 4. Injection — `_SkillInvocationInjector`

- **What.** A `MessagesTransformer` in `quickapp/skill_invocation/`. It inserts one synthetic `read_skill` call and
  result per distinct chip on the last user message.
- **Owner.** `quickapp/skill_invocation/`.
- **Semantics.**
  - **When.** When `_InvokedSkillsContext` recorded chips for this turn (concern 2, step 5) — **not** by re-reading
    the messages. The scrub transformer belongs to `SkillsModule`, which `app_factory` registers ahead of this
    module, so by the time the injector runs the messages no longer carry `custom_content.skills` at all. The
    insertion point is still taken from the messages: the index after the last `USER` message.

    Earlier invocations need nothing: the pair was inserted after the user message of its turn, `Orchestrator`
    persists everything after the last user message into `state.tool_execution_history`, and
    `_MessagesSetup.extract_tool_calls` restores it. Acting on every historical chip would duplicate them.
  - **A pair already in history is not injected again.** A chip is skipped when the conversation already holds a pair
    for the same tool and arguments, matched on the call-id prefix that `make_synthetic_call_id_prefix` builds from
    the tool name and arguments. It needs no content, so `read_skill` is not run for a re-pick at all: no stage is
    shown for a result that would be thrown away, and a request never carries two pairs sharing a `tool_call_id`.

    The manifest the model reads therefore stays the one from the turn that first picked the skill, even if the user
    edits the skill afterwards. That is how every other tool result behaves, and it keeps history consistent with what
    the model has already seen (goal 3).
  - **Where.** Directly after that user message, in chip order. The explicit index keeps the pairs ahead of any
    transformer that appends to the end (`_TimestampInjectionTransformer`, `_AttachmentNotificationInjector`),
    whatever the module order.
  - **What.** For each chip:

    | Case | Tool call | Tool result |
    |---|---|---|
    | The skill resolved | `read_skill({"skill_name": "<name>"})` | The result of actually running `read_skill`: the header line, the manifest and `<skill_files>` |
    | Failed to resolve, or over the cap | `read_skill({"skill_name": "<name>"})` | ``Error: the user's skill `<name>` could not be loaded. The reason is shown to the user.`` |

    For a resolved chip `<name>` is the manifest's name. For a failed one the skill has no manifest, so the URL's last
    segment is used — it is what the name would almost certainly have been, and it gives the model something to name
    in its apology.

    The failure result is a fixed sentence on purpose. The resolver's reason is operator detail — for example
    `Skill validation failed for 'skills/<bucket>/…'` from `parse_frontmatter` — which belongs in the "Initialization
    issues" stage and the logs, where the user can act on it. Feeding a varying, internals-shaped string to the model
    gives it something to improvise on; a fixed sentence keeps its reaction predictable.
  - **How.** For a resolved chip the injector looks up the `read_skill` `StagedBaseTool` by its function name — the
    **lookup only** follows `StagedToolSyntheticInjector` — and runs it through `arun`. Because the skill is
    registered (concern 3), the result is byte-identical to a model-initiated call, `<skill_files>` included.

    > `StagedToolSyntheticInjector.get_content` forces `stage_level=StageDisplayLevel.DEBUG`, which suppresses the
    > stage for a normal app. Copying that call verbatim would make UC-1's "Reading Skill" stage silently never
    > appear. `arun` must be called **without** `stage_level`, so it defaults to `INFO` as it does in
    > `tool_executor.py` — the invocation is something the user did, so its stage belongs in the response.

    For a failed chip the injector writes the pair itself, and there is no stage.
  - **Scrubbing lives elsewhere.** Removing `custom_content.skills` from the working copy is **not** this
    transformer's job: it belongs to a small transformer in `SkillsModule`, which is never preview-gated. The
    orchestrator LLM and any DIAL deployment tool that forwards the conversation don't need the field, and forwarding
    it makes Core share the user's skill folders with those deployments too — a leak that must not depend on whether
    the preview flag is on. Messages carrying the field are copied, not edited: the working list shares objects with
    the request's own messages.

    The two transformers need no ordering between them, because the injector takes this turn's chips from the context
    (concern 2, step 5) rather than re-reading the messages.
  - **Reporting.** Every historical pick is resolved again on every turn, so reporting everything every turn would
    repeat the same issues until the conversation ends. Only problems with the chips of the **last** user message are
    recorded as `SkillInitializationException` and shown in "Initialization issues"; problems with older picks are
    logged. The model learns about a failed chip from its error result. **No path fails the request.**
- **Change.** A new transformer. `build_synthetic_pair`, `make_synthetic_call_id` and `make_synthetic_call_id_prefix`
  in `common/synthetic_injection/` become public module-level helpers, so a multi-call injector can reuse them without
  subclassing `SyntheticToolCallInjector` — that base class assumes one tool call per transformer.

---

## Out of Scope

- **Phase 1b: collision-free names.** [Below](#follow-up-phase-1b--collision-free-names).
- **Phase 2: letting the user pick the agent's own skills.** It needs a way for the client to list them. One
  constraint is already known: Core rejects a `custom_content.skills` entry without a `url` with `400`, so a name-only
  reference can't go in that array.
- **Picking `prompts/` URLs.** Core accepts only `skills/` resources in the field. Declared `prompts/` skills are used
  by the model as today.
- **A per-message cap.** One cap is enough: the conversation cap already bounds how many skills are fetched and
  listed, and it is spent newest-first, so the current turn's chips are never dropped in favour of older ones.
- **A per-app switch to disable invocation.** Access is capped by the user's own reach. A `features.skill_invocation`
  toggle can be added if an app author asks for one.
- **Autoloading the user's skills.** Implicit, every-turn skill loading has its own access and prompt-budget story.
- **Argument templating** (`$ARGUMENTS` in the manifest). The message text is the argument. Templating would rewrite
  skill content per invocation and break the "history is what the model saw" property.
- **Enforcing `allowed-tools`.** Unchanged: still advertised in the XML and never enforced.
- **Lazy resolution of older invocations.** Today every picked skill in the conversation is resolved every turn,
  bounded by the cap. Resolving only on a `read_skill` miss would remove that cost but needs an async path through the
  registry merge.

---

## Configuration / Usage Examples

### Picking a personal skill — turn 1

```jsonc
{
  "messages": [
    {
      "role": "user",
      "content": "/code-review the diff in the attachment, focus on auth",
      "custom_content": {
        "attachments": [{ "type": "text/x-diff", "url": "files/<bucket>/pr-812.diff" }],
        "skills": [{ "url": "skills/<user-bucket>/code-review" }]
      }
    }
  ]
}
```

What the orchestrator LLM receives, when the agent also has its own `code-review`:

```text
system    … <available_skills>
              <skill><name>code-review</name><description>How I want my code reviewed</description></skill>
            </available_skills> …     ← the user's; the agent's was dropped (UC-5)
user      /code-review the diff in the attachment, focus on auth
assistant tool_calls: read_skill {"skill_name": "code-review"}
tool      Skill `code-review`, selected by the user for this conversation.
          ---\nname: code-review\n… \n<skill_files>\nreferences/checklist.md\n</skill_files>
```

The user sees the stage "Reading Skill: code-review", and an "Initialization issues" note that the agent's
`code-review` was superseded.

### Turn 2

The client resends turn 1, with `custom_content.skills` still on the first user message, then the new user message.
QuickApps restores the turn-1 pair from assistant state, resolves and registers the picked skill again under the same
name so its files stay readable, and injects nothing new unless the new message carries its own chips.

### Limits

| Variable | Default | Purpose |
|---|---|---|
| `SKILL_INVOCATION_MAX_SKILLS` | `10` | Distinct picked skills resolved and listed per request across the conversation, newest first. Each one adds a `<skill>` block to the system prompt on every turn and one Core fetch per turn. The fetches are parallel, so this is a prompt budget and a Core-load budget more than a latency one |
| `DIAL_SKILLS_FILE_MAX_BYTES` | `262144` | Reused unchanged for the manifest and each bundled file |

### Failure modes

| Condition | Result |
|---|---|
| No chips anywhere | Exactly as today, system prompt included; no extra Core calls |
| `ENABLE_PREVIEW_FEATURES=false` | The module is unregistered, so a chip is not resolved, registered or injected, and neither the user nor the model is told. The scrub still runs, because it lives in the never-gated `SkillsModule`, so the field does not reach the orchestrator deployment either way |
| Malformed entry, absolute URL, or not a `skills/` resource | Core rejects the request with `400`; QuickApps never sees it |
| Picked skill deleted (user's own, or public) | Error result on the invoking turn; on later turns it isn't registered and its name returns "not found" |
| Picked skill shared with the user, share later revoked | Core rejects the request with `403`, on every later turn of that conversation (Known Gaps) |
| Invalid or over-cap `SKILL.md` | Fixed error result for the model; the reason in "Initialization issues"; not registered |
| Picked skill has the same `name` as an agent skill | The user's wins and the agent's is dropped and reported (UC-5) |
| Two picked skills share a `name` | Decided by `DialSkillResolver`'s name dedup, not the registry — the **oldest** pick wins, the other is dropped with `Duplicate skill name …`, reported every turn |
| The same manifest `name` picked from two different URLs | The older pick stays. The newer chip derives identical `read_skill` arguments, so the skip check matches the older pair and the re-pick produces no pair, no stage and no error. Accepted: unreachable under the non-clashing-names assumption (concern 3) |
| Picked URL the app also declares | Same content, one entry; the user's copy wins by order |
| The same skill picked again later | Moves to the end of the user skills in the list; never dropped by the cap on the message that picks it; no new pair is injected and no stage is shown |
| The user edits a picked skill mid-conversation | The model keeps the manifest from the turn that first picked it; a later `read_skill` of a bundled file returns the current file |
| Identical chips on one message | Counted once: one pair, one entry |
| Over `SKILL_INVOCATION_MAX_SKILLS` in the conversation | The oldest picks stop being registered; their manifests stay in history; their names return "not found" |
| A dropped pick's files are read later | Its turn-1 manifest is still in history advertising `<skill_files>`, but its name no longer resolves, so `read_skill(name, path)` answers "not found" with no explanation of why. A rough edge of the cap, not engineered around |
| DIAL Core outage | Every picked skill gets an error result or drops out; the agent's own skills are unaffected; request served |

---

## Known Gaps

### A picked skill shadows the agent's same-named skill

`order = -10` means a user's pick replaces an agent skill of the same name for the whole conversation — including a
**predefined** skill the app author considers part of the product. The collision is reported in "Initialization
issues", so it is visible, but the author cannot prevent it and the user may not realise what they displaced.

**Accepted for 1a**, and it rests on one assumption stated plainly: **picked skills must have names that do not
clash with the agent's.** Nothing enforces it in this phase. A user who breaks it silently loses the agent's skill of
that name for the conversation.

The alternative orders are worse. At `order = 30` the agent wins instead, and the synthetic pair would inject the
agent's skill while the user picked their own — silently doing the wrong thing on the one action the user took
explicitly. An order that spares predefined skills but not declared ones (`order = 5`) was considered and rejected as
a half-measure: it splits the rule in two without removing the clash. Phase 1b removes the need for the assumption
altogether by giving picked skills names that cannot collide.

A second consequence of registering the skill as resolved: its `description`, `license`, `compatibility`,
`allowed-tools` and arbitrary `metadata` are rendered into `<available_skills>` by `generate_skills_xml`, so a picked
skill puts user-controlled text into the system prompt, the channel the app author owns — the `description`
unbounded. Accepted as it stands: the manifest body already reaches the model as a tool result either way, and the
number of picked skills is capped. Nothing is trimmed in 1a; 1b revisits it, where a picked skill stops being listed
under its own identity at all.

### A revoked share breaks the conversation

Core rejects a request with `403` when any `custom_content.skills` URL in it is unreadable by the user, the same
fail-closed rule it applies to attachments. The client resends the whole history every turn, so a skill that was
shared with the user and then unshared makes **every later turn** of that conversation fail, not just the turn that
picked it. The user's own skills and public skills are not affected: the user can always read their own bucket, and
Core doesn't check public skills. A deleted skill of either kind passes Core and becomes an ordinary QuickApps error
result.

QuickApps can't work around this, because the request never reaches it. The fix belongs in Core: skip an unreadable
skill reference instead of failing the request, and let QuickApps report it like any other skill it can't load. Until
then the user's only way out is to start a new conversation.

---

## Alternatives Considered

| Alternative | Why not |
|---|---|
| **A collision-free derived name now** (`user:<name>:<hash>`) | It is phase 1b. It needs a listed-name format, a trimmed metadata copy, a stage-title parser so the user doesn't read a hash, and the resolver's name-dedup turned off. None of it is needed to make `/skill-name` work, and the clash it prevents is one we are willing to assume away for now |
| **The agent's skill wins instead** (`order = 30`) | The synthetic pair addresses the skill by name, so it would inject the agent's skill while the user picked their own — silently wrong on the one action the user took explicitly |
| **Register the skill for reads but keep it out of `<available_skills>`** | Keeps user-controlled text out of the system prompt, but `SkillsRegistry` builds the XML and the lookup table in one pass, so it needs a new `listed` flag on `SkillsProvider` — a special case for one provider, against goal 7. The model also can't see that it has the skill |
| **A separate `read_user_skill` tool** | Sidesteps naming entirely and allows lazy resolution, but adds a second skill-reading tool to every preview app's tool list and two mental models for "read a skill" |
| **Only list the picked skill, without injecting it** | Not deterministic (goal 1): the model decides whether to read it |
| **Report a duplicate-name pick distinctly** (a field separating "dropped as a duplicate" from "failed to load") | Does not actually surface it: both picks derive the same `{"skill_name": "<name>"}` arguments, so the skip check still matches the earlier pair. Bypassing the skip would write a "could not be loaded" pair directly after one that loaded the same name fine — contradictory history for the model, for a case the non-clashing-names assumption rules out |
| **`unique_names=False` on the resolver, letting the registry settle pick-vs-pick** | Would make clash behaviour coherent and is only ~9 lines, but reopens `dial_skills/` — the one thing that keeps this phase to "add a provider". Deferred to 1b, which needs the flag anyway |
| **Only inject, without registering** | The manifest reaches the model, but bundled files are unreadable and the model can't see it has the skill (goals 4 and 7) |
| **Persist name/description/files in choice state and skip the per-turn fetch** | Would remove the re-resolution, but `ResolvedSkill.content` is an eager `str`, so `get_skill_content` would need a lazy path — a change to the skills contract, against goal 7. The fetches are already parallel (`asyncio.gather` in `DialSkillResolver`), so the saving is Core load, not latency |
| **Inline the manifest into the user message every turn** | Re-fetches and re-inlines on every turn. If the skill is edited, earlier turns silently change, so history stops matching what the model saw. The synthetic pair freezes the manifest as it was when invoked |
| **Parse `/name` from the text** | A name carries no access, so a personal skill still couldn't be read, and it is ambiguous among the user's same-named skills |
| **Request-level `custom_fields.skills.invoked`** | An invocation belongs to a turn. A request-level field only describes the latest turn and is gone from history once the next message is sent, so Core can't re-share the skill and its files become unreadable |
| **Send the skill as a `custom_content.attachments` entry** | Works with no Core change, but when the user switches models mid-conversation every other deployment would see a `skills/` URL as a file attachment, and QuickApps would have to filter it out of its own attachment pipeline |

---

## Follow-up: phase 1b — collision-free names

Tracked separately; sketched here so 1a's boundary is legible. 1b stops a picked skill from shadowing the agent's, so
both stay listed and reachable, and the app author's product is never displaced by a user's pick.

What it adds, none of which 1a needs:

| Addition | Why |
|---|---|
| A derived listed name (`user:<name>:<hash>` or similar) | Unique by construction: a valid skill name is `[a-z0-9-]` and never contains `:`, so a picked skill can never take an agent skill's name, and two picks from different buckets differ by hash |
| A trimmed metadata copy | Once the entry is listed under a name of QuickApps' making, `license`, `compatibility`, `allowed-tools` and `metadata` should not ride along into the author's system prompt, and the description wants a hard cap |
| `DialSkillResolver.resolve(unique_names=False)` | Two picked skills may share a manifest `name`; both are legitimate once each is listed under a derived name |
| A stage-title parse | So the user reads `code-review (user skill)`, not `code-review:3f9a2c` |
| `order` becomes irrelevant | With no possible collision there is nothing for precedence to decide |

1b is additive: the wire contract, the resolution walk, the injection, the scrub and the failure handling all stay,
and the injector's `skill_name` argument switches from the manifest name to the derived one.

---

## Migration

### Breaking changes

None for existing apps. Within the feature, 1b changes the name a picked skill is listed under, which changes the
system prompt and the synthetic call arguments for conversations in flight; a conversation started under 1a keeps its
turn-1 pair under the old name, so its bundled files stop resolving after the upgrade. Acceptable while the feature is
preview-gated.

### Non-breaking changes

- Requests without `custom_content.skills` behave exactly as today, system prompt included: no new Core calls, no new
  messages, no change to `<available_skills>`.
- The package is gated by `@preview_module`, matching `DialSkillsModule`, whose `DialSkillResolver` it reuses.

## Summary of Changes

### `quickapp/skill_invocation/` (new)

- `_skill_reference.py` — `SkillReference(url)`; parses `custom_content.model_extra["skills"]` from user messages,
  canonicalises the URL, dedupes keeping the latest occurrence, applies the conversation cap.
- `_invoked_skills_context.py` — `_InvokedSkillsContext(SkillsProvider)`, `order = -10`,
  `display_name = "user skills"`. Holds the resolved skills as resolved, with one header line prepended to `content`,
  the set of URLs that resolved, this turn's chips, and the exceptions for them.
- `_skill_invocation_initializer.py` — `_SkillInvocationInitializer(CompletionInitializer)`: collect newest first,
  dedupe, cap, delegate to `DialSkillResolver`.
- `_skill_invocation_injector.py` — `_SkillInvocationInjector(MessagesTransformer)`: synthetic `read_skill` pairs for
  this turn's chips via the real tool, a fixed error result for failed ones, failure reporting. No scrubbing.
- `_settings.py` — `SkillInvocationSettings` (`SKILL_INVOCATION_MAX_SKILLS`).
- `skill_invocation_module.py` — `@preview_module`; multiproviders for `CompletionInitializer`, `SkillsProvider`,
  `MessagesTransformer`, `InitializationException`. Registered in `app_factory.py` after `DialSkillsModule`.

### `quickapp/common/`

- `_di_types.py` — `REQUEST_MESSAGES`.
- `synthetic_injection/synthetic_tool_call_injector.py` — `build_synthetic_pair`, `make_synthetic_call_id` and
  `make_synthetic_call_id_prefix` as public module-level helpers; the class keeps using them.

### `quickapp/core/application/`

- `_request_context.py`, `_request_context_setup.py`, `app_module.py` — store the raw request messages in
  `setup_context` and provide them as `REQUEST_MESSAGES`.

### `quickapp/skills/`

- `_scrub_skill_chips_transformer.py` (new) — a `MessagesTransformer` that removes `custom_content.skills` from the
  working copy, registered by `SkillsModule`. It lives here, not in `skill_invocation/`, because `SkillsModule` is
  never preview-gated and the field must not reach the orchestrator deployment even with the feature off.
- `skills_module.py` — register that transformer.

Nothing else here changes: no name helpers, no listed-name format, no stage-title change.

### Unchanged

`quickapp/dial_skills/` is not touched — `DialSkillResolver` keeps its signature and its name-dedup. That is goal 7,
and it is what 1b will start changing.

### Outside this repo

- `ai-dial-core` — done in #1956 for chat completions. Follow-up request: skip an unreadable skill reference instead
  of rejecting the request (Known Gaps).
- `ai-dial-chat` — `skills?: SkillRefDto[]` on `MessageCustomContentDto` (`forbidNonWhitelisted` rejects it today),
  the `/` palette of the user's own skills, and the skill chip. `content` is sent as typed, `/name` token included.
- `aidial-sdk` (optional) — a typed `CustomContent.skills`.
- `docs/skills.md` — document invocation, the wire field and the limits once implemented.
