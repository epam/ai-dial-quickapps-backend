# Design: Add Attachment to Response Tool

- **Status:** Approved
- **Approved:** 2026-06-19
- **Dependencies:**
  - None

## Problem Statement

`StagedBaseTool` already auto-propagates certain attachment types (images and Plotly charts) to the choice via `propagate_to_choice`, based on a per-tool `propagate_types_to_choice` allowlist. However, there is no way for the agent to explicitly and on-demand promote an **arbitrary** URL — such as a CSV, PDF, or any file type not in the automatic allowlist — into the response's `attachments` array. The agent can write a CSV with `internal_file_write`, but that file will only appear in the stage, never in the final response the user sees.

The `ToolCallResult.propagate_to_choice` field and the orchestrator's wiring to `choice.add_attachment(...)` already exist. What is missing is an explicit, agent-callable tool that uses that path unconditionally for any URL and MIME type.

## Design Goals

- Give the agent a callable tool to explicitly promote any URL (DIAL or external) to the response attachments array, regardless of MIME type.
- Gate the tool behind a per-app feature flag so operators control whether agents can use it.
- Follow the `PreviewField` + `SomeConfig | None = None` shape used by `dial_files` — this is a preview feature.

---

## Use Cases

### UC-1: Agent promotes a written file to the response

**Trigger:** The agent writes a CSV report with `internal_file_write` (preview feature) and then calls `internal_add_attachment` with the returned DIAL URL.
**Behavior:** The orchestrator adds the attachment to the choice via `propagate_to_choice`. Note: `text/csv` is not in the automatic propagation allowlist, so without this tool the file would not appear in the response.
**Outcome:** The user sees the CSV as a downloadable attachment in the final response, not only in the stage.

### UC-2: Agent attaches a URL received from an external tool

**Trigger:** An MCP or REST tool returns a DIAL or external file URL. The agent calls `internal_add_attachment` with that URL.
**Behavior:** The URL is placed in `propagate_to_choice` and forwarded to the choice.
**Outcome:** The user sees the file as a response attachment.

### UC-3: Agent promotes an admin-attached file on user request

**Trigger:** The user asks about a file the operator pre-attached to the application (e.g. "show me the reference document"). The agent locates the file URL via `internal_attachments_available_context` and calls `internal_add_attachment` to surface it in the reply.
**Behavior:** The attachment URL is placed in `propagate_to_choice` and forwarded to the choice.
**Outcome:** The user receives the admin-supplied file as a response attachment without the agent re-uploading or copying it.

### UC-4: Agent re-attaches a file from conversation history on user request

**Trigger:** The user asks about a file that appeared in a previous response (e.g. "can you send me that chart again?"). The agent finds the URL in conversation history (available in its context window) and calls `internal_add_attachment` to include it in the current reply.
**Behavior:** The URL is promoted to `propagate_to_choice` exactly as in UC-1.
**Outcome:** The user receives the previously generated file as an attachment in the new response without the agent regenerating it.

### UC-5: Agent attaches a URL that was already propagated to the current response

**Trigger:** A URL was already added to the response's attachments — either by the automatic `propagate_types_to_choice` path (e.g. an image written by `internal_file_write`) or by an earlier `internal_add_attachment` call in the same turn. The agent calls `internal_add_attachment` again for the same URL.
**Behavior:** `choice.add_attachment()` has no deduplication — it streams each attachment as a new chunk with an incrementing index. The URL is added a second time.
**Outcome:** The attachment appears **twice** in the response. Agents must avoid calling `internal_add_attachment` for URLs they know are already propagated in the current turn.

---


## Proposed Design

### 1. Feature config

A new `AddAttachmentToolConfig` model is added to `src/quickapp/config/application.py`:

```python
class AddAttachmentToolConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Set to false to disable the internal_add_attachment tool.",
    )
```

`Features` gets a new field declared with `PreviewField` (same as `dial_files`):

```python
add_attachment: AddAttachmentToolConfig | None = PreviewField(  # type: ignore[assignment]
    default=None,
    description=(
        "Enables the internal_add_attachment tool. "
        "Omit or set to null to disable. "
        "Set to {} or {\"enabled\": true} to enable."
    ),
)
```

The tool is active when `ENABLE_PREVIEW_FEATURES=true`, `features.add_attachment` is not `null`, **and** `features.add_attachment.enabled` is `true`. The `enabled` flag supplements the presence gate: `null` means "not configured at all", while `{"enabled": false}` means "configured block present but deliberately off" — useful for operators who want to temporarily disable the tool without losing their config.

### 2. Tool name constant

`INTERNAL_ADD_ATTACHMENT_TOOL_NAME = "internal_add_attachment"` is added to
`src/quickapp/common/tool_names.py`. The name is flat (`internal_<action>`) rather than
prefixed with an existing family, because the implementation lives in `internal_tooling/`
alongside `internal_code_execution_*` — not in `attachment_processing/` where the
`internal_attachments_*` family resides.

### 3. Tool config (`InternalTool` definition)

A new file `src/quickapp/internal_tooling/_add_attachment_tool_config.py` defines the
`InternalTool` config (all unlisted `ConfigurableSchemaSimpleType` fields default, yielding
a valid OpenAI function schema).

Two config choices are load-bearing:
- `propagate_types_to_choice=[]` — disables automatic type-based propagation from `attachments`, eliminating any duplication risk when both `attachments` and `propagate_to_choice` are set (see §4).
- `supported_types` is left at its default `[ALL_MIME_TYPES]` — so the stage renders the attachment for any MIME type the agent supplies.

```python
ADD_ATTACHMENT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ADD_ATTACHMENT_TOOL_NAME,
            description=(
                "Add a file to the attachments of the current response. "
                "The file must be accessible via a URL (DIAL URL or external link). "
                "Use this to surface a file to the user in the final reply."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="File URL — DIAL (e.g. files/bucket/path/report.csv) or external.",
                    ),
                    "title": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="Display name shown to the user. Optional.",
                    ),
                    "type": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="MIME type (e.g. text/csv, application/pdf). Default: text/plain.",
                    ),
                },
                required=["url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Add attachment")),
    propagate_types_to_choice=[],
)
```

### 4. Tool implementation

A new file `src/quickapp/internal_tooling/_add_attachment_tool.py` contains `_AddAttachmentTool`,
a `StagedBaseTool` subclass.

**Parameters (LLM-facing):**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | File URL — DIAL or external |
| `title` | string | no | Display name shown to the user |
| `type` | string | no | MIME type. Default: `text/plain` (see Out of Scope for known limitation) |

**Runtime behaviour:**

1. Builds `Attachment(url=url, title=title, type=type or "text/plain")`.
2. Returns `ToolCallResult` with:
   - `content`: a short confirmation string (e.g. `"Attachment added to response: <title or url>"`)
   - `content_type`: `"text/plain"`
   - `attachments`: `[attachment]` — shown in the stage
   - `propagate_to_choice`: `[attachment]` — forwarded to the final response
3. A minimal stage named "Add attachment" is rendered; no network I/O occurs.

`attachments` and `propagate_to_choice` are both set deliberately. Because `propagate_types_to_choice=[]`, `StagedBaseTool._run_in_stage_report_success` will not auto-append anything from `attachments` to `propagate_to_choice`, eliminating any duplication risk for any MIME type. The attachment is shown in the stage via `attachments` and promoted to the response via `propagate_to_choice`.

### 5. Module wiring

A new `@multiprovider` method and a `configure()` binding are added to the existing
`InternalToolModule` (`src/quickapp/internal_tooling/internal_tooling_module.py`).

`configure()` adds:
```python
binder.bind(_AddAttachmentTool, to=_AddAttachmentTool, scope=request_scope)
```

The new provider:
```python
@multiprovider
def _provide_add_attachment_tool(
    self,
    app_config: ApplicationConfig,
    builder: AssistedBuilder[_AddAttachmentTool],
) -> list[StagedBaseTool]:
    cfg = app_config.features.add_attachment if app_config.features else None
    if cfg is None or not cfg.enabled:
        return []
    return [
        builder.build(
            tool_config=ADD_ATTACHMENT_TOOL_CONFIG,
            name=INTERNAL_ADD_ATTACHMENT_TOOL_NAME,
            description=ADD_ATTACHMENT_TOOL_CONFIG.open_ai_tool.function.description,
        )
    ]
```

This provider is independent of `_provide_internal_tools` (which is tool_sets-driven) — both contribute to the same `list[StagedBaseTool]` multibinding.

---

## Out of Scope

- **`data` field support** — passing raw base64 data through the LLM is impractical for files of any size. Deferred until there is a concrete use case.
- **`reference_url` / `reference_type`** — niche fields not needed for the primary use case.
- **Validating that the URL is accessible** — the tool does not verify the URL is reachable before adding it. Silently adding an unreachable URL results in a broken attachment in the response; a future `verify` flag could guard against this.
- **MIME type inference** — when `type` is omitted the attachment defaults to `text/plain` (see §4 parameter table), even for files whose extension implies another type (e.g. `.csv`, `.pdf`). The LLM is expected to supply the correct MIME type; automatic inference from the URL extension is deferred.
- **External URL access control** — the tool accepts any URL including external links; it makes no network request itself (unlike `ExternalUrlFetcher`), so `EXTERNAL_URL_FETCH_ENABLED` does not apply. Whether the DIAL client can render or download an external URL is outside the backend's responsibility.

---

## Configuration / Usage Examples

### Enabling the feature

```json
{
  "features": {
    "add_attachment": {}
  }
}
```

Requires `ENABLE_PREVIEW_FEATURES=true` on the deployment.

### Explicitly disabling while keeping config

```json
{
  "features": {
    "add_attachment": { "enabled": false }
  }
}
```

### Agent tool call

```json
{
  "name": "internal_add_attachment",
  "arguments": {
    "url": "files/bucket/path/report.csv",
    "title": "Monthly Report",
    "type": "text/csv"
  }
}
```

### Tool result

```json
{
  "content": "Attachment added to response: Monthly Report"
}
```

The file appears in the response `attachments` array alongside the assistant message.

---

## Migration

### Breaking changes

None.

### Non-breaking changes

- New preview-gated `add_attachment` field in `Features` — existing apps are unaffected.

---

## Summary of Changes

| Component | Change |
|-----------|--------|
| `src/quickapp/common/tool_names.py` | Add `INTERNAL_ADD_ATTACHMENT_TOOL_NAME` |
| `src/quickapp/config/application.py` | Add `AddAttachmentToolConfig` model; add `add_attachment` `PreviewField` to `Features` |
| `src/quickapp/internal_tooling/_add_attachment_tool_config.py` | New file — `ADD_ATTACHMENT_TOOL_CONFIG` (`InternalTool` definition with OpenAI function schema) |
| `src/quickapp/internal_tooling/_add_attachment_tool.py` | New file — `_AddAttachmentTool` implementation |
| `src/quickapp/internal_tooling/internal_tooling_module.py` | Add `configure()` binding + `@multiprovider _provide_add_attachment_tool` |
| `make dump_app_schema` | Re-run after config changes to regenerate JSON schema |
