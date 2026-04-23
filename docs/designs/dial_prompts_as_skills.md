# Design: DIAL Prompts as Skills

- **Status:** Draft
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
- **`ai-dial-client-python` prompts resource**: A new `Prompts` / `AsyncPrompts` resource class in the client
  library for fetching prompt content from DIAL Core.

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
is skipped and the user sees a warning stage explaining the issue (e.g., "Missing required fields
(name/description) in prompts/\<bucket\>/my-prompt").

**Outcome:** The request proceeds normally. Other skills (predefined and valid DIAL prompt skills) remain
available. The agent does not see the invalid skill.

### UC-3: DIAL prompt is inaccessible

**Trigger:** The config references a DIAL prompt that does not exist, or the user lacks permission to access it.

**Behavior:** The DIAL Core API returns 404 or 403. The skill is skipped and the user sees a warning stage
explaining the fetch failure.

**Outcome:** Same as UC-2 — graceful degradation. The request is served with remaining skills.

### UC-4: Name collision between DIAL prompt skill and predefined skill

**Trigger:** A DIAL prompt skill has the same `name` as a predefined skill.

**Behavior:** The predefined (admin-configured) skill takes precedence — it is never overridden by user content.
The DIAL prompt skill is skipped and the collision is reported in the warning stage.

**Outcome:** The agent sees the predefined version of the skill. Admin-configured content always wins.

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

**Config model:**

```python
# config/skill.py (new file)

class DialPromptSkillConfig(BaseModel):
    type: Literal["dial-prompt"] = Field(
        description="Skill sourced from a DIAL prompt.",
    )
    url: Annotated[str, DialResourceConfigField(
        description="Relative prompt URL in DIAL (e.g. prompts/<bucket>/<path>)"
    )]

SkillConfig = Annotated[
    DialPromptSkillConfig,    # extensible — more variants can be added later
    Field(discriminator="type"),
]
```

The `type` field drops `default="dial-prompt"`: on a `Literal` discriminator, a default can interfere with
Pydantic v2's discriminated-union dispatch once a second variant joins (the field must be explicit in the
input JSON for the discriminator to resolve). Editor autofill keeps working via the JSON schema's
`const`/`enum` hint.

The `type` discriminator is `"dial-prompt"` rather than `"dial"` because DIAL will later introduce first-class
skill entities. Reserving `"dial"` (or `"dial-skill"`) for that future integration avoids a rename or
backward-compatibility shim.

**Single-variant discriminator — intentional scaffolding.** `SkillConfig` is defined as an `Annotated[…,
Field(discriminator="type")]` even though it currently has only one variant. In Pydantic v2 the
`discriminator=…` is a no-op until a second member joins the union, so functionally the alias is equivalent
to `SkillConfig = DialPromptSkillConfig`. The annotated form is kept deliberately to (a) make the JSON
schema's `oneOf`/`anyOf` shape ready for the first additional variant and (b) signal to callers that
`type` is the discriminator key. When the second variant lands (see "Out of Scope" — `"custom"` inline
skills, native `"dial-skill"` entities), the alias expands to `Union[DialPromptSkillConfig,
OtherSkillConfig]` with no change in call sites.

**`url` field annotation — `DialResourceConfigField`:** The `url` field is annotated with the existing
`DialResourceConfigField` (emits `dial:resource: true` in the JSON schema). This is the same annotation used by
`DialMCPToolSet.dial_id` and `DialDeploymentSimpleTool.deployment_id`. DIAL Core recognizes `dial:resource`
fields and performs auto-sharing for the referenced resources at deployment time — the resource type (prompt) is
inferred from the URL prefix (`prompts/...`). No new metaschema extension is needed.

**URL format:** The `url` value must be a relative path including the `prompts/` resource type prefix, e.g.
`prompts/<bucket>/folder/my-skill`. This follows the same convention as `FileContextConfig.url` (which uses
`files/<bucket>/...`). The `DialStorageResourceMixin.get_api_path()` in the client library parses this format
and validates the resource type. Absolute URLs are not supported — the client's `safe_parse_storage_resource()`
rejects them.

**Change to `ApplicationConfig`:**

```python
class ApplicationConfig(BaseApplicationTypeConfig):
    ...
    skills: list[SkillConfig] | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Optional list of user-configured agent skills.",
    )
```

The field uses `PreviewField` with `default=None`, following the established preview feature gating pattern
(see `Features.timestamp` for reference). When `ENABLE_PREVIEW_FEATURES=false`:
- The field is stripped from the published JSON schema via `_strip_preview_fields()`.
- At runtime, the `_gate_preview_fields` model validator on `ApplicationConfig` nullifies it, so any
  user-supplied value is silently discarded.

**Semantics:**
- `None` (default) or empty list: no user-configured skills. Predefined skills remain available.
- Each entry describes a source from which to fetch skill content at request time.
- The discriminated union starts with a single variant (`DialPromptSkillConfig`) but is designed for extensibility
  (e.g. a future `"custom"` variant with inline content, `"dial"` / `"dial-skill"` for native DIAL skill
  entities once available, or a `"predefined"` variant to selectively enable built-in skills).

**Schema impact:** `make dump_app_schema` regenerates the JSON schema to include the new `skills` field. The
editor (frontend) will need to support the new field to provide a UI for configuring skills.

### 2. `ai-dial-client-python` — Prompts resource

No separate `DialPromptService` is needed in the backend — unlike `DialFileService` (which adds caching via
`StateHolder` and a size-limit check), prompt fetching is a simple GET with no extra logic. The
`DialPromptSkillResolver` injects `AsyncDial` directly and calls `prompts.get()`.

**Owner:** `ai-dial-client-python` library (separate repo).

**What:** A new `Prompts` / `AsyncPrompts` resource class and a `Prompt` type model.

#### 2.1 Type model

```python
# aidial_client/types/prompt.py (new file)

class Prompt(ExtraAllowModel):
    """A DIAL prompt resource."""
    id: str
    name: str
    folder_id: str           # camelCase alias: folderId
    content: str | None = None
```

The model uses `ExtraAllowModel` for forward compatibility with additional fields DIAL Core may add.

#### 2.2 Resource class

```python
# aidial_client/resources/prompts.py (new file)

class Prompts(Resource, DialStorageResourceMixin):
    metadata: Metadata
    resource_type: str = "prompts"

    def get(self, url: Union[str, PurePosixPath]) -> Prompt:
        """Fetch a single prompt by its storage path."""
        return self.http_client.request(
            cast_to=Prompt,
            options=FinalRequestOptions(
                method="GET",
                url=urljoin(API_PREFIX, self.get_api_path(str(url))),
            ),
            on_http_error=_prompts_error_processor,
        )

    def get_metadata(self, url: Union[str, PurePosixPath]) -> PromptMetadata:
        return self.metadata.get(
            resource="prompts",
            relative_url=self.get_api_path(str(url)),
        )

class AsyncPrompts(AsyncResource, DialStorageResourceMixin):
    metadata: AsyncMetadata
    resource_type: str = "prompts"

    async def get(self, url: Union[str, PurePosixPath]) -> Prompt:
        """Fetch a single prompt by its storage path."""
        return await self.http_client.request(
            cast_to=Prompt,
            options=FinalRequestOptions(
                method="GET",
                url=urljoin(API_PREFIX, self.get_api_path(str(url))),
            ),
            on_http_error=_prompts_error_processor,
        )

    async def get_metadata(self, url: Union[str, PurePosixPath]) -> PromptMetadata:
        return await self.metadata.get(
            resource="prompts",
            relative_url=self.get_api_path(str(url)),
        )
```

This follows the exact pattern of the existing `Files` / `AsyncFiles` resource — `DialStorageResourceMixin`
provides `get_api_path()` and `get_storage_resource()` helpers for URL normalization.

#### 2.3 Client registration

Register in `Dial._init_resources()` and `AsyncDial._init_resources()`:

```python
self.prompts = resources.Prompts(
    http_client=self._http_client,
    metadata=self.metadata,
    dial_api_url=self.api_url,
)
```

#### 2.4 Scope of client changes

Only read operations (`get`, `get_metadata`) are needed for this feature. Write operations (`create`, `update`,
`delete`) can be added later if needed by other consumers. This keeps the change minimal and focused.

### 3. Skill resolution — `DialPromptSkillResolver`

**Owner:** `dial_prompt_skills/` package (new).

The DIAL prompt skill integration is a separate module from the core `skills/` package. `skills/` owns the
framework (what a skill is, how it's surfaced to the agent). `dial_prompt_skills/` owns a specific skill
**source** (where to fetch skills from). This separation keeps `skills/` source-agnostic and mirrors how
tool types each have their own package (`rest_api_tooling/`, `mcp_tooling/`, `dial_deployment_tooling/`) while
the common tool framework lives in `common/`.

**What:** A request-scoped component that resolves `DialPromptSkillConfig` entries into validated `SkillMetadata`
objects with their full content. Injected with the request-scoped `AsyncDial` client directly (no intermediate
service needed — prompt fetching is a simple GET with no caching or size-limit logic).

**Semantics:**

```
ApplicationConfig.skills
  └──> DialPromptSkillResolver.resolve(skill_configs)
         ├── For each DialPromptSkillConfig:
         │     ├── Fetch prompt via AsyncDial.prompts.get(url)
         │     ├── Extract prompt.content
         │     ├── Parse YAML frontmatter (reuse parse_frontmatter from skills/)
         │     ├── Validate per Agent Skills spec
         │     └── Return (SkillMetadata, full_content) or skip with warning
         └── Return list of resolved skills
```

**Content guard:** Before parsing, the resolver checks `prompt.content`. If `content` is `None`, empty, or
whitespace-only (matching the current `not prompt.content.strip()` check), the skill is recorded as a
warning (e.g., "DIAL prompt at \<url\> has no content"). This handles prompts that exist but have no body —
`parse_frontmatter` expects a non-trivial `str`, so a `None`/empty body would otherwise raise or produce an
unhelpful "no frontmatter" error.

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
same skill `name`, the first one (by config order) wins and the duplicate is recorded as a warning.

**URL normalization is not performed.** Deduplication uses the raw `cfg.url` string. Two entries spelled
differently (trailing slash, URL-encoded vs. decoded, mixed case in a bucket name) are treated as distinct
and fetched twice. If both resolve to the same skill `name`, the second one produces a duplicate-name
warning. This is acceptable for a preview feature; canonicalizing via `DialStorageResourceMixin.get_api_path`
before dedup can be added later if spelling variants become a real problem in practice.

**Structured warning reporting.** The resolver does **not** log warnings or render UI stages itself. Instead,
it returns warnings alongside resolved skills so the caller — the initializer (see §6) — can route them to the
request-scoped skills context for later rendering. `SkillResolutionWarning` is a frozen Pydantic model (per
CODESTYLE §8) with two fields: `url` and `reason`. The resolver's signature:

```python
async def resolve(
    self,
    skill_configs: list[DialPromptSkillConfig],
) -> DialPromptSkillResolverOutput:
```

`DialPromptSkillResolverOutput` is a frozen Pydantic model with two fields, `resolved:
list[ResolvedDialPromptSkill]` and `warnings: list[SkillResolutionWarning]`. A named output model is used
rather than a bare tuple so callers read the fields by name (CODESTYLE §8 — "Pydantic models for complex
structures"). `ResolvedDialPromptSkill` (also a frozen Pydantic model) carries the source `url`, the parsed
`SkillMetadata`, and the full `content` — the initializer needs the URL for collision-warning messages and
for future cross-request debugging.

All failure modes — fetch exceptions, empty content, invalid frontmatter (via `SkillValidationError`), and
duplicate names — produce a `SkillResolutionWarning` with the prompt URL and a human-readable reason. The
resolver never calls `logger.warning()` — all diagnostic information flows through the return value.

**Error handling:** Each skill config is resolved independently. A failure in one does not affect others.
Parallel fetches use `asyncio.gather(..., return_exceptions=True)` — the resolver collects exceptions from the
result list, converting each into a `SkillResolutionWarning` with enough context to diagnose (prompt URL,
error type). Without `return_exceptions=True`, the first exception would cancel all remaining tasks.

**DI module — `DialPromptSkillsModule`:** Decorated with `@preview_module` and registered in `AppFactory`
alongside the other feature modules. When `ENABLE_PREVIEW_FEATURES=false`, `AppFactory` filters out the module
entirely — no resolver is bound, and no DIAL prompt fetching occurs. Binds `DialPromptSkillResolver`,
`_DialPromptSkillInitializer`, and `_DialPromptSkillsContext` at `request_scope` (see §6), and exposes the
initializer as a `CompletionInitializer` and the context's warnings list via `@multiprovider` — same pattern as
`MCPToolingModule`.

### 4. Async transformer and prompt provider interfaces

**Owner:** `common/abstract/` package.

**What:** `PromptPartProvider.get_prompt_part()` and `MessagesTransformer.transform()` are `async`. Even though
skill resolution has moved to the initialization phase (see §6) and the registry itself no longer performs
I/O in `get_prompt_part()`, the async signatures are retained as the general contract for these extension
points.

**Why keep async despite eager resolution?** The interfaces were originally made async so that
`PromptPartProvider`s could perform asynchronous I/O during prompt assembly. With the refactor in §6, the
skills registry no longer needs that capability. We retain the async contract for two reasons: (1) concrete
near-term providers plausibly need async — e.g. a future `DynamicContextPromptProvider` that fetches
user-specific project context per request, or an `UserMemoryPromptProvider` that reads from a user-scoped
state service — both fit the `PromptPartProvider` slot naturally but need I/O at prompt-assembly time; and
(2) reverting the signature would ripple through every transformer implementation, test, and call site for
negligible benefit. `async def` methods whose bodies are fully synchronous incur only a trivial overhead per
call.

An alternative — reverting to a synchronous interface and keeping the eager-resolution wiring — was
considered. It removes dead asynchrony but doubles the size of the refactor's diff without removing any
runtime cost on the hot path. Out of scope for this revision; can be reconsidered if no async
`PromptPartProvider` materializes.

**Changes:**

| Component | Before | After |
|---|---|---|
| `PromptPartProvider.get_prompt_part()` | `def get_prompt_part(self) -> str` | `async def get_prompt_part(self) -> str` |
| `MessagesTransformer.transform()` | `def transform(self, messages) -> list[Message]` | `async def transform(self, messages) -> list[Message]` |
| `_MessagesSetup.setup()` | `def setup(self, messages) -> list[Message]` | `async def setup(self, messages) -> list[Message]` |

**Impact on existing implementations** — all become `async def` with no body changes:

| Implementation | Actual async work? |
|---|---|
| `ConfigBasedPromptProvider.get_prompt_part()` | No — returns config string |
| `AgentSkillsProvider.get_prompt_part()` | No — returns cached XML |
| `_AddSystemPromptTransformer.transform()` | Yes — awaits `get_prompt_part()` on each provider |
| `_AttachmentNotificationInjector.transform()` | No |
| `_InjectFileTransferInstructionTransformer.transform()` | No |
| `_TimestampInjectionTransformer.transform()` | No |

**Call site.** `_MessagesSetup.setup()` is invoked in the post-initializer phase — see §6.1 for the new
pipeline order. The signature is unchanged; only the call site moves.

**`PreInvocationTransformer` is not affected.** `base_transformer.py` defines both `MessagesTransformer` (runs
once at setup) and `PreInvocationTransformer` (runs before every LLM call in
`AssistantInvoker.__prepare_messages()`). Only `MessagesTransformer` is async. `PreInvocationTransformer`
remains synchronous — it has no async needs and runs in a different call path.

**`ConfigurationRequest` path:** `_MessagesSetup.setup()` is only called for `Request` (chat completion),
not for `ConfigurationRequest`. No change needed.

### 5. Skills registry — request-scoped skill merging

**Owner:** `skills/` package.

**What:** A request-scoped `SkillsRegistry` that merges predefined skills (from the singleton
`AgentSkillsProvider`) with external skills that were already resolved during the initialization phase (see
§6) into a unified skill set for the current request. Implements `PromptPartProvider`.

**Why a new component?** `AgentSkillsProvider` is a singleton that loads skills eagerly at startup. External
skills (e.g. from DIAL prompts) are per-request (they depend on user credentials and may change between
requests). Merging these two sources requires a request-scoped component.

**Resolution timing — eager, not lazy.** External skills are fetched during the initialization phase by
`_DialPromptSkillInitializer` (see §6), which populates `_DialPromptSkillsContext` before the agent invoker
runs. By the time any `PromptPartProvider` is consulted, every DIAL prompt skill has already been fetched
(or failed), and every warning has already been collected. The registry therefore does **no I/O** — it is a
pure in-memory merge over two ready data sources.

The prior revision of this design had the registry perform lazy fetching inside `get_prompt_part()` and
render UI stages for failures. That conflated three responsibilities in one class: I/O orchestration, data
merging, and presentation. Moving I/O to a dedicated initializer (§6) and presentation to a dedicated
handler (§6) aligns skills with the MCP tool initialization pattern — see `_MCPToolInitializer`,
`_MCPToolingContext`, and `_InitializationErrorHandler`.

**Semantics:**

- Constructed per-request with injected `AgentSkillsProvider` (singleton), and `_DialPromptSkillsContext`
  (request-scoped, optional — see §6). The registry no longer depends on `DialPromptSkillResolver`,
  `ProviderOf[ApplicationConfig]`, or `ProviderOf[Stage]`.
- `async get_prompt_part() -> str` — builds the merged metadata list (predefined + context-resolved DIAL
  prompt skills, with collisions dropped) and returns the combined XML. Cached in-memory after the first
  call for the rest of the request. No fetching, no error handling here — by contract, the context is
  populated (or empty) by the time this method runs. Stays `async` to match the `PromptPartProvider` ABC
  (§4).
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
   `SkillResolutionWarning` that is pushed into the context (so the warning stage in §6 picks it up).
   Collision detection happens in the registry, not the initializer, because only the registry can compare
   against predefined names.
3. The registry generates combined XML from the merged metadata list. XML generation is owned exclusively
   by `SkillsRegistry` — no other component produces XML.

**Skill precedence summary.** Combining §3's resolver-level dedup with the registry's predefined-wins rule
gives a single three-level precedence:

| Priority | Source | Behavior on conflict |
|---|---|---|
| 1 (highest) | Predefined skill (`AgentSkillsProvider`) | Always wins |
| 2 | First DIAL prompt skill by config order with a given `name` | Beats subsequent DIAL prompt entries with the same name |
| 3 (lowest) | Subsequent DIAL prompt skills with an already-seen name | Dropped; duplicate-name `SkillResolutionWarning` emitted |

A DIAL prompt skill demoted by rule 1 produces a "predefined takes precedence" warning; one demoted by
rule 3 produces a "duplicate skill name" warning. Both flow to the same stage via the context.

**`SkillMetadata.metadata` typing.** The refactor also tightens the `metadata` field annotation on
`SkillMetadata` from the current bare `dict` (at `src/quickapp/skills/agent_skills_provider.py:18`) to
`dict[str, str] | None`. This field appears in every JSON schema emitted by `make dump_app_schema` and in
every response of `/v1/configuration-support/skills`, so a precise type pays off more than a typical
internal refinement.

**Collision warnings are detected at merge, reported via the context.** The initializer cannot detect
predefined-vs-DIAL-prompt name collisions (it has no reference to the predefined set). The registry detects
them during its merge and appends them to the same `_DialPromptSkillsContext`. Because the context feeds the
warning handler (§6.4), collision warnings reach the user through the same stage as fetch/validation
warnings — one consolidated UI surface. The pipeline reshuffle in §6.1 is what makes this safe: the registry
runs its merge (in the post-init phase, during `_AddSystemPromptTransformer`) *before* the warning handler
reads the merged list.

**`AgentSkillsProvider` becomes a pure data store.** The singleton drops its `PromptPartProvider`
implementation entirely — no more `get_prompt_part()`, `get_skills_xml()`, `_generate_xml()`, or
`_escape_xml()`. It retains only:
- `get_all_skills() -> list[SkillMetadata]` — returns the cached list of predefined skill metadata.
- `get_all_skill_contents() -> dict[str, str]` — returns `{name: full_content}` for all predefined skills.
- `get_skill_content(name: str) -> str` — still needed by `_InjectFileTransferInstructionTransformer`.

Each skill source (`AgentSkillsProvider`, `_DialPromptSkillsContext`) produces `list[SkillMetadata]` +
content. The registry is the single point that merges metadata, converts to XML, and exposes the result via
`PromptPartProvider`.

**`_InjectFileTransferInstructionTransformer` stays on `AgentSkillsProvider`.** This transformer only reads the
predefined `tool-call-file-parameter-formatting` skill — a built-in skill that is always available regardless
of user config. It does not need the registry and should not depend on it.

**Impact on `_SkillReaderTool`:** The tool's dependency changes from `AgentSkillsProvider` to `SkillsRegistry`.
When the agent calls `read_skill`, the registry looks up the skill by name in the merged (deduplicated) set.

### 6. Eager resolution — pipeline reshuffle, initializer, context, and warning handler

**Owner:** `dial_prompt_skills/` package for the new components; `application/` package for the pipeline
reshuffle; `skills/` package for the warning handler. The wiring mirrors MCP tooling.

**Why eager.** The previous revision of this design resolved DIAL prompt skills lazily inside
`SkillsRegistry.get_prompt_part()` and rendered failures through a stage that `SkillsRegistry` opened
directly. That shape has two problems:

1. **Responsibility smear.** The registry owned I/O, data merging, and UI presentation in one class. Each
   of those concerns evolves for different reasons.
2. **Inconsistency with MCP tool initialization.** Tool failures already flow through
   `_MCPToolingContext.append_exception` → `list[ToolInitializationException]` multiprovider →
   `_InitializationErrorHandler`. Skills invented a parallel, incompatible presentation mechanism.

Moving skill resolution to the initializer phase requires a pipeline reshuffle (§6.1) because message
transformation currently runs *before* initializers. Everything else in this section depends on that
reshuffle being in place.

#### 6.1 Pipeline reshuffle — message transformation moves post-initializer

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

This revision splits `_RequestContextSetup` into two phases and moves message transformation to a new step
that runs **after** initializers:

| Step | Responsibility | Runs |
|---|---|---|
| `_RequestContextSetup.setup_pre_init(request, choice)` | populate `api_key`, `bearer`, `application_config`, raw `messages`, `forwarded_headers`, `client_channel_id`, `response_format` | before `invoke_initializers` |
| `invoke_initializers(InitializerType.completion)` | run initializers — including `_DialPromptSkillInitializer` and existing tool initializers | — |
| `_InitializationErrorHandler.handle_initialization_errors()` | render "Tool initialization errors" stage | — |
| `_RequestContextSetup.finalize_messages()` | internally calls `_MessagesSetup.setup()` and stores the transformed messages on `_RequestContext`; runs every `MessagesTransformer`, including `_AddSystemPromptTransformer` which produces the system prompt | after handler above |
| `_SkillResolutionWarningHandler.handle_skill_resolution_warnings()` | render "Skill loading warnings" stage (see §6.4) | after messages finalize |
| `Orchestrator.invoke()` | run the agent | — |

`finalize_messages()` is a method on `_RequestContextSetup`, not a direct call to `_MessagesSetup` from
`_QuickAppCompletion`. Keeping the split inside one class means `_QuickAppCompletion` only knows two
context-setup entry points (pre-init, finalize), and `_RequestContextSetup` stays the single authority over
what lives on `_RequestContext`.

All existing `MessagesTransformer` implementations continue to work unchanged — they just run later. The
split only affects the order of the two halves of context setup. No transformer today depends on initializer
output *except* `_AddSystemPromptTransformer` via the new `SkillsRegistry` contract in §5; the reshuffle is
what unlocks that dependency.

**Interaction with `_InjectFileTransferInstructionTransformer`.** This transformer reads the predefined
`tool-call-file-parameter-formatting` skill from `AgentSkillsProvider` (a singleton populated at startup). It
does not depend on any request-scoped initializer. It runs in the post-init phase like every other
`MessagesTransformer` — nothing changes from its perspective.

**Backward compatibility.** `_MessagesSetup.setup()` keeps its signature; only its call site moves. External
API is untouched.

#### 6.2 `_DialPromptSkillInitializer` (`CompletionInitializer`)

**Owner:** `dial_prompt_skills/`.

Implements `CompletionInitializer.initialize()`. Reads `ApplicationConfig.skills` via `ProviderOf`, delegates
to `DialPromptSkillResolver.resolve(skill_configs)`, and pushes both halves of the return tuple into
`_DialPromptSkillsContext`. If `skills` is `None`/empty, the initializer is a no-op. If the resolver raises,
the initializer catches the exception and records a dedicated *catastrophic* entry — see §6.3's
`catastrophic_failure` field — then returns. The request proceeds with predefined skills only. This matches
the graceful-degradation semantics in §3.

**Reachability of the catastrophic branch.** The resolver's per-URL paths already go through
`asyncio.gather(return_exceptions=True)`, so individual fetch failures become per-URL
`SkillResolutionWarning`s, not raised exceptions. And because `AsyncDial` is injected into the resolver's
constructor, any client-construction failure would surface during `invoke_initializers`'s injector lookup,
not inside `initialize()`. The catastrophic branch therefore only covers a narrow class of synchronous
bugs — e.g. `asyncio.gather` raising before it can schedule (unlikely), or a `TypeError`/`AttributeError`
from a coding mistake in the resolver. We still keep the distinct field (rather than folding into
`warnings` with an empty `url`) because when it fires the UI header should say "DIAL prompts as a whole
could not be loaded" rather than presenting a lone stray warning that is indistinguishable from a
per-URL issue. If in practice this field never fires in production over several releases, we can collapse
it into the warnings list then.

Registered as one of `list[CompletionInitializer]` via `DialPromptSkillsModule`'s `@multiprovider`, same way
`_MCPToolInitializer` is registered by `MCPToolingModule`.

**Initializer concurrency.** `invoke_initializers` iterates and awaits each initializer sequentially (see
`src/quickapp/common/base_initializer.py:30-34`). DIAL prompt fetches do **not** overlap MCP tool
initialization: the DIAL prompt initializer runs before or after the MCP one depending on registration
order. Parallelism within `_DialPromptSkillInitializer` comes from `asyncio.gather` *inside* its
`resolve()` delegate (§3), which fans out per-URL fetches. Inter-initializer concurrency would require
changing `invoke_initializers` to `asyncio.gather` across all initializers — a separate concern with its
own trade-offs (ordering assumptions, error-propagation semantics) and is out of scope for this design.

**Request-scoped `AsyncDial`.** `DialPromptSkillResolver.__init__` takes `AsyncDial` as a constructor
dependency. `AppModule` already provides a request-scoped `AsyncDial` bound with the current request's
`api-key` — the same instance used by `DialFileService` and `ToolConfigCoreService`. The resolver's
injection relies on that binding; this design does not introduce a new `AsyncDial` scope.

#### 6.3 `_DialPromptSkillsContext` (request-scoped)

**Owner:** `dial_prompt_skills/`.

A thread-safe bag of request-scoped state. Mirrors `_MCPToolingContext` in spirit but does **not** subclass
`ToolingContextBase` — the base class pins `_tools` / `_exceptions` as field names, which do not fit the
skills domain. `_DialPromptSkillsContext` is a standalone class with skills-specific field names
(`_resolved_skills`, `_warnings`, `_catastrophic_failure`). If a third request-scoped context with the same
shape appears, the three can be refactored onto a shared generic base; until then, the code reads more
clearly without the indirection.

| `_MCPToolingContext` | `_DialPromptSkillsContext` |
|---|---|
| `_tools: list[StagedBaseTool]` | `_resolved_skills: list[ResolvedDialPromptSkill]` |
| `_exceptions: list[ToolInitializationException]` | `_warnings: list[SkillResolutionWarning]` |
| — | `_catastrophic_failure: SkillResolutionWarning \| None` |
| `append_tool` / `extend_tools` | `extend_resolved_skills` |
| `append_exception` | `append_warning` / `extend_warnings` / `set_catastrophic_failure` |
| `_lock: threading.Lock` | `_lock: threading.Lock` |

**Catastrophic failures are a distinct field, not a sentinel warning.** A per-URL failure is a
`SkillResolutionWarning(url=..., reason=...)`; a top-level failure (DIAL prompts as a whole could not be
loaded) is captured in the `_catastrophic_failure` field. The warning handler (§6.4) renders them
differently (different header, different severity wording). This removes the `url=""` sentinel from the
previous revision — no magic values, no special-casing in the warning renderer beyond "does this field
exist?".

`DialPromptSkillsModule` exposes the warnings list via `@multiprovider -> list[SkillResolutionWarning]`. The
catastrophic field is **not** exposed as a separate binding — `injector` resolves by exact type and
`Optional[X]` is fragile to bind. Instead, `_SkillResolutionWarningHandler` injects
`_DialPromptSkillsContext | None` directly (same optional-injection style as `SkillsRegistry`) and reads
`context.catastrophic_failure` as a property. This mirrors how `_MCPToolingContext.exceptions` is exposed
through the context object itself.

**Collision warnings from `SkillsRegistry`.** The registry appends predefined-vs-external name collisions to
the context's warnings list during its merge (see §5). Because the merge runs in the post-init phase (§6.1)
and the warning handler runs *after* the merge (§6.1 table), these collisions surface in the same stage as
fetch/validation warnings — one consolidated UI surface. No primer initializer is needed.

**Mutator call sites.** The initializer calls `extend_warnings(resolver_output.warnings)` with the
resolver's list in one shot; `SkillsRegistry` calls `append_warning(...)` once per predefined-vs-external
collision it detects during merge; the initializer calls `set_catastrophic_failure(...)` when it catches a
resolver-level exception.

If a second skill source is introduced later (e.g. `"custom"` inline skills with their own initializer), it
appends to the same context and gets rendered in the same stage at no extra wiring cost — identical to how
multiple tool initializers feed one error handler today.

#### 6.4 `_SkillResolutionWarningHandler`

**Owner:** `skills/`.

A small class analogous to `_InitializationErrorHandler`. Injected with `ProviderOf[Stage]` and
`_DialPromptSkillsContext | None` (optional — `None` when preview is disabled). **The handler reads both
warnings and catastrophic failure from the context — one source of truth, matching how
`_MCPToolingContext.exceptions` is consumed.** The `@multiprovider -> list[SkillResolutionWarning]` exposed
by `DialPromptSkillsModule` (§3) exists for other potential consumers (future metrics, logs, tests), not
for the handler itself. One method, `handle_skill_resolution_warnings()`:

- Returns immediately if context is `None` (preview disabled).
- Reads `context.warnings` and `context.catastrophic_failure`. If both are empty/`None`, returns (no stage
  rendered).
- Opens a fresh `Stage` titled **"Skill loading warnings"** — distinct from the
  `_InitializationErrorHandler` stage ("🚨 Tool initialization errors 🚨"). `ProviderOf[Stage]` yields a new
  `Stage` per `.get()` call (via `Choice.create_stage()` semantics), so the two handlers do not share a
  stage.
- If `catastrophic_failure` is set, renders it first with a distinct header explaining that DIAL prompts as
  a whole could not be loaded (fallback to predefined-only is in effect).
- Renders each warning as a bullet (`**{url}**: {reason}`).
- Closes with `Status.COMPLETED` — the request proceeds with remaining skills; this is a warning, not a
  failure.

The handler does not trigger skill resolution or merging itself — those are already complete by the time
it runs (see §6.1 call ordering). `SkillsRegistry` no longer injects `ProviderOf[Stage]`.

**Stage ownership summary.**

| Handler | Stage name | Close status | Source |
|---|---|---|---|
| `_InitializationErrorHandler` | "🚨 Tool initialization errors 🚨" | `FAILED` (UI-only; the request still proceeds) | tool initializers |
| `_SkillResolutionWarningHandler` | "Skill loading warnings" | `COMPLETED` | DIAL prompt skill resolver + registry merge |

**DI wiring when preview is disabled.** `DialPromptSkillsModule` is filtered out as before. With preview off:
- `_DialPromptSkillInitializer` is not bound; no DIAL prompt fetching occurs.
- `_DialPromptSkillsContext` is not bound; `SkillsRegistry` falls back to `None` via optional injection and
  sees only predefined skills. No collisions possible, so no collision warnings.
- The `list[SkillResolutionWarning]` multiprovider returns an empty list and the catastrophic provider
  returns `None`, so `_SkillResolutionWarningHandler` is a no-op.

---

## Secondary Fixes

### Extract `_parse_frontmatter` to `skills/_frontmatter.py`

The frontmatter parsing and Agent Skills spec validation logic currently lives as a static method on
`AgentSkillsProvider`. Both the provider (for predefined skills at startup) and `DialPromptSkillResolver`
(for DIAL prompt skills at request time) need it. Extract to `skills/_frontmatter.py` as a standalone
`parse_frontmatter(content: str, source_id: str)` function. The `source_id` parameter (renamed from
`file_name`) is used in error messages — callers pass a file path or prompt URL as appropriate. Both callers
import from there.

**Error reporting via exceptions, not logging.** `parse_frontmatter` raises `SkillValidationError` (a new
exception in `skills/`) on any validation failure — missing frontmatter, invalid YAML, missing required fields,
bad name format, etc. The exception message is human-readable and includes the `source_id` for context. The
function never calls `logger.warning()` or `logger.error()`.

Callers handle the exception differently depending on context:
- **`AgentSkillsProvider`** (predefined skills at startup): catches `SkillValidationError`, logs it, and
  skips the skill. This is an operator error — server logs are the right channel.
- **`DialPromptSkillResolver`** (DIAL prompt skills at request time): catches `SkillValidationError` and
  converts it into a `SkillResolutionWarning`, which flows up to the registry and is surfaced to the user
  via a stage.

### Move XML generation to `skills/_xml.py`

XML metadata generation (`_generate_xml()`, `_escape_xml()`) moves out of `AgentSkillsProvider` into
`skills/_xml.py` as standalone functions (`generate_skills_xml()`, `escape_xml()`). Only `SkillsRegistry`
imports these — the provider no longer generates XML. Whether the functions live in `_xml.py` or inline in
the registry is an implementation detail.

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

### Inline custom skills

A `type: "custom"` skill variant with inline `content` in the config (analogous to `CustomSystemPromptConfig`).
This would let users embed skill content directly without creating a DIAL prompt first.
**Why deferred:** The issue specifically targets DIAL prompts as the skill source. Inline skills can be added as
a follow-up variant of `SkillConfig` without architectural changes.

### Predefined skill selection

A `type: "predefined"` skill variant that selectively enables/disables built-in skills per-app.
**Why deferred:** Currently all predefined skills are always available. Per-app selection adds configuration
complexity and requires defining what "disabled" means (hide from XML? block `read_skill`?). Can be added later.

### DIAL prompt write operations in client library

The `ai-dial-client-python` changes only add read operations (`get`, `get_metadata`). Full CRUD (create, update,
delete) is not needed by QuickApps and can be added by other consumers of the library.

### Caching DIAL prompt content

DIAL prompts are fetched fresh on each request. Cross-request caching (e.g. with TTL) could reduce latency for
frequently used skills but adds complexity around cache invalidation.
**Why deferred:** Prompt fetches are lightweight (single GET, small payloads). Caching can be added as a
performance optimization if latency becomes a concern.

### Skill subdirectories for DIAL prompt skills

DIAL prompts are single text documents — they cannot contain `scripts/`, `references/`, or `assets/`
subdirectories. This limitation is inherent to the DIAL prompt storage model and matches the existing limitation
for predefined skills.

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

The user sees a warning stage in the response:

```
⚠️ Skill loading warnings

The following issues occurred while loading DIAL prompt skills:
- **prompts/<bucket>/greetings**: No YAML frontmatter found
```

The request proceeds normally without this skill.

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
- `ai-dial-client-python` gains a new `prompts` resource. Existing consumers of the library are unaffected.
- **Internal interface refactor:** `PromptPartProvider.get_prompt_part()` and `MessagesTransformer.transform()`
  are `async`. All existing implementations must add `async` to their method signatures. Test files that call
  `_MessagesSetup.setup()` or mock these interfaces need corresponding `await` / `AsyncMock` updates. This is
  not a public API break but touches multiple files across packages. (§4 explains why the async contract
  remains after the eager-resolution refactor.)

### Internal refactor from prior design revision

The prior revision of this design resolved DIAL prompt skills lazily inside `SkillsRegistry.get_prompt_part()`
and rendered failures from a stage the registry opened itself. This revision moves resolution to a
`CompletionInitializer`, moves message transformation to run post-initializer (§6.1), and moves stage
rendering to a dedicated handler (§6.4). The change is internal only:

- No user-visible config or behavior changes — the same `skills` config field, the same warning stage, same
  `read_skill` semantics.
- `_QuickAppCompletion.chat_completion()` runs phases in a new order: context pre-init → initializers →
  tool-init error handler → message finalization → skill-resolution warning handler → agent. This is an
  internal re-ordering; no external API changes.
- `_RequestContextSetup` is split: the old `.setup()` becomes `setup_pre_init()` (everything except message
  transformation) + `finalize_messages()` (runs `_MessagesSetup.setup()`). Callers update one line.
- `SkillsRegistry`'s constructor signature changes: drops `DialPromptSkillResolver`,
  `ProviderOf[ApplicationConfig]`, and `ProviderOf[Stage]`; adds optional `_DialPromptSkillsContext`. Tests
  that build a registry directly with these dependencies must be updated (the existing
  `test_skills_registry.py` fixtures construct it with mocks, and will need to be rewritten around the
  context).
- A new `_SkillResolutionWarningHandler` is called once per request from `_QuickAppCompletion`, in the slot
  described above.
- Pydantic models replace the earlier `@dataclass` declarations for `ResolvedDialPromptSkill` and
  `SkillResolutionWarning`, per CODESTYLE §8.

---

## Summary of Changes

### `ai-dial-client-python` (separate repository)

| Component | Change |
|---|---|
| **`types/prompt.py`** (new) | `Prompt` model: id, name, folder_id, content |
| **`resources/prompts.py`** (new) | `Prompts` / `AsyncPrompts` resource with `get()` and `get_metadata()` |
| **`resources/__init__.py`** | Export new `Prompts` / `AsyncPrompts` |
| **`_client.py`** | Register `self.prompts` in `Dial._init_resources()` and `AsyncDial._init_resources()` |

### `ai-dial-quickapps-backend`

| Component | Change |
|---|---|
| **`config/skill.py`** (new) | `DialPromptSkillConfig` (`type: "dial-prompt"`) model with `DialResourceConfigField`-annotated `url`, `SkillConfig` discriminated union. Drop the `default="dial-prompt"` from the `type` field (currently at `config/skill.py:10`) — unnecessary on a `Literal` and can interfere with discriminated-union dispatch once a second variant joins. |
| **`config/application.py`** | Add `skills: list[SkillConfig] \| None` field to `ApplicationConfig` |
| **`skills/_frontmatter.py`** (new) | Extracted `parse_frontmatter()` function (from `AgentSkillsProvider._parse_frontmatter`); raises `SkillValidationError` on invalid content |
| **`skills/_exceptions.py`** (new) | `SkillValidationError` exception class and `SkillResolutionWarning` Pydantic model |
| **`skills/_xml.py`** (new) | `generate_skills_xml()` and `escape_xml()` — moved from `AgentSkillsProvider`, imported only by `SkillsRegistry` |
| **`skills/agent_skills_provider.py`** | Remove `PromptPartProvider` implementation and XML generation; delegate to `_frontmatter.parse_frontmatter()`; expose `get_all_skills()`, `get_all_skill_contents()`, `get_skill_content()` as pure data store. Tighten `SkillMetadata.metadata` annotation from bare `dict` to `dict[str, str] \| None`. |
| **`dial_prompt_skills/` package** (new) | New package for DIAL prompt skill source integration |
| **`dial_prompt_skills/_dial_prompt_skill_resolver.py`** (new) | Request-scoped resolver: fetches DIAL prompts via request-scoped `AsyncDial`, validates as skills; returns `list[ResolvedDialPromptSkill]` + `list[SkillResolutionWarning]` (frozen Pydantic models per CODESTYLE §8). Never renders UI or logs. |
| **`dial_prompt_skills/_dial_prompt_skills_context.py`** (new) | Request-scoped, thread-safe bag of `resolved_skills`, `warnings`, and an optional `catastrophic_failure: SkillResolutionWarning \| None`. Mirror of `_MCPToolingContext`. |
| **`dial_prompt_skills/_dial_prompt_skill_initializer.py`** (new) | `CompletionInitializer` that reads `ApplicationConfig.skills`, calls the resolver, and populates the context. No-op when `skills` is empty; top-level failures set the context's `catastrophic_failure` field (not a sentinel warning). |
| **`dial_prompt_skills/dial_prompt_skills_module.py`** (new) | `@preview_module` DI module: binds resolver, initializer, and context at request-scope. Exposes the initializer via `multiprovider -> list[CompletionInitializer]` and the warnings list via `multiprovider -> list[SkillResolutionWarning]` — same shape as `MCPToolingModule`. The catastrophic failure field is read directly off the injected `_DialPromptSkillsContext` (no separate `Optional` binding). |
| **`common/abstract/base_prompt_provider.py`** | `get_prompt_part()` is `async` (unchanged from prior revision). |
| **`common/abstract/base_transformer.py`** | `MessagesTransformer.transform()` is `async` (unchanged from prior revision). |
| **`application/_messages_setup.py`** | `setup()` is `async`, awaits each transformer (unchanged from prior revision). |
| **`application/_request_context_setup.py`** | Split into `setup_pre_init()` (config, api_key, raw messages, forwarded headers, client channel, response_format) and `finalize_messages()` (runs `_MessagesSetup.setup()`). See §6.1. |
| **`application/_quick_app_completion.py`** | New call sequence: `setup_pre_init` → `invoke_initializers` → `_InitializationErrorHandler` → `finalize_messages` → `_SkillResolutionWarningHandler` → `Orchestrator.invoke`. See §6.1. |
| **`agent/_messages_transformers.py`** | `_AddSystemPromptTransformer.transform()` awaits `get_prompt_part()` (unchanged from prior revision). |
| **All other `MessagesTransformer` impls** | `async` keyword, no body changes (unchanged from prior revision). |
| **`skills/_skills_registry.py`** | Request-scoped registry: merges predefined (`AgentSkillsProvider`) + external (`_DialPromptSkillsContext`) data in `get_prompt_part()`. No I/O, no stage rendering. Appends predefined-vs-external name collisions to the context as `SkillResolutionWarning`. |
| **`skills/_skill_resolution_warning_handler.py`** (new) | Injects `ProviderOf[Stage]` and `_DialPromptSkillsContext \| None`; reads `context.warnings` and `context.catastrophic_failure` (one source of truth). Renders one "Skill loading warnings" stage if non-empty. Distinct stage from `_InitializationErrorHandler`. |
| **`skills/skills_module.py`** | Register `SkillsRegistry` (request-scope) as `PromptPartProvider`; register `_SkillResolutionWarningHandler`; remove `AgentSkillsProvider`'s `PromptPartProvider` multiprovider registration. |
| **`skills/_skill_reader_tool.py`** | Change dependency from `AgentSkillsProvider` to `SkillsRegistry`; call synchronous `get_skill_content()` (no `await`). |
| **`configuration_support/_controller.py`** | Add `GET /v1/configuration-support/skills` (predefined listing) and `POST /v1/configuration-support/skills/validate` (validates any `SkillConfig` entry) endpoints; add `AgentSkillsProvider` and `DialSettings` as constructor dependencies. |
| **Test files** | Update `test_skills_registry.py` to construct the registry from `_DialPromptSkillsContext` instead of a resolver + stage. Add tests for `_DialPromptSkillInitializer` and `_SkillResolutionWarningHandler`. Existing async-transformer test updates remain from prior revision. |
| **`app_factory.py`** | Register `DialPromptSkillsModule` in injector module list. |
| **`CODESTYLE.md`** | Add §8 rule: Pydantic `BaseModel` over `@dataclass`. |
| **`CLAUDE.md`** | Add "Data containers" bullet under Code Style. |
| **App schema** | Regenerated via `make dump_app_schema` to include `skills` field. |
| **`docs/agent.md`** | Update skills section to cover DIAL prompt skills. |
| **`docs/skills.md`** | Add "DIAL Prompt Skills" section with usage instructions. |
