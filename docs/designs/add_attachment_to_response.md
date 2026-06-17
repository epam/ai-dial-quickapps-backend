# Design: Add Attachment to Response Tool

- **Status:** Draft
- **Dependencies:**
  - None

## Problem Statement

When a QuickApp agent creates a file using the built-in file tools (e.g. `internal_file_write`), the file appears only in the stage area of the response — it is never added to the response's `attachments` array. There is no way for the agent to explicitly promote a file (or any DIAL-resident URL) into the final message attachments visible to the user.

The `ToolCallResult` model already carries a `propagate_to_choice` field and the orchestrator already wires it to `choice.add_attachment(...)`, but no tool currently populates that field.

## Design Goals

- Give the agent a callable tool to add any DIAL file URL to the response attachments array.
- Gate the tool behind a per-app feature flag so operators control whether agents can use it.
- Follow the existing `Features` config pattern (`AddAttachmentToolConfig | None = None` where `None` = disabled).
- Require no changes to the orchestrator or `ToolCallResult` — the plumbing already exists.

---

## Use Cases

### UC-1: Agent promotes a written file to the response

**Trigger:** The agent writes a CSV report with `internal_file_write` and then calls `internal_add_attachment` with the returned DIAL URL.
**Behavior:** The orchestrator adds the attachment to the choice via `propagate_to_choice`.
**Outcome:** The user sees the file as a downloadable attachment in the final response message, not only in the stage.

### UC-2: Agent attaches a URL received from an external tool

**Trigger:** An MCP or REST tool returns a DIAL file URL. The agent calls `internal_add_attachment` with that URL.
**Behavior:** Same as UC-1 — URL is promoted to `propagate_to_choice`.
**Outcome:** The user sees the externally-produced file as a response attachment.

### UC-3: Agent promotes an admin-attached file

**Trigger:** An operator pre-attaches a file to the application configuration (e.g. a reference document). The agent receives its URL and calls `internal_add_attachment` to re-surface it in the reply.
**Behavior:** The attachment URL is placed in `propagate_to_choice` and forwarded to the choice.
**Outcome:** The user sees the admin-supplied file as a response attachment without the agent needing to re-upload or copy it.

### UC-4: Agent re-attaches a file from conversation history

**Trigger:** A previous turn's response contained an attachment (e.g. a chart generated earlier). The agent extracts the URL from the conversation history and calls `internal_add_attachment` to include it again in the current reply.
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
        description="Set to false to disable the internal_add_attachment tool.",
    )
```

`Features` gets a new field:

```python
add_attachment: AddAttachmentToolConfig | None = Field(
    default=None,
    description=(
        "Enables the internal_add_attachment tool. "
        "Set to null or omit to disable. "
        "Set to {} or {\"enabled\": true} to enable."
    ),
)
```

The tool is active when `features.add_attachment` is not `null` **and** `features.add_attachment.enabled` is `true`.
Setting `features.add_attachment: {}` is the standard way to enable with defaults.

### 2. Tool name constant

`INTERNAL_ADD_ATTACHMENT_TOOL_NAME = "internal_add_attachment"` is added to
`src/quickapp/common/tool_names.py`.

### 3. Tool implementation

A new file `src/quickapp/internal_tooling/_add_attachment_tool.py` contains `_AddAttachmentTool`,
a `StagedBaseTool` subclass.

**Parameters (LLM-facing):**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | DIAL file URL (e.g. `files/bucket/path/report.csv`) |
| `title` | string | no | Display name shown to the user |
| `type` | string | no | MIME type. Default: `text/plain` |

**Runtime behaviour:**

1. Builds `Attachment(url=url, title=title, type=type)`.
2. Returns `ToolCallResult` with:
   - `content`: a short confirmation string (e.g. `"Attachment added to response: <title or url>"`)
   - `content_type`: `"text/plain"`
   - `propagate_to_choice`: `[attachment]`
3. No network I/O, no stage output — the tool is instantaneous.

### 4. Module wiring

A new `@multiprovider` method in `InternalToolModule`
(`src/quickapp/internal_tooling/internal_tooling_module.py`) checks
`app_config.features.add_attachment`. If the config is present and `enabled` is `true`,
it binds and returns `_AddAttachmentTool`.

No new DI module is introduced. `_AddAttachmentTool` is registered at `request_scope`.

---

## Out of Scope

- **`data` field support** — passing raw base64 data through the LLM is impractical for files of any size. Deferred until there is a concrete use case.
- **`reference_url` / `reference_type`** — niche fields not needed for the primary use case.
- **Validating that the URL is accessible** — the tool does not verify the URL is reachable before adding it. A future pass could add an optional `verify` flag.

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
  "name": "internal_add_attachment",
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
| `src/quickapp/common/tool_names.py` | Add `INTERNAL_ADD_ATTACHMENT_TOOL_NAME` |
| `src/quickapp/config/application.py` | Add `AddAttachmentToolConfig` model; add `add_attachment` field to `Features` |
| `src/quickapp/internal_tooling/_add_attachment_tool.py` | New file — `_AddAttachmentTool` implementation |
| `src/quickapp/internal_tooling/internal_tooling_module.py` | New `@multiprovider` to register the tool when feature is enabled |
| `make dump_app_schema` | Re-run after config changes to regenerate JSON schema |
