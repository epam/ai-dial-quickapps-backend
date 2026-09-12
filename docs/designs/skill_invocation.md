# Design: Invoking a Skill from a Message

- **Status:** Approved
- **Issue:** [epam/ai-dial-quickapps-backend#549](https://github.com/epam/ai-dial-quickapps-backend/issues/549), a
  sub-issue of [#421](https://github.com/epam/ai-dial-quickapps-backend/issues/421) ([EPIC] Advanced Agent Skills
  support)
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

Bringing the user's skills in must not create a third problem: **two skills with the same name**. A skill is
identified only by its name, which is unique within an agent today. A user's `code-review` next to the agent's
`code-review` would leave the model unable to say which one it means.

DIAL Core and DIAL Chat have agreed on a wire contract that closes the access half: a user message may carry
`custom_content.skills[*]`, and Core auto-shares each referenced skill to the app's per-request key, as it already
does for `custom_content.attachments[*]`. This design specifies how QuickApps consumes that field.

## Design Goals

1. A skill the user picks is **always** loaded into the model's context on that turn. The model doesn't choose.
2. The user can pick any skill they can read from their own catalog: their own, one shared with them, or a published
   one. It doesn't need to be in the app config.
3. A picked skill stays usable for the rest of the conversation: the model sees it in `<available_skills>`, and its
   bundled files stay readable through `read_skill`.
4. **Every name in `<available_skills>` stays unique**, so the model always gets exactly the skill it names. A picked
   skill never takes an agent skill's name, and there is no precedence rule between the user's skills and the
   agent's.
5. The model is never shown the user's bucket id.
6. A chip on the current message that fails is visible to both the user and the model. The request is still served.
7. The skills contract doesn't change: `<available_skills>` keeps `name` and `description`, and `read_skill` keeps
   its parameters. Requests that don't carry the field behave exactly as today, system prompt included.
8. The change is as small as possible: the existing skills merge, XML generator and `read_skill` tool stay as they
   are.

## Phasing

- **Phase 1 — this design.** The client knows only the user's skills. It lists them in the `/` palette and sends the
  one the user picks as a URL reference (a chip). The agent's own skills, declared or predefined, stay exactly as
  today: only the agent invokes them. A user who wants one asks for it in words ("use the release-notes skill"), and
  the model reads it from `<available_skills>` as it would anyway.
- **Phase 2 — to be designed** ([#550](https://github.com/epam/ai-dial-quickapps-backend/issues/550)). The user can
  pick the agent's own skills too. How the client learns about them is left for that design.

---

## Use Cases

### UC-1: Picking a personal skill from the palette

**Trigger:** The user picks their own `skills/<user-bucket>/sql-style` from the palette.
**Behavior:** Chat sends `content: "/sql-style …"` with `custom_content.skills: [{url: "skills/<user-bucket>/sql-style"}]`.
Core auto-shares the skill to the per-request key. QuickApps resolves it through `DialSkillResolver`, lists it in
`<available_skills>` as `user:sql-style:<hash>`, and inserts a synthetic `read_skill` call and result for that name
after the user message.
**Outcome:** The model starts its turn with the skill's manifest already in context. The response shows a
"Reading Skill: sql-style (user skill)" stage. From this turn on, the skill is listed and its bundled files are
readable.

### UC-2: Asking for one of the agent's own skills

**Trigger:** The agent has an `acme-release-notes` skill. The palette doesn't offer it, so the user writes "use the
release notes skill for 0.9.0".
**Behavior:** Nothing new. The message carries no `custom_content.skills`, and QuickApps doesn't parse the text. The
skill is in `<available_skills>` as today, and the model decides whether to call `read_skill`.
**Outcome:** Same as today: the model normally reads the skill it was asked for, but that isn't guaranteed. Guaranteed
invocation of the agent's own skills is phase 2.

### UC-3: Reading a bundled file three turns later

**Trigger:** On turn 4 the model calls `read_skill("user:sql-style:<hash>", "references/naming.md")` for a skill picked
on turn 1, using the name it sees in `<available_skills>` and in the turn-1 synthetic call.
**Behavior:** The turn-1 user message still carries the reference, so Core shares the skill again and QuickApps
resolves and lists it again under the same name. The manifest itself is not re-injected: it comes back from the
turn-1 assistant state like any other tool result.
**Outcome:** The file is returned. The conversation history is byte-identical to what the model saw on turn 1.

### UC-4: The picked skill can't be loaded

**Trigger:** The skill was deleted, or its manifest is invalid.
**Behavior:** The synthetic pair is still inserted, with an error result that names the skill and says it could not
be loaded. The reason is reported to the user in the "Initialization issues" stage. The skill is not listed.
**Outcome:** The model knows the user asked for a skill it doesn't have, and says so. The rest of the answer is
produced normally.

### UC-5: The user's skill and the agent's skill share a name

**Trigger:** The agent has `code-review`. The user picks their own `skills/<user-bucket>/code-review` from the
palette.
**Behavior:** Both are listed: the agent's as `code-review`, the user's as `user:code-review:3f9a2c`, each with its
own description. The synthetic read uses the user's name, and the injected content itself starts with that name and
how to read the skill's files. Later, `read_skill("code-review")` returns the agent's skill, because that is what
`code-review` means in the list; the user's is read by its own name. When the user asks for "my code-review" in words,
the model sees which entry is the user's.
**Outcome:** Both skills stay usable for the whole conversation, and the model always gets exactly the one it named.
Nothing is shadowed, and nothing depends on which skill "wins".

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
    QA->>QA: user skills provider - list each one as user:name:hash
    QA->>QA: injector - chips of the last user msg become synthetic read_skill pairs
    QA->>QA: strip custom_content.skills from the working copy
    QA->>LLM: system prompt with available_skills + history + synthetic pairs
    LLM-->>QA: answer
    QA-->>Chat: answer + state.tool_execution_history (includes the pair)
```

The design has four concerns.

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
  - The URL has **no trailing slash**: `skills/<bucket>/<path>`. Core shares exactly that URL, and it authorises every
    read of the skill (`SKILL.md` and each bundled file) against it, so one share covers the whole skill. A URL
    ending in `/` would be shared under a different key, and every read of the skill would then be denied.
  - The field is **per message**, not per request. An invocation belongs to the turn it was made on. Because it stays
    on that message, Core re-shares the skill on every later turn while the client keeps resending the history (UC-3).
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
     canonicalised by stripping a trailing `/`. The canonical URL is what the listed name is derived from, so it must
     be the same on every turn. Identical chips on one message count once. On each message only the first
     `SKILL_INVOCATION_MAX_PER_MESSAGE` distinct chips count; the rest are never resolved or listed, and the injector
     gives them an error result (concern 4).
  2. Deduplicate, keeping each URL's **latest** occurrence: that is what decides its position. The chips of the last
     message are therefore always the newest picks and are never dropped by the cap in step 4. A skill picked again
     later moves to the end of the user skills in `<available_skills>`, which changes the system prompt once, like any
     new pick.
  3. Reject a URL that isn't under `skills/`. Core already answers such a request with `400`, so this is only a
     defensive check.
  4. Keep the newest `SKILL_INVOCATION_MAX_SKILLS` distinct URLs. The cap drops the oldest picks. A dropped pick's
     manifest is still in history, but it is no longer listed or readable.
  5. Wrap each URL in a `DialSkillConfig` and hand the list to the existing `DialSkillResolver`, with its
     duplicate-name check **off** (`unique_names=False`). Two picked skills with the same `name` (the user's and an
     organisation's, say) are both legitimate: they are listed under different names (concern 3). Manifest parsing,
     `<skill_files>`, byte caps, per-URL failure isolation and warning severities all come for free.
  6. Store the resolved skills by position, oldest first, and a failure reason per URL for the ones that didn't
     resolve.
- **No dedup against the app config.** A picked URL that the app also declares is resolved again and listed as a
  user skill next to the agent's entry. It is the same content under two names. That costs one extra fetch in a rare
  case and needs no merging logic.
- **Where it gets the messages.** Initializers run **before** `setup_messages`, so `MessagesMixin.messages` is still
  empty. `_RequestContextSetup.setup_context` will also store the raw `request.messages`, and `AppModule` will expose
  them under a new DI alias, `REQUEST_MESSAGES`, next to `DIAL_API_KEY` and `TOOL_CHOICE` in `common/_di_types.py`.
- **Change.** A new initializer. `DialSkillResolver.resolve` gains `unique_names: bool = True`; the existing caller
  keeps the default.

### 3. Registration — listed as `user:<name>:<hash>`

- **What.**
  - `_InvokedSkillsContext` is an ordinary `SkillsProvider`, like `_DialSkillsContext`: `order = 30`,
    `display_name = "user skills"`.
  - Its `resolved_skills` are trimmed copies of the resolved skills, listed under a **listed name**:

    ```
    user:<name>:<hash>
    ```

    `<name>` is the last segment of the canonical URL, and `<hash>` is the first six hex characters of the SHA-256 of
    the canonical URL. Both come from the URL alone, so the listed name is known before the skill resolves, and is the
    same whether it resolves or not.
  - The copy differs from the resolved skill in three ways; `url`, `files` and the file reader stay as resolved:
    - `metadata` keeps only `name` (the listed name) and `description`, cut hard at 1024 characters. `license`,
      `compatibility`, `metadata` and `allowed-tools` are dropped, so they never reach the system prompt.
    - `content` starts with one line that names the skill the way the model must address it:
      ``Skill `user:code-review:3f9a2c`, selected by the user. Read its files with
      `read_skill("user:code-review:3f9a2c", <path>)`.`` The manifest itself still says `name: code-review`, and without
      this line a model could read a bundled file by that bare name and get the agent's file instead.
  - Two small helpers in `quickapp/skills/` own the format. `make_user_skill_name(url)` builds the listed name.
    `parse_user_skill_name(listed) -> str | None` strips the `user:` prefix and the trailing `:<6 hex>`, so a `:`
    inside the name survives, and returns the name or `None`. The provider and the injector use the first; the stage
    title (Secondary Fixes) uses the second.
- **Owner.** `quickapp/skills/` for the name format; `quickapp/skill_invocation/` for the provider.
- **Semantics.**
  - Everything downstream works as it does today, because the listed name is just a name:
    - the `SkillsRegistry` merge sees one more provider;
    - `generate_skills_xml` renders `<name>user:code-review:3f9a2c</name>` and the description, as for any skill;
    - `read_skill("user:code-review:3f9a2c", …)` is the same dictionary lookup as for any skill;
    - bundled files are read by `skill.url` (`DialSkillReader.read_bundled_file`), which the copy keeps, and
      file-level errors name the skill by its listed name.
  - **Unique by construction.** A valid skill name is `[a-z0-9-]` and never contains `:`, so a listed user name can't
    equal a valid agent skill's name. Two picked skills from different buckets get different hashes, even when their
    paths end the same. A six-character hash collision among at most ten picks is practically impossible; if one
    happens, the existing merge keeps the older entry and reports the other as a collision, as it does for any
    duplicate name.
  - **Stable across turns.** The listed name depends only on the canonical URL, so it is the same on every turn, with
    no stored state. It doesn't change when the user edits the skill's `name` in `SKILL.md`, and it doesn't shift when
    an older pick drops out of the cap.
  - **No bucket id.** The model sees the skill's path segment and a hash. The URL, and the bucket in it, never reach
    the model.
  - **The `user:` prefix helps the model.** When the user asks for "my code-review" in words, the model can tell which
    entry is the user's.
- **Why list the user's skills in the system prompt.** The model can only choose between two same-named skills if it
  can see both, with their descriptions, in one place. The cost: `<available_skills>` grows on the turn a skill is
  first picked, so that request misses the prompt cache, and later turns are stable until the next pick. The client
  never sees the system prompt; QuickApps rebuilds it on every request (`_AddSystemPromptTransformer`), as it already
  does when a declared skill's description changes.
- **Change.** The two helpers and the trimmed copy.

### 4. Injection — `_SkillInvocationInjector`

- **What.** A `MessagesTransformer` in `quickapp/skill_invocation/`. It inserts one synthetic `read_skill` call and
  result per distinct chip on the last user message.
- **Owner.** `quickapp/skill_invocation/`.
- **Semantics.**
  - **When.** It acts only when the **last** message is a user message that carries chips. Earlier invocations are
    already in history: the pair was inserted after the user message of its turn, and `Orchestrator` persists
    everything after the last user message into `state.tool_execution_history`. `_MessagesSetup.extract_tool_calls`
    restores it on the next turn. Acting on every historical chip would duplicate them.
  - **A pair already in history is not injected again.** Identical chips on one message count once (concern 2), and a
    chip is skipped when the conversation already holds a pair for the same tool and arguments. The check matches the
    call-id prefix that `_make_call_id_prefix` builds from the tool name and the arguments, which for a picked skill
    derive from the canonical URL alone. It needs no content, so `read_skill` is not run for a re-pick at all: the
    user sees no "Reading Skill" stage for a pair that would be thrown away, and a request never carries two pairs
    sharing a `tool_call_id`, nor two pairs with the same arguments and different content.

    The manifest the model reads therefore stays the one from the turn that first picked the skill, even if the user
    edits the skill afterwards. That is how every other tool result in the history behaves, and it keeps the history
    consistent with what the model has already seen.
  - **Where.** It inserts directly after that user message, in chip order. The explicit index keeps the pairs ahead
    of any other transformer that appends to the end (`_TimestampInjectionTransformer`,
    `_AttachmentNotificationInjector`), whatever the module order.
  - **What.** For each chip:

    | Case | Tool call | Tool result |
    |---|---|---|
    | The skill resolved | `read_skill({"skill_name": "user:<name>:<hash>"})` | The result of actually running `read_skill`: the one-line header, the manifest and `<skill_files>` |
    | Failed to resolve, rejected, or over a cap | `read_skill({"skill_name": "user:<name>:<hash>"})` | ``Error: the user's skill `user:<name>:<hash>` could not be loaded. The reason is shown to the user.`` |

    The listed name comes from the URL (concern 3), so a failed chip is named exactly as it would have been listed.
    The failure result is a fixed sentence on purpose. The resolver's reason can contain the skill URL, for example
    `Skill validation failed for 'skills/<bucket>/…'` from `parse_frontmatter`, so it goes to the "Initialization
    issues" stage and the logs, where the user seeing their own bucket is fine, and never to the model.

  - **How.** For a resolved chip, the injector looks up the `read_skill` `StagedBaseTool` by its function name, the
    same way `StagedToolSyntheticInjector` does, and runs it through `arun`. The result is then byte-identical to what
    a model-initiated call returns, and the user sees the tool's normal stage at the app's `stage_display_level`, not
    DEBUG, because the invocation is something the user did. For a failed chip, the injector writes the pair itself:
    there is no "Reading Skill" stage, only the "Initialization issues" one.
  - **Scrubbing.** The same transformer removes `custom_content.skills` from every message in the working copy. The
    orchestrator LLM and any DIAL deployment tool that forwards the conversation don't need it. Forwarding it would
    make Core share the user's skill folders with those deployments too.
- **Change.** A new transformer. `_build_pair`, `make_call_id` and the call-id prefix helper in
  `common/synthetic_injection/` become public module-level helpers, so a multi-call injector can reuse them without
  subclassing `SyntheticToolCallInjector`. That base class assumes one tool call per transformer.

---

## Secondary Fixes

### Stage title shows the user skill's short name

`_SkillReaderStageWrapper._get_stage_title_from_params` titles the stage with the raw `skill_name` argument, which
would show `Reading Skill: user:code-review:3f9a2c`. When `parse_user_skill_name` recognises the argument, the title
uses the `<name>` part and marks it: `Reading Skill: code-review (user skill)`, or
`Reading Skill: code-review/references/checklist.md (user skill)` for a bundled file. It is a string parse, with no
registry access, and it applies to model-initiated reads of user skills as well as the synthetic one. An agent skill
whose name happens to have the same shape, which only an invalid name can, would be titled the same way.

### Reporting

Every historical pick is resolved again on every turn, so reporting everything every turn would repeat the same
issues until the conversation ends. Only problems with the chips of the **last** user message (failed resolution,
over a cap) are recorded as `SkillInitializationException` on `_InvokedSkillsContext` and shown in the
"Initialization issues" stage, with the full reason; problems with older picks are logged. The model learns about a
failed chip from its fixed error result (concern 4), and about an older pick that is no longer available from the
list itself. **No path fails the request.**

---

## Out of Scope

- **Phase 2: letting the user pick the agent's own skills.** It needs a way for the client to list them. It gets its
  own design. One constraint is already known: Core rejects a `custom_content.skills` entry without a `url` with
  `400`, so a name-only reference can't go in that array.
- **Picking `prompts/` URLs.** Core accepts only `skills/` resources in the field. Declared `prompts/` skills are used
  by the model as today.
- **A per-app switch to disable invocation.** A picked skill never replaces one of the agent's skills, and access is
  capped by the user's own reach. It does put the skill's name and description into the system prompt, the channel
  the app author owns, which pasting text into a message can't. That is limited to one description of at most 1024
  characters per skill, and to `SKILL_INVOCATION_MAX_SKILLS` skills. A `features.skill_invocation` toggle can be added
  if an app author asks for one.
- **Autoloading the user's skills.** Implicit, every-turn skill loading has its own access story (Core resource
  dependencies) and prompt-budget story.
- **Argument templating** (`$ARGUMENTS` in the manifest). The message text is the argument. Templating would
  rewrite skill content per invocation and break the "history is what the model saw" property.
- **Enforcing `allowed-tools`.** Unchanged: still advertised in the XML and never enforced.
- **Lazy resolution of older invocations.** Today every picked skill in the conversation is resolved every turn,
  bounded by the cap. Resolving only on a `read_skill` miss would remove that cost but needs an async path through
  the registry merge.

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
              <skill><name>code-review</name><description>How this team reviews PRs</description></skill>
              <skill><name>user:code-review:3f9a2c</name><description>How I want my code reviewed</description></skill>
            </available_skills> …
user      /code-review the diff in the attachment, focus on auth
assistant tool_calls: read_skill {"skill_name": "user:code-review:3f9a2c"}
tool      Skill `user:code-review:3f9a2c`, selected by the user. Read its files with `read_skill("user:code-review:3f9a2c", <path>)`.
          ---\nname: code-review\n… \n<skill_files>\nreferences/checklist.md\n</skill_files>
```

The user sees the stage "Reading Skill: code-review (user skill)".

### Turn 2

The client resends turn 1, with `custom_content.skills` still on the first user message, then the new user message.
QuickApps restores the turn-1 pair from assistant state, resolves and lists the picked skill again under the same
name so its files stay readable, and injects nothing new unless the new message carries its own chips.

### Limits

| Variable | Default | Purpose |
|---|---|---|
| `SKILL_INVOCATION_MAX_SKILLS` | `10` | Distinct picked skills resolved and listed per request across the conversation, newest first. Each listed skill adds a `<skill>` block to the system prompt on every turn, so this is also a prompt budget. |
| `SKILL_INVOCATION_MAX_PER_MESSAGE` | `5` | Chips honoured on one message; the rest get an error result and are never listed. |
| `DIAL_SKILLS_FILE_MAX_BYTES` | `262144` | Reused unchanged for the injected manifest. |

### Failure modes

| Condition | Result |
|---|---|
| No chips anywhere | Exactly as today, system prompt included; no extra Core calls |
| `ENABLE_PREVIEW_FEATURES=false` | The module is unregistered, so a chip is not resolved, listed or injected, and neither the user nor the model is told. `custom_content.skills` also keeps its place on the messages, so it reaches the orchestrator deployment and Core shares those skills with it. Accepted while the feature is preview-only; registering the scrub in `SkillsModule`, which is never gated, would close both halves |
| Malformed entry, absolute URL, or not a `skills/` resource | Core rejects the request with `400`; QuickApps never sees it |
| Picked skill deleted (user's own, or public) | Error result on the invoking turn; on later turns it isn't listed and its name returns "not found" |
| Picked skill shared with the user, share later revoked | Core rejects the request with `403`, on every later turn of that conversation (Known Gaps) |
| Invalid or over-cap `SKILL.md` | Fixed error result for the model; the reason in "Initialization issues"; not listed |
| Picked skill has the same `name` as an agent skill | Both listed, under `code-review` and `user:code-review:<hash>` (UC-5) |
| Two picked skills share a `name` | Both listed, with different hashes |
| The same skill picked again later | Moves to the end of the user skills in the list; never dropped by the cap on the message that picks it; no new pair is injected, and no "Reading Skill" stage is shown |
| The user edits a picked skill's content mid-conversation | The model keeps the manifest from the turn that first picked it; a later `read_skill` of a bundled file returns the current file |
| The user edits the skill's `name` in `SKILL.md` mid-conversation | The listed name doesn't change: it comes from the URL |
| Identical chips on one message | Counted once: one pair, one entry |
| Picked URL the app also declares | Listed twice: under the agent's name and as a user skill; either name reads the same content |
| Over `SKILL_INVOCATION_MAX_PER_MESSAGE` on one message | The extra chips get an error result and are not listed |
| Over `SKILL_INVOCATION_MAX_SKILLS` in the conversation | The oldest picks are no longer listed; their manifests stay in history; their names return "not found" |
| DIAL Core outage | Every picked skill gets an error result or drops out of the list; the agent's own skills are unaffected; request served |

---

## Known Gaps

### A revoked share breaks the conversation

Core rejects a request with `403` when any `custom_content.skills` URL in it is unreadable by the user, the same
fail-closed rule it applies to attachments. The client resends the whole history every turn, so a skill that was
shared with the user and then unshared makes **every later turn** of that conversation fail, not just the turn that
picked it. The user's own skills and public skills are not affected: the user can always read their own bucket, and
Core doesn't check public skills. A deleted skill of either kind passes Core and becomes an ordinary QuickApps error
result.

QuickApps can't work around this, because the request never reaches it. The fix belongs in Core: skip an unreadable
skill reference instead of failing the request, and let QuickApps report it like any other skill it can't load.
Until then the user's only way out is to start a new conversation.

---

## Alternatives Considered

| Alternative | Why not |
|---|---|
| **A precedence rule between same-named skills** (the user's pick wins the name, or the agent's does) | Whichever skill loses becomes unreachable by name, and the model silently gets a different skill than it may have meant. If the user's pick wins, it can also replace predefined skills, and the mapping flips on its own when a pick is deleted or drops out of the cap. |
| **Add `<id>` and `<source>` to every skill, with an ambiguity error for shared names** | Solves collisions, but changes the skills contract and the system prompt of every app, and needs a new lookup order in `SkillsRegistry`. A derived name gives the same guarantee with no contract change. |
| **The URL as the listed name** | The simplest unique name, but it puts the user's bucket id in front of the model and in the stage title. |
| **`<name>` from the skill's `SKILL.md`** | Readable, but the listed name would change when the user edits the manifest mid-conversation, and a chip that fails to resolve has no manifest name at all. The URL's last segment gives one stable name per pick. |
| **`user:<name>` without a hash** | Two picked skills with the same name (the user's and an organisation's) can't both be listed, and the name would switch skills when one of them is picked, deleted or dropped. |
| **`user:<name>-<n>` numbered by pick order** | The numbering shifts when an older pick drops out of the cap, and a name then points to a different skill. |
| **Address picked skills by URL but keep them out of `<available_skills>`** | Keeps the system prompt stable, but the model can't see that a second `code-review` exists, and a bare-name call silently goes to the agent's. |
| **Parse `/name` from the text** | A name carries no access, so a personal skill still couldn't be read, and it is ambiguous among the user's same-named skills. |
| **Match a leading `/name` against the agent's own skills** | Considered for phase 1 and dropped. Without a palette the user can't discover the names, and it would be a second invocation path that phase 2 replaces anyway. Asking in words covers the need until then. |
| **Only list the picked skill, without injecting it** | Not deterministic (goal 1): the model decides whether to read it. |
| **Request-level `custom_fields.skills.invoked`** | An invocation belongs to a turn. A request-level field only describes the latest turn and is gone from history once the next message is sent, so Core can't re-share the skill and its files become unreadable. |
| **Send the skill as a `custom_content.attachments` entry** | Works with no Core change, since Core already shares any attachment URL. But when the user switches models mid-conversation, every other deployment would see a `skills/` URL as a file attachment. QuickApps would also have to filter it out of its own attachment pipeline. |
| **Inline the manifest into the user message every turn** | Re-fetches and re-inlines every historical invocation on every turn. If the skill is edited, earlier turns silently change, which makes history differ from what the model actually saw. The synthetic pair freezes the manifest as it was when invoked. |

---

## Migration

### Breaking changes

None.

### Non-breaking changes

- Requests without `custom_content.skills` behave exactly as today, system prompt included: no new Core calls, no new
  messages, no change to `<available_skills>`.
- The package is gated by `@preview_module`, matching `DialSkillsModule`, whose `DialSkillResolver` it reuses.

## Summary of Changes

### `quickapp/skill_invocation/` (new)

- `_skill_reference.py` — `SkillReference(url)`; parses `custom_content.model_extra["skills"]` from user messages and
  canonicalises the URL.
- `_invoked_skills_context.py` — `_InvokedSkillsContext(SkillsProvider)`, `order = 30`, `display_name = "user skills"`.
  Lists trimmed copies of the resolved skills under `user:<name>:<hash>` (name and a capped description only, content
  with the one-line header), by position; holds a failure reason per URL and the exceptions for the last user
  message's chips.
- `_skill_invocation_initializer.py` — `_SkillInvocationInitializer(CompletionInitializer)`: collect newest first,
  per-message dedup and cap, canonicalise, keep the latest occurrence, validate, conversation cap, delegate to
  `DialSkillResolver`.
- `_skill_invocation_injector.py` — `_SkillInvocationInjector(MessagesTransformer)`: synthetic `read_skill` pairs for
  the distinct chips of the last user message, a fixed error result for failed ones, and `custom_content.skills`
  scrubbing.
- `_settings.py` — `SkillInvocationSettings` (`SKILL_INVOCATION_MAX_SKILLS`, `SKILL_INVOCATION_MAX_PER_MESSAGE`).
- `skill_invocation_module.py` — `@preview_module`; multiproviders for `CompletionInitializer`, `SkillsProvider`,
  `MessagesTransformer`, `InitializationException`. Registered in `app_factory.py` after `DialSkillsModule`.

### `quickapp/skills/`

- `_user_skill_names.py` — `make_user_skill_name(url)`, `parse_user_skill_name(listed)`.
- `_skill_reader_stage_wrapper.py` — the stage title for a user skill shows its short name, marked "(user skill)".
- `__init__.py` — export `SKILL_READER_TOOL_NAME` and the two helpers.

### `quickapp/dial_skills/`

- `_dial_skill_resolver.py` — `resolve(..., unique_names: bool = True)`. The invoked-skills initializer passes
  `False`; the existing caller is unchanged.

### `quickapp/common/`

- `_di_types.py` — `REQUEST_MESSAGES`.
- `synthetic_injection/synthetic_tool_call_injector.py` — `build_synthetic_pair` and `make_synthetic_call_id` as
  public module-level helpers; the class keeps using them.

### `quickapp/core/application/`

- `_request_context.py`, `_request_context_setup.py`, `app_module.py` — store the raw request messages in
  `setup_context` and provide them as `REQUEST_MESSAGES`.

### Outside this repo

- `ai-dial-core` — done in #1956 for chat completions. Follow-up request: skip an unreadable skill reference instead
  of rejecting the request (Known Gaps).
- `ai-dial-chat` — `skills?: SkillRefDto[]` on `MessageCustomContentDto` (`forbidNonWhitelisted` rejects it today),
  the `/` palette of the user's own skills, and the skill chip. `content` is sent as typed, `/name` token included.
- `aidial-sdk` (optional) — a typed `CustomContent.skills`.
- `docs/skills.md` — document invocation, the wire field, the `user:<name>:<hash>` listing, and the limits once
  implemented.
