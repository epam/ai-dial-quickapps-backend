# Design: Attachment Configuration Redesign

**Status:** Implemented

## Problem Statement

The `supported_types` field on `AttachmentConfig` is overloaded — it simultaneously drives three unrelated decisions:

1. Which tool-output attachments to keep (base class filter)
2. Whether a REST API HTTP response body should be converted into an attachment (creation gate)
3. Whether an MCP attachment should be uploaded to DIAL Core (upload gate)

This causes silent response duplication in REST API tools (default `*/*` wraps every JSON response as an attachment),
redundant double-filtering in tool subclasses, and a semantic mismatch where deployment `input_attachment_types` are
mapped to output filtering.

## Design Goals

- Each attachment-related behavior is controlled by **exactly one** config field with a clear name.
- Tool subclasses do **not** duplicate base-class filtering logic.
- REST API tools support three distinct response modes out of the box.
- Deployment tools correctly separate input-type declarations from output-type filtering.

---

## Proposed Design

The design decomposes the current overloaded `supported_types` into three orthogonal concerns, each controlled by
exactly one config field.

### Concern 1: Output attachment filtering ("what to keep")

**Field:** `AttachmentConfig.supported_types` (existing, name kept as-is — once the overloaded semantics are removed, the
name is clear enough and avoiding a rename eliminates migration cost for all existing configs)

**Owner:** `StagedBaseTool._run_in_stage_report_success()` — the **single, canonical** filter point.

**Semantics:** After a tool produces its `CompletionResult`, the base class filters `result.attachments` to keep only
types matching this list. This is the only place this check runs.

**Change:** Remove the `supported_types` check from `_RestApiTool` (it will no longer create attachments itself — that's
Concern 3's job). For `_MCPTool`, replace `_maybe_upload_attachment` with a `_should_upload(type)` helper that gates
**both** the upload and the append. Currently, `_MCPTool` unconditionally appends every attachment to the result list
even when the upload is skipped — these unuploaded objects linger in memory until the base-class filter discards them.
The new helper should short-circuit: if the type won't survive `supported_types` filtering, skip both upload and append.
This is framed as a **performance optimization** — the base class remains the single owner of the actual filtering
decision.

### Concern 2: Choice propagation ("what to show in UI")

**Field:** `AttachmentConfig.propagate_types_to_choice` (existing, unchanged)

**Owner:** `StagedBaseTool._run_in_stage_report_success()` — same loop as concern 1.

**Semantics:** Attachments matching this list are forwarded to the response `Choice` for UI rendering (e.g., inline
images, Plotly charts).

**Change (bug fix):** The current code in `StagedBaseTool._run_in_stage_report_success` runs the `supported_types` and
`propagate_types_to_choice` checks as two independent `if` statements in the same loop. An attachment that fails
`supported_types` but matches `propagate_types_to_choice` is still added to `propagate_to_choice` — it leaks to the UI
choice despite being filtered from `result.attachments`. This is an existing bug.

Fix: restructure the loop so that `propagate_types_to_choice` is checked **only on surviving attachments** (i.e., those
that already passed the `supported_types` filter). This enforces propagation as a logical subset of filtering via runtime
code ordering. No config-time validation is needed (MIME wildcard subset checking is non-trivial and not worth the
complexity).

### Concern 3: Response-to-attachment conversion ("whether to create an attachment from the response")

This is **REST-API-specific**. Other tool types (MCP, deployment, internal) produce attachments through their own
natural mechanisms — they don't need a "should I wrap my text response as a file?" decision.

**New field:** `RestApiTool.response_as_attachment` — a new field on `RestApiTool`, alongside the inherited `attachment`
config from `BaseTool`. Defined per-tool. `RestApiToolSet` gets an optional `response_as_attachment` field that serves as
the default for all tools in the set; individual tools can override it. Override semantics are **full replacement**: if a
tool defines `response_as_attachment`, the entire toolset default is ignored for that tool (no field-level merging).

Note: `RestApiToolSet` currently has no toolset-level attachment defaults — this is new plumbing. `MCPToolSet` already has
a similar pattern (toolset-level `attachment: AttachmentConfig` propagated in `_MCPToolInitializer`). The REST API
propagation should follow the same approach: resolve the toolset default during tool initialization and copy it to each
tool that doesn't define its own override.

**Type:** config model with:

- **`enabled`** (`bool`, default `False`) — whether to wrap the HTTP response body as an attachment at all.
- **`content_types`** (`list[str]`, default `["*/*"]`) — which response Content-Types to convert. Uses the same MIME
  matching logic. Only relevant when `enabled=True`.
- **`include_body_as_content`** (`bool`, default `True`) — when an attachment is created, whether to also keep the
  response body as `CompletionResult.content`. When `false`, content is set to a placeholder
  (e.g., `"See attached file: {filename}"`) rather than left empty, since some LLM providers reject empty tool messages.

This cleanly supports three REST API response modes:

| Mode                      | `enabled` | `include_body_as_content` | Result                                           |
|---------------------------|-----------|---------------------------|--------------------------------------------------|
| 1. Text only              | `false`   | n/a                       | Response as text, no attachment                  |
| 2. Attachment only        | `true`    | `false`                   | Response as attachment, placeholder text content |
| 3. Both text + attachment | `true`    | `true`                    | Response in both forms                           |

Additional patterns (like "propagation only") emerge from combining `response_as_attachment` with `propagate_types_to_choice` — these are documented in the Configuration / Usage Examples section below.

**Default behavior change:** `enabled=False` means REST API tools no longer silently duplicate responses as attachments.
This is a breaking change for configs that rely on the current implicit behavior — a migration note is needed.

---

## Secondary Fixes

### Deployment tool `input_attachment_types` mapping

Currently `deployment.input_attachment_types` (what the deployment accepts as input) is mapped to `supported_types` (
what the tool outputs). This is a semantic mismatch — and also a **bug**: when a deployment has no
`input_attachment_types`, `ToolConfigCoreService` sets `supported_types=deployment.input_attachment_types or []`, which
evaluates to `[]`. Since `matches_type(mime_type, [])` returns `False` for all types, this silently blocks **all** output
attachments from deployments that don't declare input types.

**Fix:** When building a `DialDeploymentTool` from DIAL Core metadata:

- Use `deployment.input_attachment_types` only for its actual purpose — controlling which attachments are forwarded *to*
  the deployment (the `attachment_urls` parameter).
- Default `supported_types` to `["*/*"]` (the `AttachmentConfig` default) for deployment tools, since we generally don't
  know what a deployment will *return*. If DIAL Core metadata eventually exposes output types, map those instead.
- Keep `propagate_types_to_choice` as `[]` for deployment tools. Unlike predefined tools (py_interpreter, etc.) where we
  control the output, deployment tools return arbitrary content from external services. Automatically propagating unknown
  attachments to the UI choice could produce unexpected rendering behavior (e.g., malformed Plotly JSON breaking the UI).
  Config authors can opt in per-tool when appropriate.

### `supported_types: None` handling

Make `supported_types` non-optional: `list[str]` with default `["*/*"]`. If `None` is provided in config, the Pydantic
validator coerces it to the default. Eliminates the silent "block everything" trap.

---

## Out of Scope

### Pre-LLM user attachment filter (`_AttachmentFilter`)

The investigation flags `_AttachmentFilter.SUPPORTED_ATTACHMENTS = ["image/*"]` as high severity — the pre-LLM filter is
hardcoded and disconnected from tool configs. This means configuring a tool with `supported_types: ["application/pdf"]`
doesn't help if the LLM never sees user-submitted PDFs in the first place.

This is intentionally deferred. Making it configurable requires broader design work around token budget concerns (large
PDFs shouldn't always be sent to the LLM), LLM capability detection, and file size limits. It deserves its own design
pass.

### REST API binary response handling

The current `_RestApiTool` uses `response.text` to create attachments, which fails or produces garbage for binary
responses (images, PDFs). This is a pre-existing bug, not introduced by this redesign. Since we're changing the
attachment creation path, it's a natural time to fix it — but the fix (detecting binary Content-Types, using
`response.content` with base64 encoding) is mechanical and orthogonal to the config model changes here.

---

## Configuration / Usage Examples

Common patterns that emerge from combining the orthogonal config fields:

**REST API tool returning JSON data (text only — the new default, no config needed):**
- `response_as_attachment` is omitted (defaults to `enabled = false`)
- Result: HTTP response body is returned as `CompletionResult.content` text. No attachment is created. This is the most
  common case for REST API tools that return structured data for the LLM to process.

**REST API tool returning custom Plotly visualization (propagation only):**
- `response_as_attachment.enabled = true`
- `response_as_attachment.content_types = ["application/vnd.plotly.v1+json"]`
- `response_as_attachment.include_body_as_content = false`
- `propagate_types_to_choice = ["application/vnd.plotly.v1+json"]`
- Result: Plotly JSON is wrapped as attachment, propagated to UI choice for rendering, placeholder text sent to LLM.

**REST API tool returning images inline:**
- `response_as_attachment.enabled = true`
- `response_as_attachment.content_types = ["image/*"]`
- `response_as_attachment.include_body_as_content = false`
- `supported_types = ["image/*"]`
- `propagate_types_to_choice = ["image/*"]`
- Result: Image responses become attachments shown in UI. Non-image responses pass through as text only.

---

## Migration

### Breaking changes

**REST API response-to-attachment default.** The new default `response_as_attachment.enabled = false` means REST API
tools no longer silently create attachments from every HTTP response. Configs that relied on this behavior need to
explicitly opt in.

**Backward compatibility strategy:** Log a warning **once at startup** (config load time) for REST API tools where
`response_as_attachment` is absent from the config input. Detection uses Pydantic's `model_fields_set`: if
`"response_as_attachment"` is not in the set, the field was never provided and the warning fires. If a user explicitly
writes `response_as_attachment: {enabled: false}`, they made a deliberate choice and should **not** see the warning. The
message should be: "REST API tool X uses the default `response_as_attachment.enabled=false`. If you relied on automatic
attachment creation, set `enabled=true` explicitly." Per-response warnings would fire on every single API call (since
the old `*/*` default matched everything) and produce pure noise.

### Non-breaking changes

**Deployment tools.** Deployment tool defaults are preserved (`propagate_types_to_choice = []`). The only change is that
`supported_types` defaults to `["*/*"]` instead of being derived from `input_attachment_types`, which means deployment
output attachments are no longer silently filtered when the deployment doesn't declare input types.

**Field naming.** `supported_types` field name is kept as-is. No config migration needed for existing users of this
field.

---

## Summary of Changes

**`AttachmentConfig`** (all tool types):

- `supported_types: list[str] = ["*/*"]` — output attachment filter (non-optional)
- `propagate_types_to_choice: list[str] = [...]` — UI choice propagation (unchanged)

**`RestApiTool`** (REST API only, new):

- `response_as_attachment.enabled: bool = False`
- `response_as_attachment.content_types: list[str] = ["*/*"]`
- `response_as_attachment.include_body_as_content: bool = True`

**`ToolConfigCoreService`** (deployment tools):

- Stop mapping `input_attachment_types` → `supported_types`; default to `["*/*"]`
- Keep `propagate_types_to_choice = []` (intentional for deployment tools)
- Use `input_attachment_types` only for controlling which attachments are forwarded to the deployment

