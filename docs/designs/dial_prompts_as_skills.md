# Design: DIAL Prompts as Skills

- **Status:** Implemented
- **Approved:** 2026-04-23
- **Dependencies:**
  - [Agent Skills and File Transfer](skills_and_file_transfer.md) (implemented)

## Problem Statement

Today, the only way to provide agent skills is through predefined content layers — static `SKILL.md` files bundled
at build time or mounted via `PREDEFINED_EXTRA_PATHS`. Users cannot configure their own skills for a QuickApp.

DIAL already has a prompts API (`/v1/prompts/`) that allows users to create, store, and manage text content in their
personal storage. A DIAL prompt whose content follows the
[Agent Skills specification](https://agentskills.io/specification) (valid YAML frontmatter with `name` and
`description`) is semantically a skill. Exposing these prompts as skills gives users a self-service path to extend
agent behavior without operator involvement or redeployment.

## Design Goals

- **New `skills` config field** in the application schema that accepts an array of skill source descriptors,
  analogous to `contexts` and `tool_sets`.
- **DIAL prompt skill source** (`type: "dial-prompt"`) that fetches a prompt from DIAL Core at request time and validates
  its content as a conformant skill (per the Agent Skills spec).
- **Unified skill experience**: DIAL prompt skills appear in the same `<available_skills>` XML block and are
  readable via the same `read_skill` tool as predefined skills.
- **Graceful degradation**: Invalid or inaccessible DIAL prompts are skipped with a warning — they never prevent
  the request from being served.
- **Unified initialization reporting**: All initialization issues — tool-init failures and skill-loading
  failures — share a common `InitializationException` hierarchy, flow through a single
  `list[InitializationException]` multiprovider, and surface in one stage with per-feature sections
  via the generalized `_InitializationErrorHandler`.

---

## Use Cases

### UC-1: User adds a custom skill from a DIAL prompt

**Trigger:** A user creates a prompt in DIAL Chat (or via API) with valid Agent Skills frontmatter, then
references it in a QuickApp config.

**Behavior:** At request time, the backend fetches the prompt from DIAL Core, validates the frontmatter, and
registers it alongside predefined skills. The agent sees the skill's metadata in its system prompt and can call
`read_skill` to retrieve the full content.

**Outcome:** The agent follows the instructions from the user-provided skill, just as it would for a built-in
skill.

### UC-2: User references a DIAL prompt without valid skill header

**Trigger:** The config references a DIAL prompt whose content does not contain valid YAML frontmatter (missing
`name` or `description`, or no frontmatter at all).

**Behavior:** The backend fetches the prompt, attempts to parse the frontmatter, and finds it invalid. The skill
is skipped and the user sees a *Skill loading* section inside the single *Initialization issues* stage,
explaining the issue (e.g., "Missing required fields (name/description) in prompts/\<bucket\>/my-prompt").

**Outcome:** The request proceeds normally. Other skills (predefined and valid DIAL prompt skills) remain
available. The agent does not see the invalid skill.

### UC-3: DIAL prompt is inaccessible

**Trigger:** The config references a DIAL prompt that does not exist, or the user lacks permission to access it.

**Behavior:** The DIAL Core API returns 404 or 403. The skill is skipped and the user sees a *Skill
loading* section inside the single *Initialization issues* stage explaining the fetch failure.

**Outcome:** Same as UC-2 — graceful degradation. The request is served with remaining skills.

---

## Proposed Design

### 1. Application config — `skills` field

**Owner:** `config/` package.

**What:** A new optional field `skills` on `ApplicationConfig` — an array of skill source descriptors using a
discriminated union, following the established pattern of `contexts` and `tool_sets`.

```yaml
# Application config example
orchestrator: ...
contexts: [...]
tool_sets: [...]
skills:                           # NEW
  - type: "dial-prompt"
    url: "prompts/<bucket>/<folder>/<prompt-name>"
```

**Config model:** A new `config/skill.py` defines `DialPromptSkillConfig` (with `type: Literal["dial-prompt"]`
and a `DialResourceConfigField`-annotated `url`) and a `SkillConfig` discriminated union keyed on `type`.

The `type` discriminator is `"dial-prompt"` rather than `"dial"` to reserve `"dial"` / `"dial-skill"` for
future first-class DIAL skill entities without a rename.

`SkillConfig` is kept as an `Annotated[…, Field(discriminator="type")]` union even though it has only one
variant today — so the JSON schema's `oneOf` shape is ready for the second variant and callers know `type`
is the discriminator key.

**`url` field annotation — `DialResourceConfigField`:** The `url` field is annotated with the existing
`DialResourceConfigField` (emits `dial:resource: true` in the JSON schema). This is the same annotation used by
`DialMCPToolSet.dial_id` and `DialDeploymentSimpleTool.deployment_id`. DIAL Core recognizes `dial:resource`
fields and performs auto-sharing for the referenced resources at deployment time — the resource type (prompt) is
inferred from the URL prefix (`prompts/...`). No new metaschema extension is needed.

**URL format:** the `url` must be a relative path with the `prompts/` resource prefix (e.g.
`prompts/<bucket>/folder/my-skill`), following the same convention as `FileContextConfig.url`. Absolute URLs
are rejected by the client's `safe_parse_storage_resource()`.

**Change to `ApplicationConfig`:** add an optional `skills: list[SkillConfig] | None` field gated by
`PreviewField(default=None)` — same pattern as `Features.timestamp`. With `ENABLE_PREVIEW_FEATURES=false`
the field is stripped from the published JSON schema by `_strip_preview_fields`
(`src/quickapp/common/base_config.py`) and any user-supplied value is nullified by `_gate_preview_fields`.

**Semantics:**
- `None` (default) or empty list: no user-configured skills. Predefined skills remain available.
- Each entry describes a source from which to fetch skill content at request time.
- The discriminated union starts with a single variant (`DialPromptSkillConfig`) but is designed for extensibility
  (e.g. a future `"custom"` variant with inline content, `"dial"` / `"dial-skill"` for native DIAL skill
  entities once available, or a `"predefined"` variant to selectively enable built-in skills).

**Schema impact:** `make dump_app_schema` regenerates the JSON schema to include the new `skills` field. The
editor (frontend) will need to support the new field to provide a UI for configuring skills.

### 2. Skill resolution — `DialPromptSkillResolver`

**Owner:** `dial_prompt_skills/` package (new).

The DIAL prompt skill integration is a separate module from the core `skills/` package. `skills/` owns the
framework (what a skill is, how it's surfaced to the agent). `dial_prompt_skills/` owns a specific skill
**source** (where to fetch skills from). This separation keeps `skills/` source-agnostic and mirrors how
tool types each have their own package (`rest_api_tooling/`, `mcp_tooling/`, `dial_deployment_tooling/`) while
the common tool framework lives in `common/`.

**What:** A component that resolves `DialPromptSkillConfig` entries into validated `SkillMetadata`
objects with their full content. Bound at `request_scope` in `DialPromptSkillsModule` and injected with
the request-scoped `AsyncDial` client directly (no intermediate service needed — prompt fetching is a
simple GET with no caching or size-limit logic).

**Semantics:**

```
ApplicationConfig.skills
  └──> DialPromptSkillResolver.resolve(skill_configs)
         ├── For each DialPromptSkillConfig:
         │     ├── Fetch prompt via AsyncDial.prompts.get(url)
         │     ├── Extract prompt.content
         │     ├── Parse YAML frontmatter (reuse parse_frontmatter from skills/)
         │     ├── Validate per Agent Skills spec
         │     └── Return (SkillMetadata, full_content) or skip with SkillInitializationException
         └── Return list of resolved skills
```

**Content guard:** Before parsing, the resolver checks `prompt.content`. If `content` is `None`, empty, or
whitespace-only (matching the current `not prompt.content.strip()` check), the skill is recorded as a
`SkillInitializationException` (e.g., "DIAL prompt at \<url\> has no content"). This handles prompts that
exist but have no body — `parse_frontmatter` expects a non-trivial `str`, so a `None`/empty body would
otherwise raise or produce an unhelpful "no frontmatter" error.

**Validation rules** (same as predefined skills, enforced by `parse_frontmatter`):
- Must have YAML frontmatter delimited by `---`
- `name`: required, max 64 chars, lowercase alphanumeric + hyphens, no consecutive hyphens
- `description`: required, max 1024 chars
- Other fields (`license`, `compatibility`, `metadata`, `allowed-tools`): optional, validated per spec

**Key design choice — frontmatter parsing is reused, not duplicated.** The static method
`AgentSkillsProvider._parse_frontmatter()` already implements full Agent Skills spec validation. The resolver
calls it directly rather than reimplementing validation. To enable this,
`_parse_frontmatter` is promoted from a private static method on `AgentSkillsProvider` to a standalone module-level
function in `skills/` (e.g. `skills/_frontmatter.py`), importable by both the provider and the resolver.

**Deduplication:** Before fetching, the resolver deduplicates by URL — if the same prompt URL appears multiple
times in the `skills` array, it is fetched once. After fetching, if two different DIAL prompts resolve to the
same skill `name`, the first one (by config order) wins and the duplicate is recorded as a
`SkillInitializationException`.

**URL normalization is not performed.** Deduplication uses the raw `cfg.url` string. Two entries spelled
differently (trailing slash, URL-encoded vs. decoded, mixed case in a bucket name) are treated as distinct
and fetched twice. If both resolve to the same skill `name`, the second one produces a duplicate-name
`SkillInitializationException`. This is acceptable for a preview feature; canonicalizing via
`DialStorageResourceMixin.get_api_path` before dedup can be added later if spelling variants become a real
problem in practice.

**Structured issue reporting.** The resolver does **not** log issues or render UI stages itself. Instead,
it returns failed entries alongside resolved skills so the caller — the initializer (see §4) — can route them
to the request-scoped skills context for later rendering. Per-URL failures are modeled as
`SkillInitializationException` instances (defined alongside `ToolInitializationException` in
`common/exceptions/`; see §4.0). The resolver's signature:

```python
async def resolve(
    self,
    skill_configs: list[DialPromptSkillConfig],
) -> DialPromptSkillResolverOutput:
```

`DialPromptSkillResolverOutput` is a frozen Pydantic model with two fields, `resolved:
list[ResolvedDialPromptSkill]` and `exceptions: list[SkillInitializationException]`. A named output model is
used rather than a bare tuple so callers read the fields by name (CODESTYLE §8 — "Pydantic models for
complex structures"). `ResolvedDialPromptSkill` (also a frozen Pydantic model) carries the source `url`, the
parsed `SkillMetadata`, and the full `content` — the initializer needs the URL for collision messages and for
future cross-request debugging.

All per-URL failure modes — fetch exceptions, empty content, invalid frontmatter (via `SkillValidationError`),
and duplicate names — produce a `SkillInitializationException(url=..., reason=...)`. Each such instance is
"soft" (`is_hard = False`), meaning the request proceeds with whatever skills did resolve. Whole-subsystem
failures (resolver raises before any per-URL task runs) are represented by the subclass
`SkillCatastrophicInitializationException` with `is_hard = True`; that flip is what lets the handler (§4.4)
decide the stage's close status without inspecting a separate field.

**Error handling:** Each skill config is resolved independently. A failure in one does not affect others.
Parallel fetches use `asyncio.gather(..., return_exceptions=True)` — the resolver collects exceptions from the
result list, converting each into a `SkillInitializationException` with enough context to diagnose (prompt
URL, error type). Without `return_exceptions=True`, the first exception would cancel all remaining tasks.

**DI module — `DialPromptSkillsModule`:** Decorated with `@preview_module` and registered in `AppFactory`
alongside the other feature modules. When `ENABLE_PREVIEW_FEATURES=false`, `AppFactory` filters out the module
entirely — no resolver is bound, and no DIAL prompt fetching occurs. Binds `DialPromptSkillResolver`,
`_DialPromptSkillInitializer`, and `_DialPromptSkillsContext` at `request_scope` (see §4), exposes the
initializer as a `CompletionInitializer`, and exposes the context's `_exceptions` list via
`@multiprovider → list[InitializationException]` — same pattern as `MCPToolingModule`, but widened to the
shared base type (§4.0) so both modules' contributions concatenate into one injected list at the handler.

### 3. Skills registry — request-scoped skill merging

**Owner:** `skills/` package.

**What:** A request-scoped `SkillsRegistry` that merges predefined skills (from the singleton
`AgentSkillsProvider`) with external skills that were already resolved during the initialization phase (see
§4) into a unified skill set for the current request. Implements `PromptPartProvider`.

**Why a new component?** `AgentSkillsProvider` is a singleton that loads skills eagerly at startup. External
skills (e.g. from DIAL prompts) are per-request (they depend on user credentials and may change between
requests). Merging these two sources requires a request-scoped component.

**Resolution timing — eager, not lazy.** External skills are fetched during the initialization phase by
`_DialPromptSkillInitializer` (see §4), which populates `_DialPromptSkillsContext` before the agent invoker
runs. By the time any `PromptPartProvider` is consulted, every DIAL prompt skill has already been fetched
(or failed), and every `SkillInitializationException` has already been collected. The registry therefore
does **no I/O** and **does not mutate** either `AgentSkillsProvider`'s cached list or the context's
`_resolved_skills` list — it builds its own local merged list from copies and returns the XML/metadata from
that. The sources remain independently inspectable for tests and future callers.

The registry itself performs no I/O. I/O orchestration lives in the initializer (§4) and UI presentation
lives in the unified `_InitializationErrorHandler` (§4.4), reusing the same pattern that already covers
MCP tool initialization (`_MCPToolInitializer`, `_MCPToolingContext`, `_InitializationErrorHandler`).

**Semantics:**

- Constructed per-request with injected `AgentSkillsProvider` (singleton), and `_DialPromptSkillsContext`
  (request-scoped, optional — see §4). The registry no longer depends on `DialPromptSkillResolver`,
  `ProviderOf[ApplicationConfig]`, or `ProviderOf[Stage]`.
- `async get_prompt_part() -> str` — builds the merged metadata list (predefined + context-resolved DIAL
  prompt skills, with collisions dropped) and returns the combined XML. Cached in-memory after the first
  call for the rest of the request. No fetching, no error handling here — by contract, the context is
  populated (or empty) by the time this method runs. Stays `async` to match the `PromptPartProvider` ABC.
- `get_skill_content(name: str) -> str` — **synchronous**. Returns full content for a skill by name. If
  the skill is predefined, looks up in `AgentSkillsProvider.get_all_skill_contents()`. If the skill is a
  DIAL prompt skill, looks up in the context's merged content map. Raises `FileNotFoundError` when the
  name is not in the merged set — preserving the existing error contract used by
  `_SkillReaderTool._run_in_stage_async()`. Not part of `PromptPartProvider` or any other abstract base;
  under the eager model it is a pure dict lookup. Making it sync avoids a misleading `await` at the one
  caller (`_SkillReaderTool`) and signals clearly that all resolution has already happened.

**DI wiring when preview is disabled:** When `DialPromptSkillsModule` is filtered out (preview off),
`_DialPromptSkillsContext` is not bound. `SkillsRegistry` handles this via optional injection
(`_DialPromptSkillsContext | None = None`). When `None`, the registry sees only predefined skills — no DIAL
prompt skills ever appear.

**Merge semantics:**
1. Start with all predefined skills (from `AgentSkillsProvider`). These are admin-configured and always take
   precedence.
2. Add DIAL prompt skills from the context. If a DIAL prompt skill has the same `name` as a predefined
   skill, the DIAL prompt skill is **skipped** — predefined wins. The collision produces a
   `SkillInitializationException(url=..., reason="predefined skill with same name takes precedence; skipped")`
   that is appended to the context's `_exceptions` list (so the unified handler in §4.4 picks it up via the
   shared multiprovider). Collision detection happens in the registry, not the initializer, because only the
   registry can compare against predefined names.
3. The registry generates combined XML from the merged metadata list. XML generation is owned exclusively
   by `SkillsRegistry` — no other component produces XML.

**Skill precedence summary.** Combining §2's resolver-level dedup with the registry's predefined-wins rule
gives a single three-level precedence:

| Priority | Source | Behavior on conflict |
|---|---|---|
| 1 (highest) | Predefined skill (`AgentSkillsProvider`) | Always wins |
| 2 | First DIAL prompt skill by config order with a given `name` | Beats subsequent DIAL prompt entries with the same name |
| 3 (lowest) | Subsequent DIAL prompt skills with an already-seen name | Dropped; duplicate-name `SkillInitializationException` emitted |

A DIAL prompt skill demoted by rule 1 produces a "predefined takes precedence" `SkillInitializationException`;
one demoted by rule 3 produces a "duplicate skill name" one. Both flow to the same stage via the context →
multiprovider → handler path.

**`SkillMetadata.metadata` typing.** The refactor also tightens the `metadata` field annotation on
`SkillMetadata` (at `src/quickapp/skills/_skill_metadata.py:11`) from the current bare `dict` to
`dict[str, Any] | None`. This adds shape (a mapping keyed by strings, explicitly nullable) without
constraining values, which the Agent Skills spec allows to be arbitrary YAML (ints, lists, nested mappings
— the existing XML generator in `_xml.py` already coerces every value via `str(raw_value)`, confirming the
model intentionally tolerates non-string values). Narrower typing like `dict[str, str]` would cause
Pydantic to reject previously-accepted frontmatter at load time and silently skip those skills via the
`except SkillValidationError` / `except Exception` branches in `AgentSkillsProvider._load_skills`. The
schema emitted by `make dump_app_schema` will show `metadata` as `{string: any}` rather than untyped
object — still a precision win without a compatibility break. This field appears in every response of
`/v1/configuration-support/skills`.

**Collision exceptions are detected at merge, reported via the context.** The initializer cannot detect
predefined-vs-DIAL-prompt name collisions (it has no reference to the predefined set). The registry
detects them during its merge and appends them to the same `_DialPromptSkillsContext._exceptions`.
`DialPromptSkillsModule` exposes that list via a `@multiprovider → list[InitializationException]`, which the
unified `_InitializationErrorHandler` (§4.4) injects alongside the analogous contribution from
`MCPToolingModule` — collision entries reach the user in the same `Skill loading` section as
fetch/validation entries and alongside any tool-initialization entries, one consolidated UI surface. The
pipeline reshuffle in §4.1 is what makes this safe: the registry's merge runs during message finalization,
and the handler runs *after* finalization.

**`AgentSkillsProvider` becomes a pure data store.** The singleton drops its `PromptPartProvider`
implementation entirely — no more `get_prompt_part()`, `get_skills_xml()`, `_generate_xml()`, or
`_escape_xml()`. It retains only:
- `get_all_skills() -> list[SkillMetadata]` — returns the cached list of predefined skill metadata.
- `get_all_skill_contents() -> dict[str, str]` — returns `{name: full_content}` for all predefined skills.
- `get_skill_content(name: str) -> str` — still needed by `_InjectFileTransferInstructionTransformer`.

Each skill source (`AgentSkillsProvider`, `_DialPromptSkillsContext`) produces `list[SkillMetadata]` +
content. The registry is the single point that merges metadata, converts to XML, and exposes the result via
`PromptPartProvider`.

**`_InjectFileTransferInstructionTransformer` stays on `AgentSkillsProvider`.** This transformer lives in
`src/quickapp/skills/_inject_file_transfer_instruction_transformer.py` and is wired by `SkillsModule` — the
`skills_and_file_transfer.md` "Summary of Changes" mistakenly attributes it to `file_transfer/`, but the
codebase is authoritative. It only reads the predefined `tool-call-file-parameter-formatting` skill — a
built-in skill that is always available regardless of user config. It does not need the registry and should
not depend on it. No file moves; only the data-source call (`AgentSkillsProvider.get_skill_content`) is
preserved as `AgentSkillsProvider` narrows to a pure data store.

**Impact on `_SkillReaderTool`:** The tool's dependency changes from `AgentSkillsProvider` to `SkillsRegistry`.
When the agent calls `read_skill`, the registry looks up the skill by name in the merged (deduplicated) set.

### 4. Initialization-time resolution and unified error reporting

**Owner:** `common/exceptions/` for the shared exception hierarchy; `dial_prompt_skills/` package for the
new request-scoped components; `application/` package for the pipeline reshuffle and the generalized
`_InitializationErrorHandler`. The wiring mirrors MCP tooling.

**Why eager.** The previous revision of this design resolved DIAL prompt skills lazily inside
`SkillsRegistry.get_prompt_part()` and rendered failures through a stage that `SkillsRegistry` opened
directly. That shape has two problems:

1. **Responsibility smear.** The registry owned I/O, data merging, and UI presentation in one class. Each
   of those concerns evolves for different reasons.
2. **Inconsistency with tool initialization.** Tool failures flow through
   `_MCPToolingContext.append_exception` → `list[ToolInitializationException]` multiprovider →
   `_InitializationErrorHandler`. Skills invented a parallel, incompatible presentation mechanism — a
   second handler and a second stage for what is conceptually the same class of problem ("something went
   wrong while setting up this request").

Moving skill resolution to the initializer phase requires a pipeline reshuffle (§4.1) because message
transformation currently runs *before* initializers. The same reshuffle also lets a **single** post-
finalization handler cover both tool-init and skill-loading issues (§4.4). Everything else in this section
depends on the reshuffle being in place and on the unified exception hierarchy introduced in §4.0.

#### 4.0 Unified exception hierarchy — `InitializationException`

**Owner:** `common/exceptions/`.

Tool-init and skill-loading issues share one shape: a typed, structured record of "something went wrong
during request setup" that the same handler renders in one consolidated stage. Modeling them as siblings
under a common base class turns that shared shape into a type the DI graph can express directly — every
feature module binds `@multiprovider → list[InitializationException]` and the handler injects one merged
list.

```
InitializationException                                (Exception; is_hard: ClassVar[bool] = True)
├── ToolInitializationException                         (unchanged fields: tool_name, toolset_name, details)
└── SkillInitializationException                        (fields: url, reason; is_hard = False)
    └── SkillCatastrophicInitializationException        (no url; is_hard = True — flips stage to FAILED)
```

**Base class docstring contract.** `InitializationException` carries a one-line docstring stating its
purpose: *"Base class for any failure that should flow through the merged
`list[InitializationException]` multiprovider to `_InitializationErrorHandler` for unified rendering."*
This gives a future maintainer introducing a third subclass (e.g. for a new `"custom"` skill source or a
REST-API tool context) an unambiguous criterion: if the entry needs to appear in the unified
`Initialization issues` stage, subclass `InitializationException`; otherwise it is a different concern.

**What `is_hard` does.** `is_hard` is a `ClassVar[bool]` the handler consults to decide the close status
of the single `Initialization issues` stage. If *any* exception in the merged list has `is_hard = True`, the
stage closes `FAILED`; otherwise `COMPLETED`. The request proceeds either way — the status is a UI cue.

**Behavior preservation for tool-only runs.** Because `ToolInitializationException.is_hard = True` is a
classvar true for every instance, any non-empty contribution from `MCPToolingModule` flips the stage to
`FAILED` — identical to today's unconditional `Status.FAILED` at `_initialization_error_handler.py:36`.
The generalization strictly weakens FAILED only for *skill-only* runs with no catastrophics, which is a
new surface; tool behavior is unchanged.

- `ToolInitializationException.is_hard = True` — any tool-init failure is treated as hard, matching
  existing behavior.
- `SkillInitializationException.is_hard = False` — per-URL skill failures are soft; the agent still runs
  with whatever skills resolved.
- `SkillCatastrophicInitializationException.is_hard = True` — whole-subsystem failure (DIAL prompts as a
  whole could not be loaded) is hard.

**Why a subclass rather than a field for catastrophic.** A `SkillCatastrophicInitializationException` needs
(a) different rendering (distinct sub-header, no per-URL bullet shape) and (b) a different `is_hard` value.
Encoding both via subclass keeps the handler's logic a pure `isinstance` dispatch and avoids magic field
values (empty-string `url`, nullable fields). If a future skill source needs another "hard, subsystem-wide"
failure it simply subclasses `SkillInitializationException` the same way.

**Rejected alternative: polymorphic `render()` on the exception classes.** Pushing markdown generation onto
each exception subclass would couple domain types to presentation (Stage, markdown syntax) and complicate
testing. The handler is where presentation belongs; each new exception class only adds an `isinstance`
branch there.

**Rejected alternative: single merged bag without a shared base.** The merged-multiprovider approach only
works when the binding key (`list[InitializationException]`) is expressible. Without the shared base, each
module would need its own typed binding and the handler would inject multiple lists — regressing to the
per-feature-dependency shape and losing `isinstance`/catch semantics everywhere else in the codebase.

**Migration note.** `ToolInitializationException` gains `InitializationException` as its parent in place of
the previous direct `Exception` parent. No existing `except ToolInitializationException` site changes. The
`MCPToolingModule.__provide_initialization_exceptions` return annotation widens from
`list[ToolInitializationException]` to `list[InitializationException]`; concrete instances are still
`ToolInitializationException` so no caller behavior changes.

#### 4.1 Pipeline reshuffle — message transformation moves post-initializer

Today, `_QuickAppCompletion.chat_completion()` runs:

```
_RequestContextSetup.setup(request, choice)   # includes _MessagesSetup.setup() inline
invoke_initializers(InitializerType.completion)
_InitializationErrorHandler.handle_initialization_errors()
Orchestrator.invoke()
```

`_RequestContextSetup.setup()` awaits `_MessagesSetup.setup()` (see `_request_context_setup.py:59`), which
runs every `MessagesTransformer` — including `_AddSystemPromptTransformer`, which calls every
`PromptPartProvider.get_prompt_part()`, including `SkillsRegistry.get_prompt_part()`. So by the time
initializers run, the system-prompt XML has already been built. An eager
`_DialPromptSkillInitializer` that populates state after that point would be wasted: the XML would never see
the DIAL prompt skills.

This revision splits `_RequestContextSetup` into two phases. **Only the transformer chain** moves
post-initializer; `extract_tool_calls` (multi-turn tool-history unpacking — currently the first step of
`_MessagesSetup.setup()`) stays pre-init because it is a structural normalization of the incoming message
list that no initializer depends on and that every consumer expects to have already happened.

| Step | Responsibility | Runs |
|---|---|---|
| `_RequestContextSetup.setup_pre_init(request, choice)` | populate `api_key`, `bearer`, `application_config`, `forwarded_headers`, `client_channel_id`, `response_format`, and `messages`. **`messages` shape:** post-`extract_tool_calls`, pre-transformer. | before `invoke_initializers` |
| `invoke_initializers(InitializerType.completion)` | run initializers — including `_DialPromptSkillInitializer` and existing tool initializers; each populates its own feature context. **Initializers may read `context.messages`** in the shape set by `setup_pre_init`. | — |
| `_RequestContextSetup.finalize_messages()` | calls `_MessagesSetup.run_transformers(context.messages)` and overwrites `context.messages` with the transformed list; the chain includes `_AddSystemPromptTransformer`, which produces the system prompt and may push predefined-vs-external collision `SkillInitializationException` entries into `_DialPromptSkillsContext`. **`messages` shape after:** post-transformer (final). | after initializers |
| `_InitializationErrorHandler.handle_initialization_issues()` | render one "Initialization issues" stage with per-feature sections (see §4.4) | after messages finalize |
| `Orchestrator.invoke()` | run the agent | — |

**Contract for `context.messages` across the split.** After `setup_pre_init`, `context.messages` is always
defined and always in its post-`extract_tool_calls` shape; it is never raw. After `finalize_messages`, the
same field is overwritten with the transformer output. There is no intermediate state where `context.messages`
is missing or partially processed — initializers see one consistent shape; post-init code sees another.

**`_MessagesSetup` split.** The existing `setup(messages)` method is decomposed into two public entry
points with the same combined effect:
- `_MessagesSetup.extract_tool_calls(messages) -> list[Message]` (remains an instance method — unchanged
  body; promoted from an implementation detail of `setup()` to a named entry point of the public API).
- `_MessagesSetup.run_transformers(messages) -> list[Message]` (new; instance method; runs only the
  transformer chain).

`setup()` is removed — every call site moves to one of the two new methods. `setup_pre_init` calls
`extract_tool_calls`; `finalize_messages` calls `run_transformers`. External API is strictly additive at
the `_MessagesSetup` boundary (two methods instead of one), and the caller set is small (currently only
`_RequestContextSetup`).

`finalize_messages()` is a method on `_RequestContextSetup`, not a direct call to `_MessagesSetup` from
`_QuickAppCompletion`. Keeping the split inside one class means `_QuickAppCompletion` only knows two
context-setup entry points (pre-init, finalize), and `_RequestContextSetup` stays the single authority over
what lives on `_RequestContext`.

All existing `MessagesTransformer` implementations continue to work unchanged — they just run later. The
split only affects the order of the two halves of context setup. No transformer today depends on initializer
output *except* `_AddSystemPromptTransformer` via the new `SkillsRegistry` contract in §3; the reshuffle is
what unlocks that dependency.

**Interaction with `_InjectFileTransferInstructionTransformer`.** This transformer reads the predefined
`tool-call-file-parameter-formatting` skill from `AgentSkillsProvider` (a singleton populated at startup). It
does not depend on any request-scoped initializer. It runs in the post-init phase like every other
`MessagesTransformer` — nothing changes from its perspective.

**Backward compatibility.** `_MessagesSetup.setup()` is replaced by two method entry points
(`extract_tool_calls` and `run_transformers`) with the same combined behavior. The only caller today is
`_RequestContextSetup`; its two new phases call one method each. `_QuickAppCompletion`'s public
`chat_completion` signature is unchanged.

#### 4.2 `_DialPromptSkillInitializer` (`CompletionInitializer`)

**Owner:** `dial_prompt_skills/`.

Implements `CompletionInitializer.initialize()`. Reads `ApplicationConfig.skills` via `ProviderOf`, delegates
to `DialPromptSkillResolver.resolve(skill_configs)`, and pushes both halves of `DialPromptSkillResolverOutput`
into `_DialPromptSkillsContext` — `resolved` into `_resolved_skills`, `exceptions` into `_exceptions`. If
`skills` is `None`/empty, the initializer is a no-op. If the resolver raises, the initializer catches the
exception and appends a `SkillCatastrophicInitializationException(reason=...)` to the same `_exceptions`
list, then returns. The request proceeds with predefined skills only. This matches the graceful-degradation
semantics in §2.

**Reachability of the catastrophic branch.** The resolver's per-URL paths already go through
`asyncio.gather(return_exceptions=True)`, so individual fetch failures become per-URL
`SkillInitializationException`s, not raised exceptions. And because `AsyncDial` is injected into the
resolver's constructor, any client-construction failure would surface during `invoke_initializers`'s
injector lookup, not inside `initialize()`. The catastrophic branch therefore only covers a narrow class of
synchronous bugs — e.g. `asyncio.gather` raising before it can schedule (unlikely), or a
`TypeError`/`AttributeError` from a coding mistake in the resolver. We still keep the distinct
`SkillCatastrophicInitializationException` subclass (rather than folding into `SkillInitializationException`
with an empty `url`) because when it fires the UI header should say "DIAL prompts as a whole could not be
loaded" rather than presenting a lone stray entry that is indistinguishable from a per-URL issue, and the
close-stage status needs to flip to `FAILED` (hard).

**Deletion criterion.** If logs across three consecutive releases show zero `SkillCatastrophicInitializationException`
instances, delete the subclass and fold the resolver-level `except Exception` catch back into
`SkillInitializationException` with a fixed `url = "<dial-prompts-subsystem>"` sentinel. Keeping the subclass
indefinitely with no evidence of use is how dead branches stay unexercised forever; the criterion gives
future maintainers a concrete signal to act on.

Registered as one of `list[CompletionInitializer]` via `DialPromptSkillsModule`'s `@multiprovider`, same way
`_MCPToolInitializer` is registered by `MCPToolingModule`.

**Initializer concurrency and ordering.** `invoke_initializers` iterates and awaits each initializer
sequentially (see `src/quickapp/common/base_initializer.py:30-34`). DIAL prompt fetches do **not** overlap
MCP tool initialization: the DIAL prompt initializer runs before or after the MCP one depending on the
injector's binding traversal order — which is predictable today but is an internal detail of `injector`,
not a stable public contract. **Contract: order among initializers is unspecified, and no initializer may
depend on another's state.** Every initializer writes to its own feature-specific context and reads only
from `ApplicationConfig` and other startup-scoped data; the registry's merge in §3 is what consolidates
both contexts, and it runs *after* all initializers have completed. Future features that need
cross-initializer data must surface a dedicated shared stage (e.g. a post-initializer hook) rather than
rely on ordering. Parallelism within `_DialPromptSkillInitializer` comes from `asyncio.gather` *inside* its
`resolve()` delegate (§2), which fans out per-URL fetches. Inter-initializer concurrency would require
changing `invoke_initializers` to `asyncio.gather` across all initializers — a separate concern with its
own trade-offs (ordering assumptions, error-propagation semantics) and is out of scope for this design.

**Request-scoped `AsyncDial`.** `DialPromptSkillResolver.__init__` takes `AsyncDial` as a constructor
dependency. `AppModule` already provides a request-scoped `AsyncDial` bound with the current request's
`api-key` — the same instance used by `DialFileService` and `ToolConfigCoreService`. The resolver's
injection relies on that binding; this design does not introduce a new `AsyncDial` scope.

#### 4.3 `_DialPromptSkillsContext` (request-scoped)

**Owner:** `dial_prompt_skills/`.

A thread-safe bag of request-scoped state. Mirrors `_MCPToolingContext` in spirit but does **not** subclass
`ToolingContextBase` — the base class pins `_tools` as a field name, which does not fit the skills domain.
`_DialPromptSkillsContext` is a standalone class with skills-specific field names
(`_resolved_skills`, `_exceptions`). If a third request-scoped context with the same shape appears, the
three can be refactored onto a shared generic base; until then, the code reads more clearly without the
indirection.

| `_MCPToolingContext` | `_DialPromptSkillsContext` |
|---|---|
| `_tools: list[StagedBaseTool]` | `_resolved_skills: list[ResolvedDialPromptSkill]` |
| `_exceptions: list[ToolInitializationException]` | `_exceptions: list[SkillInitializationException]` |
| `append_tool` / `extend_tools` | `extend_resolved_skills` |
| `append_exception` | `append_exception` / `extend_exceptions` |
| `_lock: threading.Lock` | `_lock: threading.Lock` |

`_exceptions` is typed as `list[SkillInitializationException]`. Because `SkillCatastrophicInitializationException`
subclasses it, catastrophic entries live in the same list — no separate `_catastrophic_failure` field, no
sentinel values. The handler distinguishes them via `isinstance` (§4.4).

`DialPromptSkillsModule` exposes the exceptions list via a `@multiprovider → list[InitializationException]`
binding, which widens the element type via subclass covariance. The unified `_InitializationErrorHandler`
injects the merged `list[InitializationException]` directly — the context object is not injected into the
handler, and neither is the module-specific type. This mirrors how `_MCPToolingContext` surfaces its
`list[ToolInitializationException]` today, but with the shared base type so both modules' contributions
concatenate into one injected list at the handler.

**Collision exceptions from `SkillsRegistry`.** The registry appends predefined-vs-external name collisions
to the context's `_exceptions` list during its merge (see §3). Because the merge runs in message
finalization (§4.1) and the handler runs *after* finalization (§4.1 table), these collisions surface
alongside fetch/validation entries in the same `Skill loading` section — one consolidated UI surface.

**Mutator call sites.** The initializer calls `extend_exceptions(resolver_output.exceptions)` with the
resolver's list in one shot, and `append_exception(SkillCatastrophicInitializationException(...))` when it
catches a resolver-level exception. `SkillsRegistry` calls `append_exception(...)` once per
predefined-vs-external collision it detects during merge. Note that `extend_exceptions` has no counterpart
on `_MCPToolingContext` — see "Divergence from `_MCPToolingContext`" below.

**Divergence from `_MCPToolingContext`.** `ToolingContextBase` (from which `_MCPToolingContext` inherits)
exposes only `append_exception`, not `extend_exceptions`. The new context's `extend_exceptions` is added to
serve the initializer's bulk-push path, which has no analogue on the MCP side. When these contexts are
eventually refactored onto a shared generic base, that base will need both variants; flagging here so the
future refactor doesn't silently drop the bulk-push method.

If a second skill source is introduced later (e.g. `"custom"` inline skills with their own initializer), it
subclasses `SkillInitializationException` for its failure modes and binds its own
`@multiprovider → list[InitializationException]`. The handler's `Skill loading` section renders all such
subclasses uniformly — no extra wiring at the handler.

#### 4.4 `_InitializationErrorHandler` — generalized via merged multiprovider

**Owner:** `core/application/`. The existing handler at
`src/quickapp/core/application/_initialization_error_handler.py` is generalized in place; no new handler class
is introduced, and no separate skill-specific handler exists.

Today the handler injects `ProviderOf[list[ToolInitializationException]]` and renders a dedicated
tool-init stage. The feature generalizes it so that one handler renders **one stage with one section per
feature that reported an issue**, driven entirely by a single merged `list[InitializationException]`.
Adding a new feature means binding one `@multiprovider → list[InitializationException]` in the new
module and adding one `isinstance` branch in the handler — no new handler, no new stage, no new injection.

**Constructor dependencies after generalization.** Two injected dependencies total, regardless of how
many features contribute.

| Dependency | Source | Used for |
|---|---|---|
| `ProviderOf[Stage]` | `Choice.create_stage()` | opens the unified stage |
| `ProviderOf[list[InitializationException]]` | merged across `@multiprovider` bindings in every feature module (`MCPToolingModule`, `DialPromptSkillsModule`, …) | every section |

The merge is done by injector itself: each `@multiprovider → list[InitializationException]` provider
contributes its list, and the injector concatenates them at the injection site. No handler-side glue, no
optional context injection.

**Single method, `handle_initialization_issues()`**:

1. `exceptions = self.__exceptions_provider.get()` — one merged list.
2. Short-circuit to a no-op if the list is empty — no stage is opened.
3. Otherwise open one `Stage` named **`"Initialization issues"`** and write markdown containing a
   `####`-level section per feature-kind that has at least one entry:
   - **Tool initialization** (entries where `isinstance(e, ToolInitializationException)`): bullet per
     entry (`**{tool_name}{toolset_name}**: {e}`), followed by a fenced `details` block when present.
     Same format as today.
   - **Skill loading** (entries where `isinstance(e, SkillInitializationException)` — this subclass
     check also matches `SkillCatastrophicInitializationException`). The handler partitions this group
     into `catastrophics = [e for e in skill_exceptions if isinstance(e, SkillCatastrophicInitializationException)]`
     and `per_url = [e for e in skill_exceptions if not isinstance(e, SkillCatastrophicInitializationException)]`.
     Catastrophics render first under a distinct sub-header indicating DIAL prompts as a whole could not
     be loaded (fallback to predefined-only is in effect); then bullets for per-URL entries
     (`**{e.url}**: {e.reason}`).

   Sections for feature-kinds that reported nothing are omitted entirely.
4. Close the stage with a status derived from `is_hard`:
   - **`FAILED`** iff `any(e.is_hard for e in exceptions)`.
   - **`COMPLETED`** otherwise (for example, per-URL skill failures only, no tool failures, no
     catastrophics). The request always proceeds in both cases; the status flag is purely a UI cue.

Pipeline slot: after `finalize_messages()`, before `Orchestrator.invoke()` — see §4.1. Placing the
handler after finalization is required so that predefined-vs-external collision entries pushed into the
skill context by `SkillsRegistry` during the message-setup merge are visible to the handler's
multiprovider read. The handler itself does not trigger resolution, merging, or any I/O.

**Transformer-ordering invariant.** Collision detection runs in `SkillsRegistry.get_prompt_part()`, which
is invoked by `_AddSystemPromptTransformer` during the transformer chain. If a future transformer runs
*after* `_AddSystemPromptTransformer` and raises, the exception bubbles out of `finalize_messages` before
the handler can surface collisions — acceptable, since the request is failing anyway — but the
prerequisite is that `_AddSystemPromptTransformer` is registered and reached on every non-failing path.
This is currently guaranteed by `AgentModule`'s transformer registration. Any future refactor that
reorders or conditionally skips `_AddSystemPromptTransformer` must re-evaluate this invariant.

**Call-site contract.** `handle_initialization_issues()` is called **exactly once** per request, from
`_QuickAppCompletion.chat_completion()`. It is not re-entrant and not idempotent: calling it twice would
open two stages. The short-circuit on empty input is a convenience (avoids opening an empty stage when
nothing was reported), not a signal that repeated invocation is safe. A future refactor that relocates the
call must preserve the single-invocation property.

**DI wiring when preview is disabled.** `DialPromptSkillsModule` is filtered out as before. With preview
off there is no `@multiprovider` contributing skill entries, so the merged
`list[InitializationException]` contains only tool entries; the Skill loading section is absent for
lack of matching isinstances. Behavior with respect to tool-init is unchanged.

---

## Secondary Fixes

### `skills/_exceptions.py` cleanup

`SkillResolutionWarning` (currently at `skills/_exceptions.py:15`) is deleted — superseded by
`SkillInitializationException` and `SkillCatastrophicInitializationException`, which are collected rather
than raised and live alongside `ToolInitializationException` in `common/exceptions/` (see §4.0).
`skills/_exceptions.py` retains only `SkillValidationError`.

### Configuration support API — skills endpoints

Two new endpoints on the `_Controller` in `configuration_support/`:

**1. List predefined skills — `GET /v1/configuration-support/skills`**

Returns `list[SkillMetadata]` — the full canonical model including `name`, `description`, `license`,
`compatibility`, `metadata`, and `allowed_tools`. No fields are trimmed: the editor needs visibility into
everything the frontmatter declared so it can display (e.g.) allowed-tool lists or licensing. The controller
depends on `AgentSkillsProvider` (which holds parsed metadata), not `ConfigResolver`. This mirrors
the `/system-prompts` endpoint pattern (returns structured metadata, not just names).

This endpoint is **predefined-only** — DIAL prompt skills are per-request (depend on user credentials) and
cannot be served from the singleton controller. The editor UI will see DIAL prompt skills through the config's
`skills` array, not through this endpoint.

**2. Validate a skill config entry — `POST /v1/configuration-support/skills/validate`**

Validates whether a skill config entry resolves to a valid skill. The editor (frontend) calls this when a user
adds or modifies an entry in the `skills` array, providing immediate feedback before saving.

**Request:** JSON body containing a single `SkillConfig` object (the discriminated union — the same shape as
one element of the `skills` array). Requires `api-key` header for skill types that fetch from DIAL Core (same
pattern as the existing `GET /v1/configuration-support/template/{deployment}` endpoint).

```json
{ "type": "dial-prompt", "url": "prompts/<bucket>/skills/my-skill" }
```

**Response on success:** `SkillMetadata` — the same canonical shape as the listing endpoint, including
`allowed_tools` and any other optional frontmatter fields.

**Response on failure:** HTTP error with a descriptive detail message:
- 404 — resource not found or inaccessible (e.g. DIAL prompt does not exist, permission denied).
- 422 — content is not a valid skill (empty content, missing/invalid frontmatter). The detail includes the
  `SkillValidationError` message so the user knows exactly what to fix.

**Dispatch by type.** The endpoint deserializes the body as `SkillConfig` (Pydantic handles the discriminated
union), then dispatches validation based on the `type` field. For `"dial-prompt"`: creates an `AsyncDial`
client with the request's `api-key`, fetches the prompt, validates with `parse_frontmatter`. Future variants
(e.g. `"custom"` with inline content) add their own validation branch without changing the endpoint contract.

**DI:** The controller gets `DialSettings` injected (singleton, already available). The `AsyncDial` client is
created per-request inside the endpoint handler using the `api-key` from the HTTP request — the same approach
used by `ToolConfigCoreService`. No new DI bindings are needed.

---

## Out of Scope

### Additional `SkillConfig` variants and cross-request caching

Future variants (inline `"custom"` skills, native `"dial-skill"` entities, per-app `"predefined"` selection)
and TTL-based caching of DIAL prompt content are deferred. The discriminated union and request-scoped fetch
leave room for them without architectural change.

### Skill subdirectories for DIAL prompt skills

DIAL prompts are single text documents — they cannot contain `scripts/`, `references/`, or `assets/`
subdirectories. This matches the existing limitation for predefined skills.

### URL canonicalization before dedup

The resolver deduplicates by raw `cfg.url` (§2). Trivially distinct spellings — trailing slash,
URL-encoded vs. decoded, mixed case in a bucket name — are treated as distinct and fetched twice. Adding
canonicalization via `aidial_client.helpers.storage_resource.DialStorageResourceMixin.get_api_path` (or an
equivalent helper) before the dedup pass is a five-minute change once we see it hit in practice. Tracked
as a follow-up rather than fixing preemptively.

---

## Configuration / Usage Examples

### Creating a skill-compatible DIAL prompt

A user creates a prompt in DIAL with content following the Agent Skills format:

```markdown
---
name: code-review-guidelines
description: Guidelines for reviewing code changes. Use when the user asks for a code review.
allowed-tools: [read_file, grep]
metadata:
  author: "team-platform"
  version: "1.0"
---

# Code Review Guidelines

When reviewing code, follow these steps:

1. Check for security vulnerabilities (injection, XSS, auth bypass)
2. Verify error handling covers edge cases
3. Ensure test coverage for new logic
4. Review naming conventions and code clarity
...
```

The prompt is stored at, e.g., `prompts/<user-bucket>/skills/code-review-guidelines`.

### QuickApp config referencing the prompt

```json
{
  "orchestrator": {
    "deployment": { "name": "gpt-4o" },
    "system_prompt": { "type": "predefined", "template": "gpt_prompt" }
  },
  "contexts": [],
  "tool_sets": [...],
  "skills": [
    {
      "type": "dial-prompt",
      "url": "prompts/<user-bucket>/skills/code-review-guidelines"
    }
  ]
}
```

### Resulting agent behavior

The agent's system prompt includes:

```xml
<available_skills>
  <skill>
    <name>tool-call-file-parameter-formatting</name>
    <description>Formats file and URL parameters for tool calls...</description>
  </skill>
  <skill>
    <name>code-review-guidelines</name>
    <description>Guidelines for reviewing code changes. Use when the user asks for a code review.</description>
    <allowed_tools>read_file grep</allowed_tools>
    <metadata>
      <entry key="author">team-platform</entry>
      <entry key="version">1.0</entry>
    </metadata>
  </skill>
</available_skills>
```

The `<allowed_tools>` element is a single space-joined string (matching what `generate_skills_xml` emits and
the space-separated `allowed-tools` form accepted in frontmatter), not nested `<tool>` children.

When the user asks "review my latest changes," the agent recognizes the relevant skill, calls `read_skill` with
`skill_name: "code-review-guidelines"`, receives the full markdown content, and follows the instructions.

### Invalid prompt example

If a DIAL prompt does not contain valid frontmatter:

```
This is just a regular prompt without any YAML frontmatter.
It talks about how to greet users politely.
```

The user sees the unified initialization stage in the response, containing only the relevant section
(no tool-init issues, so that section is omitted):

```
Initialization issues

#### Skill loading
- **prompts/<bucket>/greetings**: No YAML frontmatter found
```

The stage closes with `COMPLETED` (soft warning only) and the request proceeds without this skill.
If any tool-initialization exceptions were also present, a `#### Tool initialization` section would
appear in the same stage and its close status would flip to `FAILED`.

---

## Migration

### Breaking changes

None. The `skills` field is optional and defaults to `None`. Existing application configs are unaffected.

### Non-breaking changes

- `ApplicationConfig` gains a new optional `skills` field. Existing configs without it continue to work
  identically.
- The JSON schema grows to include `skills` and `DialPromptSkillConfig`. The editor UI should be updated to support
  the new field, but this is additive.
- `_SkillReaderTool` can now return content for DIAL prompt skills in addition to predefined skills. Agents that
  don't use `read_skill` are unaffected.
- `AgentSkillsProvider` remains a singleton and continues to serve predefined skills. Its internal behavior is
  unchanged.

---

## Summary of Changes

| Component | Change |
|---|---|
| **`common/exceptions/initialization.py`** (new) | `InitializationException(Exception)` base with `is_hard: ClassVar[bool] = True`. |
| **`common/exceptions/tool_initialization.py`** | `ToolInitializationException` now inherits from `InitializationException`; fields unchanged. |
| **`common/exceptions/skill_initialization.py`** (new) | `SkillInitializationException(InitializationException)` with `url: str` / `reason: str` and `is_hard = False`; `SkillCatastrophicInitializationException(SkillInitializationException)` with `is_hard = True`. |
| **`common/exceptions/__init__.py`** | Re-export the three new classes alongside existing symbols. |
| **`skills/_exceptions.py`** | Remove `SkillResolutionWarning` — superseded by `SkillInitializationException` in `common/exceptions/`. All call sites (`dial_prompt_skills/_dial_prompt_skill_resolver.py`, `skills/_skills_registry.py`) switch to the new class in the same commit. Keep `SkillValidationError` (still raised by `parse_frontmatter`). |
| **`config/skill.py`** (new) | `DialPromptSkillConfig` (`type: "dial-prompt"`) and `SkillConfig` discriminated union. |
| **`config/application.py`** | Optional `skills: list[SkillConfig] \| None` field on `ApplicationConfig`, gated by `PreviewField`. |
| **`skills/agent_skills_provider.py`** | Drop `PromptPartProvider` implementation; expose `get_all_skills()`, `get_all_skill_contents()`, `get_skill_content()` as a pure data store. |
| **`skills/_skill_metadata.py`** | Tighten `SkillMetadata.metadata` annotation from bare `dict` to `dict[str, Any] \| None` — adds shape without breaking frontmatter whose values are ints/lists/nested mappings. |
| **`skills/_skills_registry.py`** (new) | Request-scoped merger of predefined + context-resolved DIAL prompt skills; generates the combined `<available_skills>` XML. Appends predefined-vs-external collisions to `_DialPromptSkillsContext._exceptions` as `SkillInitializationException` instances. **Dependencies removed under this refactor:** `ProviderOf[Stage]`, `ProviderOf[ApplicationConfig]`, `DialPromptSkillResolver` — the registry no longer opens stages, reads config, or invokes fetching. Constructor reduces to `AgentSkillsProvider` + `_DialPromptSkillsContext \| None`. |
| **`skills/skills_module.py`** | Register `SkillsRegistry` as `PromptPartProvider`; remove `AgentSkillsProvider`'s `PromptPartProvider` registration. |
| **`skills/_skill_reader_tool.py`** | Depend on `SkillsRegistry`; call its synchronous `get_skill_content()`. |
| **`dial_prompt_skills/`** (new package) | `DialPromptSkillResolver` returning `DialPromptSkillResolverOutput(resolved, exceptions)`, `_DialPromptSkillInitializer`, `_DialPromptSkillsContext` (holds `_resolved_skills` and `_exceptions: list[SkillInitializationException]`), `DialPromptSkillsModule` (`@preview_module`) exposing `@multiprovider → list[InitializationException]` and `list[CompletionInitializer]`. |
| **`mcp_tooling/mcp_tooling_module.py`** | Widen `__provide_initialization_exceptions` return type from `list[ToolInitializationException]` to `list[InitializationException]` so both modules feed the same injected list. |
| **`application/_initialization_error_handler.py`** | Rename `handle_initialization_errors` → `handle_initialization_issues`. Inject `ProviderOf[list[InitializationException]]` (merged multiprovider) and `ProviderOf[Stage]`. Render one `"Initialization issues"` stage with `#### Tool initialization` and/or `#### Skill loading` sections grouped by `isinstance`; catastrophics render first within the Skill loading section. Close `FAILED` iff `any(e.is_hard for e in exceptions)`, otherwise `COMPLETED`. |
| **`application/_messages_setup.py`** | Decompose `setup()` into two public methods: `extract_tool_calls(messages)` (structural; runs pre-init) and `run_transformers(messages)` (transformer chain; runs post-init). Same combined behavior; `setup()` is removed. |
| **`application/_request_context_setup.py`** | Split into `setup_pre_init()` and `finalize_messages()` — see §4.1. `setup_pre_init` calls `extract_tool_calls`; `finalize_messages` calls `run_transformers`. |
| **`application/_quick_app_completion.py`** | New call order: `setup_pre_init` → initializers → `finalize_messages` → `_InitializationErrorHandler.handle_initialization_issues()` → `Orchestrator.invoke` (§4.1). |
| **`configuration_support/_controller.py`** | Add `GET /v1/configuration-support/skills` and `POST /v1/configuration-support/skills/validate`; inject `AgentSkillsProvider` and `DialSettings`. |
| **`app_factory.py`** | Register `DialPromptSkillsModule`. |
| **Tests** | `test_skills_registry.py` rewritten around `_DialPromptSkillsContext`; new tests for `_DialPromptSkillInitializer` and for the generalized `_InitializationErrorHandler` (no-op on empty list, COMPLETED on skill-only per-URL failures, FAILED on tool-only errors, FAILED on catastrophic-only, FAILED with both sections on mixed input); unit tests for `InitializationException` / `SkillInitializationException` / `SkillCatastrophicInitializationException` hierarchy. |
| **App schema + docs** | `make dump_app_schema` regenerates to include `skills`; `docs/agent.md` and `docs/skills.md` updated to cover DIAL prompt skills. |
