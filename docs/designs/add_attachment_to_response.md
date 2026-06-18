# Design: Add Attachment to Response Tool

- **Status:** Approved
- **Approved:** 2026-06-18
- **Dependencies:**
  - None

## Problem Statement

`StagedBaseTool` already auto-propagates certain attachment types (images and Plotly charts) to the choice via `propagate_to_choice`, based on a per-tool `propagate_types_to_choice` allowlist. However, there is no way for the agent to explicitly and on-demand promote an **arbitrary** URL — such as a CSV, PDF, or any file type not in the automatic allowlist — into the response's `attachments` array. The agent can write a CSV with `internal_file_write`, but that file will only appear in the stage, never in the final response the user sees.

The `ToolCallResult.propagate_to_choice` field and the orchestrator's wiring to `choice.add_attachment(...)` already exist. What is missing is an explicit, agent-callable tool that uses that path unconditionally for any URL and MIME type.

## Design Goals

- Give the agent a callable tool to explicitly promote any DIAL file URL to the response attachments array, regardless of MIME type.
- Gate the tool behind a per-app feature flag so operators control whether agents can use it.
- Follow the `SomeConfig | None = None` field shape used by other features (same as `dial_files`, but with a plain `Field` rather than `PreviewField` — this feature is not preview-gated).

---

## Use Cases

### UC-1: Agent promotes a written file to the response

**Trigger:** The agent writes a CSV report with `internal_file_write` (preview feature) and then calls `internal_attachments_add` with the returned DIAL URL.
**Behavior:** The orchestrator adds the attachment to the choice via `propagate_to_choice`. Note: `text/csv` is not in the automatic propagation allowlist, so without this tool the file would not appear in the response.
**Outcome:** The user sees the CSV as a downloadable attachment in the final response, not only in the stage.

### UC-2: Agent attaches a URL received from an external tool

**Trigger:** An MCP or REST tool returns a DIAL file URL. The agent calls `internal_attachments_add` with that URL.
**Behavior:** The URL is placed in `propagate_to_choice` and forwarded to the choice.
**Outcome:** The user sees the externally-produced file as a response attachment.

### UC-3: Agent promotes an admin-attached file

**Trigger:** An operator pre-attaches a file to the application configuration (e.g. a reference document). The agent receives its URL and calls `internal_attachments_add` to re-surface it in the reply.
**Behavior:** The attachment URL is placed in `propagate_to_choice` and forwarded to the choice.
**Outcome:** The user sees the admin-supplied file as a response attachment without the agent needing to re-upload or copy it.

### UC-4: Agent re-attaches a file from conversation history

**Trigger:** A previous turn's response contained an attachment (e.g. a chart generated earlier). The agent extracts the URL from the conversation history and calls `internal_attachments_add` to include it again in the current reply.
**Behavior:** The URL is promoted to `propagate_to_choice` exactly as in UC-1.
**Outcome:** The user receives the previously generated file as an attachment in the new response without the agent regenerating it.

---

## Proposed Design

### 1. Feature config

A new `AddAttachmentToolConfig` model is added to `src/quickapp/config/application.py`:

```python
class AddAttachmentToolConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Set to false to disable the internal_attachments_add tool.",
    )
```

`Features` gets a new field:

```python
add_attachment: AddAttachmentToolConfig | None = Field(
    default=None,
    description=(
        "Enables the internal_attachments_add tool. "
        "Omit or set to null to disable. "
        "Set to {} or {\"enabled\": true} to enable."
    ),
)
```

The tool is active when `features.add_attachment` is not `null` **and** `features.add_attachment.enabled` is `true`. The two-level gate is intentional: `null` means "not configured" (tool absent from schema), while `{"enabled": false}` means "configured but deliberately off" — useful when an operator wants to keep the config block while temporarily disabling the tool.

The feature is **not** preview-gated (`@preview_module` / `PreviewField` are not applied). UC-1 depends on `internal_file_write` which is a preview feature, but UC-2–4 work without preview, and the tool itself should be available in non-preview deployments.

### 2. Tool name constant

`INTERNAL_ATTACHMENTS_ADD_TOOL_NAME = "internal_attachments_add"` is added to
`src/quickapp/common/tool_names.py`.

### 3. Tool config (`InternalTool` definition)

A new file `src/quickapp/add_attachment_tooling/_tool_configs.py` defines the `InternalTool` config that exposes the tool to the LLM (all unlisted `ConfigurableSchemaSimpleType` fields default, yielding a valid OpenAI function schema):

```python
ADD_ATTACHMENT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ATTACHMENTS_ADD_TOOL_NAME,
            description=(
                "Add a file to the attachments of the current response. "
                "The file must already exist as a DIAL URL (e.g. files/bucket/path/file.csv). "
                "Use this to surface a file to the user in the final reply."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="DIAL file URL (e.g. files/bucket/path/report.csv).",
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
)
```

### 4. Tool implementation

A new file `src/quickapp/add_attachment_tooling/_add_attachment_tool.py` contains `_AddAttachmentTool`,
a `StagedBaseTool` subclass.

**Parameters (LLM-facing):**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | DIAL file URL (e.g. `files/bucket/path/report.csv`) |
| `title` | string | no | Display name shown to the user |
| `type` | string | no | MIME type. Default: `text/plain` (see Out of Scope for known limitation) |

**Runtime behaviour:**

1. Builds `Attachment(url=url, title=title, type=type or "text/plain")`.
2. Returns `ToolCallResult` with:
   - `content`: a short confirmation string (e.g. `"Attachment added to response: <title or url>"`)
   - `content_type`: `"text/plain"`
   - `propagate_to_choice`: `[attachment]`
   - `attachments`: left unset (`None`)
3. A minimal stage named "Add attachment" is rendered (consistent with `_CurrentTimestampTool`); no network I/O occurs.

`attachments` is intentionally left unset. `StagedBaseTool._run_in_stage_report_success` only post-processes `result.attachments` when it is non-empty — leaving it `None` causes the `propagate_types_to_choice` type-gate, `attachment.supported_types` filter, and media-type substitution to be skipped entirely. This is the desired behaviour: the tool promotes arbitrary types unconditionally. As a consequence, the attachment also receives no media-type substitution.

### 5. Dedicated module and app_factory registration

A new `AddAttachmentToolingModule` (following the `DialFilesToolingModule` / `TimestampModule` precedent) is added to `src/quickapp/add_attachment_tooling/add_attachment_tooling_module.py`:

```python
class AddAttachmentToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_AddAttachmentTool, to=_AddAttachmentTool, scope=request_scope)

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
                name=INTERNAL_ATTACHMENTS_ADD_TOOL_NAME,
                description=ADD_ATTACHMENT_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]
```

`AddAttachmentToolingModule` is registered in `src/quickapp/app_factory.py` alongside the other feature modules.

---

## Out of Scope

- **`data` field support** — passing raw base64 data through the LLM is impractical for files of any size. Deferred until there is a concrete use case.
- **`reference_url` / `reference_type`** — niche fields not needed for the primary use case.
- **Validating that the URL is accessible** — the tool does not verify the URL is reachable before adding it. Silently adding an unreachable URL results in a broken attachment in the response; a future `verify` flag could guard against this.
- **MIME type inference** — when `type` is omitted the attachment defaults to `text/plain` (see §4 parameter table), even for files whose extension implies another type (e.g. `.csv`, `.pdf`). The LLM is expected to supply the correct MIME type; automatic inference from the URL extension is deferred.

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
  "name": "internal_attachments_add",
  "arguments": {
    "url": "files/appdata/report.csv",
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

- New `add_attachment` field in `Features` — defaults to `null`, so existing apps are unaffected.
- New tool is only registered when `features.add_attachment` is set and `enabled` is `true`.

---

## Summary of Changes

| Component | Change |
|-----------|--------|
| `src/quickapp/common/tool_names.py` | Add `INTERNAL_ATTACHMENTS_ADD_TOOL_NAME` |
| `src/quickapp/config/application.py` | Add `AddAttachmentToolConfig` model; add `add_attachment` field to `Features` |
| `src/quickapp/add_attachment_tooling/_tool_configs.py` | New file — `ADD_ATTACHMENT_TOOL_CONFIG` (`InternalTool` definition with OpenAI function schema) |
| `src/quickapp/add_attachment_tooling/_add_attachment_tool.py` | New file — `_AddAttachmentTool` implementation |
| `src/quickapp/add_attachment_tooling/add_attachment_tooling_module.py` | New file — `AddAttachmentToolingModule` with feature-gated `@multiprovider` |
| `src/quickapp/app_factory.py` | Register `AddAttachmentToolingModule` |
| `make dump_app_schema` | Re-run after config changes to regenerate JSON schema |
