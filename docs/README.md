# Quick Apps Documentation

Hub for all Quick Apps backend documentation.

## How to read these docs

Search **top-down**. Stop at the first layer that fully answers the question.

| Layer | What it answers | Where |
|-------|-----------------|-------|
| **L0 — Hub** | Which topic exists and where to go next | This file |
| **L1 — Configure / operate** | Manifest fields, env vars, local run | [CONFIGURATION.md](../CONFIGURATION.md), [local-development.md](./local-development.md) |
| **L2 — Behaviour** | How a capability works end-to-end | Guides below (`agent.md`, `skills.md`, …) |
| **L3 — Design** | Why it was built this way; trade-offs | [designs/](./designs/) |
| **L4 — Code** | Ground truth when docs disagree | `src/quickapp/` |

**Rules of thumb**

- “How do I configure X?” → **L1** ([CONFIGURATION.md](../CONFIGURATION.md)). Prefer it over design docs.
- “How do I run this locally?” → **L1** ([local-development.md](./local-development.md)).
- “What happens when …?” → **L2**, then L1 samples.
- “Why this shape / trade-off?” → **L3** designs (check **Status**; prefer `Implemented`).
- Design docs are historical once Implemented — do not treat Draft/Approved-only text as runtime behaviour.

Root entry: [../README.md](../README.md) (project overview + links only).

## Feature Lifecycle

Preview features may change in breaking ways without a major version bump.
See [Feature Lifecycle](../README.md#feature-lifecycle) in the root README.

## Capability map

### Stable

| Capability | Configure (L1) | Behaviour (L2) | Design (L3, optional) |
|------------|----------------|----------------|------------------------|
| Orchestrator / agent loop | [CONFIGURATION — Orchestrator](../CONFIGURATION.md#orchestrator-configuration) | [agent.md](./agent.md) | — |
| Attachment strategy (`lazy_on_demand`) | [CONFIGURATION — Attachment strategy](../CONFIGURATION.md#attachment-strategy-configuration) | [agent.md](./agent.md#orchestrator-attachment-strategies) | [pass_attachments_to_orchestrator.md](./designs/pass_attachments_to_orchestrator.md) |
| Tool sets (REST, MCP, DIAL, internal) | [CONFIGURATION — Tool sets](../CONFIGURATION.md#tool-sets-configuration) | [agent.md](./agent.md) | — |
| Tool fallbacks | [CONFIGURATION — Tool Fallback](../CONFIGURATION.md#tool-fallback-configuration) | — | [fallback_strategies_refactor.md](./designs/fallback_strategies_refactor.md) |
| File transfer (`file:{prefix}::`) | — | [file_transfer.md](./file_transfer.md) | — |
| External URL egress | [CONFIGURATION — External URL fetch](../CONFIGURATION.md#external-url-fetch-configuration) | [file_transfer.md](./file_transfer.md) | [external_url_attachments.md](./designs/external_url_attachments.md) |
| DIAL files tools | [CONFIGURATION — DIAL files](../CONFIGURATION.md#dial-files-configuration) | — | [dial_files_tools.md](./designs/dial_files_tools.md) |
| Stage display | [CONFIGURATION — Stage display](../CONFIGURATION.md#stage-display-configuration) | — | [stage_display_level.md](./designs/stage_display_level.md) |
| Time awareness | [CONFIGURATION — Timestamp](../CONFIGURATION.md#timestamp-configuration) | [time_awareness.md](./time_awareness.md) | [time_awareness.md](./designs/time_awareness.md) |
| Resumable subagents | [CONFIGURATION — Conversation mode](../CONFIGURATION.md#conversation-mode) | — | [subagents_conversation_mode.md](./designs/subagents_conversation_mode.md) |
| Conversation starters | [CONFIGURATION — Conversation starters](../CONFIGURATION.md#conversation-starters-configuration) | — | — |
| MCP resources | [CONFIGURATION — MCP resources](../CONFIGURATION.md#mcp-resources-configuration) | — | [mcp_capabilities_extension.md](./designs/mcp_capabilities_extension.md) |
| Interactive login (MCP) | [CONFIGURATION — Environment Variables](../CONFIGURATION.md#environment-variables) (`DIAL_INTERACTIVE_LOGIN_TIMEOUT_SECONDS`) | [agent.md](./agent.md) | [interactive_login.md](./designs/interactive_login.md) |
| Logging | [CONFIGURATION — Environment Variables](../CONFIGURATION.md#environment-variables) / [logging.md](./logging.md) | [logging.md](./logging.md) | [log_levels_and_content_policy.md](./designs/log_levels_and_content_policy.md) |
| Error handling | — | [error_handling.md](./error_handling.md) | [error_message_resolution.md](./designs/error_message_resolution.md) |
| Application schema | [application-schema.md](./application-schema.md) | — | — |
| ChatHub templates | [chathub.md](./chathub.md) | — | — |
| Custom CA certs | [custom_ca_certificates.md](./custom_ca_certificates.md) | — | — |
| Skills (predefined + dial-prompt) | [CONFIGURATION — Skills](../CONFIGURATION.md#skills-configuration) | [skills.md](./skills.md) | [dial_prompts_as_skills.md](./designs/dial_prompts_as_skills.md) |

### Preview

Require `ENABLE_PREVIEW_FEATURES=true`. May change without a major version bump.

| Capability | Configure (L1) | Behaviour (L2) | Design (L3) |
|------------|----------------|----------------|-------------|
| Config-driven hooks | [CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration) | — | [config_driven_hooks.md](./designs/config_driven_hooks.md) |
| Dynamic tool discovery | [CONFIGURATION — Tool discovery](../CONFIGURATION.md#tool-discovery-configuration) | — | [dynamic_tool_discovery.md](./designs/dynamic_tool_discovery.md) |
| Web fetch (`internal_web_fetch`) | [CONFIGURATION — Web fetch](../CONFIGURATION.md#web-fetch-configuration) | — | [web_fetch_tool.md](./designs/web_fetch_tool.md) |
| Tool-result offload | [CONFIGURATION — DIAL files offload](../CONFIGURATION.md#tool-call-result-offload) | — | [large_tool_responses.md](./designs/large_tool_responses.md) |
| Representation add-attachment | [CONFIGURATION — Representation tooling](../CONFIGURATION.md#representation-tooling-configuration) | — | [add_attachment_to_response.md](./designs/add_attachment_to_response.md) |
| Folder context | [CONFIGURATION — Folder context](../CONFIGURATION.md#folder-context-type-folder) | — | [folder_context.md](./designs/folder_context.md) |
| DIAL skill resources (`dial-skill`) | [CONFIGURATION — Skills](../CONFIGURATION.md#skills-configuration) | [skills.md](./skills.md) | [skills_as_dial_resource.md](./designs/skills_as_dial_resource.md) |
| Skill invocation from a message | [CONFIGURATION — Environment Variables](../CONFIGURATION.md#environment-variables) / [skills.md](./skills.md#invoking-a-skill-from-a-message-preview) | [skills.md](./skills.md) | [skill_invocation.md](./designs/skill_invocation.md) |
| Citation annotation propagation | [CONFIGURATION — Citations](../CONFIGURATION.md#citation-annotations) | [agent.md](./agent.md) | — |

## Behaviour guides (L2)

| Document | Description |
|----------|-------------|
| [Agent Design](./agent.md) | Orchestrator loop, tool system, message processing pipeline |
| [Application Schema](./application-schema.md) | Schema endpoint vs full schema in DIAL Core |
| [ChatHub](./chathub.md) | ChatHub variants — structure, authoring, recipes |
| [Error Handling](./error_handling.md) | User-facing errors, correlation, DIAL protocol delivery |
| [File Transfer](./file_transfer.md) | `file:{prefix}::` convention and preprocessing pipeline |
| [Logging](./logging.md) | Console log modes, OTEL correlation, OTLP export |
| [Agent Skills](./skills.md) | Skill layout, metadata, DIAL sources, invocation |
| [Time Awareness](./time_awareness.md) | Current time and data freshness |
| [Custom CA Certificates](./custom_ca_certificates.md) | Trust private/corporate Root CA (`USE_SYSTEM_CA_CERTS`) |
| [Local development](./local-development.md) | Setup, run, format, lint, tests |

## Diagrams

Architecture diagrams are stored in `content/svg/` as editable draw.io files. To modify a diagram:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/)
2. Make your changes
3. Export as SVG with `Appearance -> Light`, `Embed images` & `Embed fonts` checked.

## Related

- [Design documents](./designs/README.md) — design lifecycle and writing guidelines
- [Root README](../README.md) — project overview
