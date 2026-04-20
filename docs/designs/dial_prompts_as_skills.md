# Design: DIAL Prompts as Skills

- **Status:** Implemented
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
        default="dial-prompt",
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

The `type` discriminator is `"dial-prompt"` rather than `"dial"` because DIAL will later introduce first-class
skill entities. Reserving `"dial"` (or `"dial-skill"`) for that future integration avoids a rename or
backward-compatibility shim.

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

**Content guard:** Before parsing, the resolver checks `prompt.content`. If `content` is `None` or empty, the
skill is recorded as a warning (e.g., "DIAL prompt at \<url\> has no content"). This handles prompts that exist
but have no body — `parse_frontmatter` expects a `str`, so a `None` would otherwise raise a `TypeError`.

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

**Structured warning reporting.** The resolver does **not** log warnings itself. Instead, it returns warnings
alongside resolved skills so the caller can surface them to the user:

```python
@dataclass
class SkillResolutionWarning:
    url: str
    reason: str

async def resolve(
    self,
    skill_configs: list[DialPromptSkillConfig],
) -> tuple[list[tuple[SkillMetadata, str]], list[SkillResolutionWarning]]:
```

All failure modes — fetch exceptions, empty content, invalid frontmatter (via `SkillValidationError`), and
duplicate names — produce a `SkillResolutionWarning` with the prompt URL and a human-readable reason. The
resolver never calls `logger.warning()` — all diagnostic information flows through the return value.

**Error handling:** Each skill config is resolved independently. A failure in one does not affect others.
Parallel fetches use `asyncio.gather(..., return_exceptions=True)` — the resolver collects exceptions from the
result list, converting each into a `SkillResolutionWarning` with enough context to diagnose (prompt URL,
error type). Without `return_exceptions=True`, the first exception would cancel all remaining tasks.

**DI module — `DialPromptSkillsModule`:** Decorated with `@preview_module` and registered in `AppFactory`
alongside the other feature modules. When `ENABLE_PREVIEW_FEATURES=false`, `AppFactory` filters out the module
entirely — no resolver is bound, and no DIAL prompt fetching occurs. Binds `DialPromptSkillResolver` at
`request_scope`.

### 4. Async transformer and prompt provider interfaces

**Owner:** `common/abstract/` package.

**What:** `PromptPartProvider.get_prompt_part()` and `MessagesTransformer.transform()` become async. This
eliminates the need for a separate pre-resolve step — the `SkillsRegistry` fetches DIAL prompts lazily inside
its `get_prompt_part()` call, at the natural point where skills are consumed.

**Why?** `PromptPartProvider.get_prompt_part()` and `MessagesTransformer.transform()` are currently synchronous.
A synchronous interface would force skill resolution into a separate pre-step outside the transformer pipeline
(e.g. in `_RequestContextSetup`), leaking domain-specific logic into a generic setup class. Making the
interfaces async lets `SkillsRegistry` fetch DIAL prompts inside its own `get_prompt_part()` — skill resolution
happens where skills are consumed (prompt assembly), not in a separate orchestration step.

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

**Call site:** `_RequestContextSetup.setup()` already calls `_MessagesSetup.setup()` — it just needs to
`await` it. No new dependencies on `_RequestContextSetup`.

**`PreInvocationTransformer` is not affected.** `base_transformer.py` defines both `MessagesTransformer` (runs
once at setup) and `PreInvocationTransformer` (runs before every LLM call in
`AssistantInvoker.__prepare_messages()`). Only `MessagesTransformer` becomes async. `PreInvocationTransformer`
remains synchronous — it has no async needs and runs in a different call path.

**`ConfigurationRequest` path:** `_MessagesSetup.setup()` is only called for `Request` (chat completion),
not for `ConfigurationRequest`. No change needed.

### 5. Skills registry — request-scoped skill merging

**Owner:** `skills/` package.

**What:** A request-scoped `SkillsRegistry` that merges predefined skills (from the singleton
`AgentSkillsProvider`) with external skills (from resolvers like `DialPromptSkillResolver`) into a unified
skill set for the current request. Implements `PromptPartProvider` — fetches and merges lazily on first
`get_prompt_part()` call.

**Why a new component?** `AgentSkillsProvider` is a singleton that loads skills eagerly at startup. External
skills (e.g. from DIAL prompts) are per-request (they depend on user credentials and may change between
requests). Merging these two sources requires a request-scoped component.

**Semantics:**

- Constructed per-request with injected `AgentSkillsProvider` (singleton), `DialPromptSkillResolver`
  (request-scoped, optional), `ProviderOf[ApplicationConfig]` (deferred access via `.get()` — required
  because `ApplicationConfig` is populated on `_RequestContext` after DI construction; same pattern as
  `ConfigBasedPromptProvider`, `_AttachmentNotificationInjector`, and `_TimestampInjectionTransformer`),
  and `ProviderOf[Stage]` (for surfacing warnings to the user).
- `async get_prompt_part() -> str` — on first call: reads `skills` config via `provider_of.get()`, fetches
  DIAL prompt skills via the resolver, merges with predefined, generates combined XML, caches everything.
  On subsequent calls: returns cached XML. The entire fetch-merge block is wrapped in `try/except` — if
  the fetch fails catastrophically (e.g. DIAL Core outage), falls back to predefined-only skills. A DIAL
  Core failure never prevents the request from being served. A failed fetch sets a "resolved" flag —
  subsequent calls (including `get_skill_content()`) use whatever was cached (predefined only) and do not
  re-attempt the DIAL prompt fetch within the same request.
- `async get_skill_content(name: str) -> str` — returns full content for a skill by name. Triggers
  lazy fetch if cache is not yet populated (same cache as `get_prompt_part()`). Making this async eliminates
  the implicit ordering invariant between prompt assembly and `read_skill` execution. If the lazy fetch fails,
  only predefined skills are cached — `get_skill_content()` for a DIAL prompt skill raises `FileNotFoundError`,
  preserving the existing error contract used by `_SkillReaderTool._run_in_stage_async()`. If the name is not
  in the merged set at all, `FileNotFoundError` is raised.
- The lazy fetch + cache pattern means no explicit `resolve()` call is needed anywhere.

**DI wiring when preview is disabled:** When `DialPromptSkillsModule` is filtered out (preview off),
`DialPromptSkillResolver` is not bound. `SkillsRegistry` handles this via optional injection
(`DialPromptSkillResolver | None = None`). When `None`, `get_prompt_part()` returns only predefined skills
XML — no DIAL prompt fetching occurs.

**Merge semantics:**
1. Start with all predefined skills (from `AgentSkillsProvider`). These are admin-configured and always take
   precedence.
2. Add DIAL prompt skills. If a DIAL prompt skill has the same `name` as a predefined skill, the DIAL prompt
   skill is **skipped** — predefined wins. The collision is added to the warnings list.
3. The registry generates combined XML from the merged metadata list. XML generation is owned exclusively
   by `SkillsRegistry` — no other component produces XML.

**User-facing warning stage.** After resolution, if any warnings were collected (from the resolver's return
value or from the registry's own merge-time collisions), the registry opens a stage via `ProviderOf[Stage]`
and renders all warnings as a markdown list — following the same pattern as `_InitializationErrorHandler`.
This ensures the user sees exactly which skills failed and why, rather than warnings being silently lost in
server logs. The stage is closed with `Status.COMPLETED` (the request proceeds with remaining skills).

No `logger.warning()` calls are made for DIAL prompt skill issues — all diagnostic output goes through the
stage. (Predefined skill issues at startup still use logging, since there is no request-scoped stage
available.)

**Concurrency:** Multiple DIAL prompt fetches within a single request are parallelized with `asyncio.gather()`
inside the resolver for better latency when multiple skills are configured.

**`AgentSkillsProvider` becomes a pure data store.** The singleton drops its `PromptPartProvider`
implementation entirely — no more `get_prompt_part()`, `get_skills_xml()`, `_generate_xml()`, or
`_escape_xml()`. It retains only:
- `get_all_skills() -> list[SkillMetadata]` — returns the cached list of predefined skill metadata.
- `get_all_skill_contents() -> dict[str, str]` — returns `{name: full_content}` for all predefined skills.
- `get_skill_content(name: str) -> str` — still needed by `_InjectFileTransferInstructionTransformer`.

Each skill source (`AgentSkillsProvider`, `DialPromptSkillResolver`) produces `list[SkillMetadata]` + content.
The registry is the single point that merges metadata, converts to XML, and exposes the result via
`PromptPartProvider`.

**`_InjectFileTransferInstructionTransformer` stays on `AgentSkillsProvider`.** This transformer only reads the
predefined `tool-call-file-parameter-formatting` skill — a built-in skill that is always available regardless
of user config. It does not need the registry and should not depend on it.

**Impact on `_SkillReaderTool`:** The tool's dependency changes from `AgentSkillsProvider` to `SkillsRegistry`.
When the agent calls `read_skill`, the registry looks up the skill by name in the merged (deduplicated) set.

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

Returns `list[SkillMetadata]` (name, description, and optional fields like license, compatibility). The
controller depends on `AgentSkillsProvider` (which holds parsed metadata), not `ConfigResolver`. This mirrors
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

**Response on success:** `SkillMetadata` (name, description, and optional fields).

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
    <metadata>
      <entry key="author">team-platform</entry>
      <entry key="version">1.0</entry>
    </metadata>
  </skill>
</available_skills>
```

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
  become async. All existing implementations must add `async` to their method signatures. Test files that call
  `_MessagesSetup.setup()` or mock these interfaces need corresponding `await` / `AsyncMock` updates. This is
  not a public API break but touches multiple files across packages.

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
| **`config/skill.py`** (new) | `DialPromptSkillConfig` (`type: "dial-prompt"`) model with `DialResourceConfigField`-annotated `url`, `SkillConfig` discriminated union |
| **`config/application.py`** | Add `skills: list[SkillConfig] \| None` field to `ApplicationConfig` |
| **`skills/_frontmatter.py`** (new) | Extracted `parse_frontmatter()` function (from `AgentSkillsProvider._parse_frontmatter`); raises `SkillValidationError` on invalid content |
| **`skills/_exceptions.py`** (new) | `SkillValidationError` exception class |
| **`skills/_xml.py`** (new) | `generate_skills_xml()` and `escape_xml()` — moved from `AgentSkillsProvider`, imported only by `SkillsRegistry` |
| **`skills/agent_skills_provider.py`** | Remove `PromptPartProvider` implementation and XML generation; delegate to `_frontmatter.parse_frontmatter()`; expose `get_all_skills()`, `get_all_skill_contents()`, `get_skill_content()` as pure data store |
| **`dial_prompt_skills/` package** (new) | New package for DIAL prompt skill source integration |
| **`dial_prompt_skills/_dial_prompt_skill_resolver.py`** (new) | Request-scoped resolver: fetches DIAL prompts via `AsyncDial`, validates as skills; returns structured `SkillResolutionWarning` list alongside resolved skills (no logging) |
| **`dial_prompt_skills/dial_prompt_skills_module.py`** (new) | `@preview_module` DI module: binds `DialPromptSkillResolver` at request-scope |
| **`common/abstract/base_prompt_provider.py`** | `get_prompt_part()` becomes `async` |
| **`common/abstract/base_transformer.py`** | `MessagesTransformer.transform()` becomes `async` |
| **`application/_messages_setup.py`** | `setup()` becomes `async`, awaits each transformer |
| **`agent/_messages_transformers.py`** | `_AddSystemPromptTransformer.transform()` becomes `async`, awaits `get_prompt_part()` |
| **All other `MessagesTransformer` impls** | Add `async` keyword, no body changes |
| **`skills/_skills_registry.py`** (new) | Request-scoped registry: merges predefined + external skills lazily in async `get_prompt_part()`, serves `read_skill` lookups; surfaces resolution warnings to user via `ProviderOf[Stage]` |
| **`skills/skills_module.py`** | Register `SkillsRegistry` (request-scope) as `PromptPartProvider`; remove `AgentSkillsProvider`'s `PromptPartProvider` multiprovider registration |
| **`skills/_skill_reader_tool.py`** | Change dependency from `AgentSkillsProvider` to `SkillsRegistry`; `await` the now-async `get_skill_content()` |
| **`configuration_support/_controller.py`** | Add `GET /v1/configuration-support/skills` (predefined listing) and `POST /v1/configuration-support/skills/validate` (validates any `SkillConfig` entry) endpoints; add `AgentSkillsProvider` and `DialSettings` as constructor dependencies |
| **Test files** | Update sync calls to `_MessagesSetup.setup()`, `transform()`, `get_prompt_part()` to `await`; update mocks to `AsyncMock` |
| **`app_factory.py`** | Register `DialPromptSkillsModule` in injector module list |
| **App schema** | Regenerated via `make dump_app_schema` to include `skills` field |
| **`docs/agent.md`** | Update skills section to cover DIAL prompt skills |
| **`docs/skills.md`** | Add "DIAL Prompt Skills" section with usage instructions |
| **`CLAUDE.md`** | Update architecture notes for skills |
