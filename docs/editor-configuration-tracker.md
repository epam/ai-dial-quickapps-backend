# Quick Apps 2.0 — Editor Configuration Tracker

Every field of the Quick Apps 2.0 application config, and whether the **editor** (the no-code
app-builder UI in ai-dial-chat) lets you set it.

Source of truth: [`generated-app-schema.json`](./generated-app-schema.json) — regenerate with
`make dump_app_schema`. Editor state observed 2026-09-18 on
`/apps-editor?step=settings&schema=…/quickapps2`. Issues land in **epam/ai-dial-chat**; use the
`quickapps-editor-issue` skill to write them.

## Legend

| Status | Meaning |
|---|---|
| ✅ | **Done** — dedicated control in the editor |
| 🟡 | **Partial** — a control exists but does not cover the field's range |
| 📝 | **JSON only** — editable through the raw **JSON** toggle next to *Agents & Toolsets*, no form control |
| ❌ | **Missing** — no way to set it in the editor |
| ➖ | **N/A** — not editor-facing: type discriminators, deprecated aliases, runtime-populated fields, or handled outside the manifest |

| Column | Values |
|---|---|
| **Tier** | `Basic` — belongs in the main form, ordinary app authors need it. `Advanced` — belongs behind *Advanced settings* or a per-toolset advanced panel. |
| **Pri** | `High` — blocks real use today. `Medium` — clear value, worth scheduling. `Low` — backlog; the JSON editor or a backend default is fine for now. |

Most toolset and tool internals are `Low` by default: they belong to the published **Toolset
resource**, so this editor only needs to reference them, not re-edit them. The exceptions are the
toolset-level fields the *app* owns — `description`, `enabled`, `deferred`.

*(preview)* marks preview-tier backend fields — gate any editor control behind the preview flag.

## Coverage

Counted in tracked rows; a few rows cover a group of sibling fields (noted in the row).

| Section | ✅ | 🟡 | 📝 | ❌ | ➖ | Total |
|---|---:|---:|---:|---:|---:|---:|
| `orchestrator` | 4 | 0 | 0 | 18 | 2 | 24 |
| `contexts` | 1 | 0 | 0 | 5 | 2 | 8 |
| `tool_sets` | 3 | 1 | 38 | 0 | 6 | 48 |
| `conversation_starters` | 4 | 0 | 0 | 0 | 0 | 4 |
| `starters` | 0 | 0 | 0 | 0 | 1 | 1 |
| `skills` | 1 | 0 | 0 | 1 | 1 | 3 |
| `hooks` | 0 | 0 | 0 | 7 | 1 | 8 |
| `features` | 1 | 1 | 0 | 13 | 1 | 16 |
| `tool_defaults` | 0 | 0 | 0 | 1 | 0 | 1 |
| **Total** | **14** | **2** | **38** | **45** | **14** | **113** |

### Open work by priority

Rows still needing editor work (❌ + 📝 + 🟡), by priority.

| Section | High | Medium | Low |
|---|---:|---:|---:|
| `orchestrator` | 2 | 4 | 12 |
| `contexts` | 1 | 3 | 1 |
| `tool_sets` | 2 | 1 | 36 |
| `skills` | 1 | 0 | 0 |
| `hooks` | 0 | 0 | 7 |
| `features` | 2 | 6 | 5 |
| `tool_defaults` | 0 | 1 | 0 |
| **Total** | **8** | **15** | **61** |

**High-priority shortlist:** folder contexts · toolset `description` · toolset `deferred` +
`tool_discovery.enabled`/`service_model` (one feature) · `dial-skill` resources ·
`features.web_fetch.enabled` · `features.representation_tooling.add_attachment`.

---

## orchestrator

[`config/application.py`](../src/quickapp/config/application.py) ·
[`config/dial_deployment.py`](../src/quickapp/config/dial_deployment.py) ·
[`config/prompt.py`](../src/quickapp/config/prompt.py) ·
[`config/tool_discovery.py`](../src/quickapp/config/tool_discovery.py)

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `deployment.deployment_id` | The LLM that drives the agent. | ✅ *Model* | — | — |
| `deployment.name` | Deprecated alias for `deployment_id`. | ➖ | — | — |
| `deployment.parameters.temperature` | Sampling temperature. | ✅ *Temperature* | — | — |
| `deployment.parameters.reasoning_effort` | How much the model reasons before answering (`none`…`high`); supported values vary per deployment. | ❌ | Basic | Medium |
| `deployment.parameters.max_tokens` | Cap on generated tokens. | ❌ | Advanced | Medium |
| `deployment.parameters.top_p` | Nucleus sampling cutoff. | ❌ | Advanced | Low |
| `deployment.parameters.seed` | Fixed seed for reproducible responses. | ❌ | Advanced | Low |
| `deployment.parameters.stop` | Up to 4 stop sequences. | ❌ | Advanced | Low |
| `deployment.parameters.n` | Number of completion choices. | ❌ | Advanced | Low |
| `deployment.parameters.presence_penalty` | Penalty on tokens already present. | ❌ | Advanced | Low |
| `deployment.parameters.frequency_penalty` | Penalty scaled by token frequency. | ❌ | Advanced | Low |
| `deployment.parameters.custom_fields.configuration` | Deployment-specific params, schema served by that deployment's configuration endpoint. | ❌ | Advanced | Low |
| `system_prompt` *(custom)* `.content` | Inline system prompt. | ✅ *Instructions* | — | — |
| `system_prompt` *(custom)* `.variables` | Preset values substituted into the inline prompt. | ❌ | Advanced | Low |
| `system_prompt` *(dial)* `.path` | Use a prompt stored in DIAL instead of inline text — shared and versioned across apps. | ❌ | Advanced | Low |
| `system_prompt` *(dial)* `.variables` | Values substituted into the DIAL prompt template. | ❌ | Advanced | Low |
| `system_prompt` *(predefined)* `.template` | Use a server-shipped prompt template by name. | ❌ | Advanced | Low |
| `system_prompt.type` / `.content` (loaded) | Discriminator; resolved prompt cached at runtime. | ➖ | — | — |
| `max_iterations` | Cap on orchestrator loop turns. No field at all — silently 15, so long runs stop mid-task. | ❌ | Advanced | Medium |
| `propagate_stages` | Whether the orchestrator's own reasoning stages are shown to the user. | ❌ | Advanced | Medium |
| `attachment_strategy` | How the orchestrator receives request attachments (lazy on-demand vs none). | ✅ *Process files* | — | — |
| `tool_discovery.enabled` *(preview)* | Withhold deferred toolsets from the initial payload; surface them on demand via `tool_search`. Prerequisite for toolset `deferred`. [design](./designs/dynamic_tool_discovery.md) | ❌ | Advanced | **High** |
| `tool_discovery.service_model` *(preview)* | Deployment used for the routing call inside `tool_search`; falls back to the orchestrator's own model. [design](./designs/dynamic_tool_discovery.md) | ❌ | Advanced | **High** |
| `tool_discovery.min_tools_for_deferral` *(preview)* | Toolsets smaller than this stay eager (default 10). [design](./designs/dynamic_tool_discovery.md) | ❌ | Advanced | Low |

## contexts

[`config/context.py`](../src/quickapp/config/context.py)

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| *(file)* `.url` | Attach a DIAL file as admin context. | ✅ *Context files* | — | — |
| *(file)* `.description` | Hint the agent sees next to the file in the available-context listing — the only signal besides filename and MIME for deciding what to load. Matters most under *Process files*. | ❌ | Basic | Medium |
| *(folder)* `.url` *(preview)* | Attach a whole DIAL folder; files and subfolders are expanded into the listing. Today only individual files can be picked. [design](./designs/folder_context.md) | ❌ | Basic | **High** |
| *(folder)* `.description` *(preview)* | Description on the folder entry itself. | ❌ | Basic | Medium |
| *(folder)* `.max_depth` *(preview)* | Recursion depth when expanding the folder (1–10, default 10). | ❌ | Advanced | Low |
| *(folder)* `.mime` *(preview)* | Fixed metadata MIME marker. | ➖ | — | — |
| *(user-defined)* `.content` | Inline text baked into the agent's context without a file. | ❌ | Basic | Medium |
| `type` (×3 variants) | Discriminators. | ➖ | — | — |

## tool_sets

The form is a **resource picker** — you choose published Toolset/Agent resources from the catalog,
and their internals are owned by that resource, not by this app. Everything below is reachable in
this editor only through the raw **JSON** toggle.
[`config/toolsets/`](../src/quickapp/config/toolsets) · [`config/tools/`](../src/quickapp/config/tools)

### Common to every toolset

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `name` | Toolset name; prefixes every tool name sent to the LLM. | ✅ *picker* | — | — |
| `description` | Toolset-level description shown to the LLM — steers *when* the agent reaches for that group of tools. | 📝 | Basic | **High** |
| `enabled` | Switch a toolset off without removing it. | 📝 | Basic | Medium |
| `deferred` *(preview)* | Opt this toolset in/out of dynamic discovery. Inert without `orchestrator.tool_discovery.enabled`. [design](./designs/dynamic_tool_discovery.md) | 📝 | Advanced | **High** |
| `type` | Discriminator. | ➖ | — | — |

### Common to every tool

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `enabled` | Switch a single tool off inside a toolset. | 📝 | Advanced | Low |
| `open_ai_tool` | The tool's function schema (name, description, parameters) — owned by the toolset resource. | 📝 | Advanced | Low |
| `attachment.supported_types` | Which attachment types the tool may return. [design](./designs/attachment_config_redesign.md) | 📝 | Advanced | Low |
| `attachment.propagate_types_to_choice` | Which types get promoted from the stage onto the answer. | 📝 | Advanced | Low |
| `attachment.media_type_substitution` | MIME remapping for custom visualizers. | 📝 | Advanced | Low |
| `fallback_configuration.strategies[]` | What happens when the tool fails — `continue` with instructions, or `hard_stop`; optionally scoped by `trigger_on` (value + case sensitivity). [design](./designs/fallback_strategies_refactor.md) | 📝 | Advanced | Low |
| `fallback_configuration.display_error_in_stage` | Show the error text in the stage, or just an error notification. | 📝 | Advanced | Low |
| `display.stage.name` / `.body` | Human-readable stage title/body with `{arg}` placeholders, instead of the raw tool name — the main lever on what users see while the agent works. | 📝 | Advanced | Low |
| `display.stage.defer_close` | Keep the stage open until parallel tool execution finishes. | 📝 | Advanced | Low |
| `display.stage.show` | Deprecated — superseded by `features.stage_display.level`. | ➖ | — | — |
| `type` | Discriminator. | ➖ | — | — |

### `rest-api`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `authorization` | Credentials for the API: `basic`, `bearer`, `client_id_secret` (OAuth2 client-credentials), `api_key` (header/query/body), or `forward_auth_token` (forwards the caller's DIAL bearer). Live and applied per request; normally owned by the Toolset resource, not this app. Note: the interactive-login flow is MCP-only and does **not** cover REST tools. | 📝 | Advanced | Low |
| `response_as_attachment.enabled` | Wrap the HTTP response as a DIAL file the user can download. | 📝 | Advanced | Low |
| `response_as_attachment.content_types` | Which response `Content-Type`s become attachments (default all). | 📝 | Advanced | Low |
| `response_as_attachment.include_body_as_content` | Keep the body as tool content too, or replace it with `See attached file: …` to keep large payloads out of context. | 📝 | Advanced | Low |
| `tools[].rest_api_method_info.method_url` / `.method_type` | Endpoint URL and HTTP verb. | 📝 | Advanced | Low |
| `tools[].response_as_attachment.*` | Per-tool override of the toolset default (3 fields). | 📝 | Advanced | Low |

### `dial-deployment`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `tools[].deployment.deployment_id` | Which DIAL deployment this subagent tool calls. | 📝 | Advanced | Low |
| `tools[].deployment.parameters.*` | Subagent sampling params — same 10 fields as the orchestrator. | 📝 | Advanced | Low |
| `tools[].deployment.parameters.tools` | Static tools the target deployment runs on its own side (e.g. web search); forwarded, never executed here. [design](./designs/external_tools_passthrough.md) | 📝 | Advanced | Low |
| `tools[].system_prompt` | The subagent's own system prompt (inline or from DIAL). | 📝 | Advanced | Low |
| `tools[].content_propagation.propagate_headers` | Which request headers are forwarded to the deployment. | 📝 | Advanced | Low |
| `tools[].conversation_mode.resumable` | Subagent keeps a session across calls instead of starting fresh. [design](./designs/subagents_conversation_mode.md) | 📝 | Advanced | Low |
| `tools[].propagate_annotations_to_choice` *(preview)* | Forward the deployment's citation annotations onto the app's answer. | 📝 | Advanced | Low |
| `tools[]` *(simple)* `.deployment_id` / `.enabled` / `.conversation_mode` / `.propagate_annotations_to_choice` | Shorthand deployment-tool form (4 fields). | 📝 | Advanced | Low |
| `tools[].content_propagation.propagate_history` | Deprecated — use `conversation_mode.resumable`. | ➖ | — | — |
| `tools[].supports_url_attachments` | Snapshotted from the deployment's `features.url_attachments` at build time. | ➖ | — | — |

### `internal`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `tools[]` | Built-in Python tools. The *Code Interpreter* toggle covers the Python-execution toolset; anything else is JSON-only. | 🟡 *Code Interpreter* | Advanced | Low |

### `mcp`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `mcp_server_info.url` / `.protocol` / `.authorization` | Point at an external MCP server. | 📝 | Advanced | Low |
| `allowed_tools` | Whitelist which of the server's tools reach the agent. | 📝 | Advanced | Low |
| `resources.enabled` / `.items[].uri` / `.items[].eager` | Expose MCP resources — all lazily, or a named subset with eager loading. [design](./designs/mcp_capabilities_extension.md) | 📝 | Advanced | Low |

### `dial-app`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `deployment_id` | The DIAL app/deployment used as a toolset. [design](./designs/dial_app_toolset.md) | ✅ *picker* | — | — |
| `transport` | `auto` / `mcp` / `chat-completion` routing override. | 📝 | Advanced | Low |
| `allowed_tools` | Tool whitelist (MCP branch only). | 📝 | Advanced | Low |
| `conversation_mode.resumable` | Resumable subagent session (chat-completion branch only). | 📝 | Advanced | Low |

### `dial-mcp`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `deployment_id` | The DIAL-hosted MCP deployment. | ✅ *picker* | — | — |
| `transport` | `HTTP` or `SSE`. | 📝 | Advanced | Low |
| `allowed_tools` | Tool whitelist. | 📝 | Advanced | Low |
| `resources.*` | Resource exposure (3 fields, as `mcp`). | 📝 | Advanced | Low |
| `dial_id` | Deprecated alias for `deployment_id`. | ➖ | — | — |

### `predefined`

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `template_name` | Reference a server-shipped toolset template by name. [design](./designs/layered_predefined_config.md) | 📝 | Advanced | Low |
| `override` | JSON Merge Patch applied to the resolved template. [design](./designs/predefined_template_overrides.md) | 📝 | Advanced | Low |
| `tools[]` *(predefined)* `.template_name` / `.enabled` / `.override` | Same, per tool. | 📝 | Advanced | Low |

## conversation_starters

Fully covered.

| Field | What it does | Status |
|---|---|---|
| `starters[].title` / `.text` | Button label and the prompt it sends. | ✅ |
| `intro_text` | Text above the starter buttons. | ✅ *Intro text* |
| `auto_submit` | Send immediately vs populate the input for editing. | ✅ *Starters behavior* |
| `chat_message_input_disabled` | Restrict users to the starter buttons only. | ✅ *Disable chat input* |

## starters

| Field | What it does | Status |
|---|---|---|
| `starters` | Deprecated — superseded by `conversation_starters`. | ➖ |

## skills

[`config/skill.py`](../src/quickapp/config/skill.py) · [`docs/skills.md`](./skills.md)

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| *(dial-prompt)* `.url` | Attach a DIAL prompt as a reusable instruction module. | ✅ *Agent Skills* | — | — |
| *(dial-skill)* `.url` *(preview)* | Attach a DIAL **skill resource** (`skills/<bucket>/<path>` — a folder with `SKILL.md` plus files the agent reads on demand). The picker browses prompts and offers "Create prompt", so only prompt skills can be attached. [design](./designs/skills_as_dial_resource.md) | ❌ | Basic | **High** |
| `type` (×2) | Discriminators. | ➖ | — | — |

## hooks

No UI at all. Config-driven synthetic tool calls fired at named orchestrator seams — e.g. always
seed the conversation with a directory listing, refreshed on a TTL.
[`config/hooks.py`](../src/quickapp/config/hooks.py) · [design](./designs/config_driven_hooks.md)

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `event` | Which orchestrator seam fires the hook. | ❌ | Advanced | Low |
| `name` | Label for the injected call. | ❌ | Advanced | Low |
| `tool_name` | Tool to invoke. | ❌ | Advanced | Low |
| `toolset_name` | Disambiguates the tool when names collide. | ❌ | Advanced | Low |
| `arguments` | Arguments passed to the tool. | ❌ | Advanced | Low |
| `frequency` | How often it is re-injected (`append_if_changed`, …). | ❌ | Advanced | Low |
| `refresh_condition.kind` / `.ttl_minutes` | TTL-based refresh. | ❌ | Advanced | Low |
| `kind` | Discriminator. | ➖ | — | — |

## features

[`config/application.py`](../src/quickapp/config/application.py) ·
[`config/dial_files.py`](../src/quickapp/config/dial_files.py) ·
[`config/web_fetch.py`](../src/quickapp/config/web_fetch.py)

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `timestamp` | Agent knows the current time. [docs](./time_awareness.md) | ✅ *Time awareness* | — | — |
| `timestamp.injection_strategy` | Fixed to `tool_call` — the only allowed value. | ➖ | — | — |
| `file_loading.size_limit` | Per-app cap on a single downloaded file; otherwise the env default (10 MiB). | ❌ | Advanced | Medium |
| `external_url_fetch.enabled` | Per-app opt-out of fetching external URLs, inside the admin env cap. [design](./designs/external_url_attachments.md) | ❌ | Advanced | Medium |
| `external_url_fetch.host_allowlist` | Narrow the allowed hosts (intersected with the admin list). | ❌ | Advanced | Medium |
| `stage_display.level` | How much of the agent's work users see: `none` / `error` / `info` / `debug`. [design](./designs/stage_display_level.md) | ❌ | Advanced | Medium |
| `dial_files` | Built-in file tools for the app's storage. [design](./designs/dial_files_tools.md) | 🟡 *File tools* — all-or-nothing | — | — |
| `dial_files.enabled_tools` | Expose a subset instead of all nine (e.g. read-only: `read_lines` + `search`). | ❌ | Advanced | Medium |
| `dial_files.agent_home_dir` | Root the agent in a subfolder of the app's appdata. | ❌ | Advanced | Medium |
| `dial_files.max_files_scanned` | Cap on files downloaded per folder-mode `search` (default 50). [design](./designs/dial_files_search.md) | ❌ | Advanced | Low |
| `dial_files.tool_call_result_offload.enabled` *(preview)* | Offload oversized tool results to a file, read back on demand. [design](./designs/large_tool_responses.md) | ❌ | Advanced | Low |
| `dial_files.tool_call_result_offload.size_threshold` *(preview)* | Byte threshold that triggers offloading. | ❌ | Advanced | Low |
| `dial_files.tool_call_result_offload.excluded_tools` *(preview)* | Tools exempt from offloading. | ❌ | Advanced | Low |
| `web_fetch.enabled` *(preview)* | Expose `internal_web_fetch` — fetch an external resource inline or save it to the workspace. [design](./designs/web_fetch_tool.md) | ❌ | Basic | **High** |
| `web_fetch.max_inline_size` *(preview)* | Byte cap on text returned inline by `internal_web_fetch`. | ❌ | Advanced | Low |
| `representation_tooling.add_attachment` *(preview)* | Let the agent attach a file it produced to its own answer. [design](./designs/add_attachment_to_response.md) | ❌ | Basic | **High** |

## tool_defaults

| Field | What it does | Status | Tier | Pri |
|---|---|---|---|---|
| `timeout_seconds` | Timeout applied to every tool call in the app; otherwise the env default. Slow REST/MCP backends need it raised per app. [design](./designs/configurable_timeouts.md) | ❌ | Advanced | Medium |

---

## Out of scope

Handled elsewhere, listed so they are not mistaken for gaps:

- **General step** (avatar, name, version, description, tags) — DIAL application metadata, not this config.
- **User attachments** (*Attachment types*, *Max. attachments number*) — DIAL application-level
  `inputAttachmentTypes` / `maxInputAttachments`, not the Quick Apps manifest.
- **Toolset internals** — owned by the published Toolset resource, edited in its own editor; the
  📝 rows above describe what this app's manifest could override. REST `authorization` belongs to
  this group: it is a live manifest field, but credentials are normally set on the toolset resource.
- **Interactive login** — the `toolset/signin` / `external-service/signin` recovery flow
  ([design](./designs/interactive_login.md)) is wired into MCP tooling only; it is not an
  alternative to REST `authorization`.
