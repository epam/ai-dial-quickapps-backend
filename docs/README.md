# Quick Apps Documentation

This folder contains technical documentation for the Quick Apps backend.

## How to read these docs (for humans and agents)

Search **top-down**. Stop at the first layer that fully answers the question.

| Layer | What it answers | Where |
|-------|-----------------|-------|
| **L0 — Map** | Which capability exists and where to read next | This file |
| **L1 — Configure** | Manifest fields, env vars, recipes | [`CONFIGURATION.md`](../CONFIGURATION.md), [`README.md`](../README.md) |
| **L2 — Behaviour** | How a capability works end-to-end | Guides in this folder (`agent.md`, `skills.md`, …) |
| **L3 — Design** | Why it was built this way; edge cases | [`designs/`](./designs/) |
| **L4 — Code** | Ground truth when docs disagree | `src/quickapp/` |

**Rules of thumb**

- “How do I configure X?” → **L1** (`CONFIGURATION.md`). Prefer it over design docs.
- “What happens when …?” → **L2** guides, then L1 samples.
- “Why this shape / trade-off?” → **L3** designs (check **Status**; prefer `Implemented`).
- Design docs are historical once Implemented — do not treat Draft/Approved-only text as runtime behaviour.

## Capability map (L0)

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
| Stage display | [CONFIGURATION — Stage display](../CONFIGURATION.md#stage-display-configuration) / [README](../README.md#stage-display-level) | — | [stage_display_level.md](./designs/stage_display_level.md) |
| Time awareness | [CONFIGURATION — Timestamp](../CONFIGURATION.md#timestamp-configuration) | [time_awareness.md](./time_awareness.md) | [time_awareness.md](./designs/time_awareness.md) |
| Resumable subagents | [CONFIGURATION — Conversation mode](../CONFIGURATION.md#conversation-mode) | — | [subagents_conversation_mode.md](./designs/subagents_conversation_mode.md) |
| Conversation starters | [CONFIGURATION — Conversation starters](../CONFIGURATION.md#conversation-starters-configuration) | — | — |
| MCP resources | [CONFIGURATION — MCP resources](../CONFIGURATION.md#mcp-resources-configuration) | — | [mcp_capabilities_extension.md](./designs/mcp_capabilities_extension.md) |
| Interactive login (MCP) | [README env](../README.md#environment-variables) (`DIAL_INTERACTIVE_LOGIN_TIMEOUT_SECONDS`) | [agent.md](./agent.md) | [interactive_login.md](./designs/interactive_login.md) |
| Logging | [README](../README.md) / [logging.md](./logging.md) | [logging.md](./logging.md) | [log_levels_and_content_policy.md](./designs/log_levels_and_content_policy.md) |
| Error handling | — | [error_handling.md](./error_handling.md) | [error_message_resolution.md](./designs/error_message_resolution.md) |
| Application schema | [application-schema.md](./application-schema.md) | — | — |
| ChatHub templates | [chathub.md](./chathub.md) | — | — |
| Custom CA certs | [custom_ca_certificates.md](./custom_ca_certificates.md) | — | — |
| Skills (predefined + dial-prompt) | [CONFIGURATION — Skills](../CONFIGURATION.md#skills-configuration) | [skills.md](./skills.md) | [dial_prompts_as_skills.md](./designs/dial_prompts_as_skills.md) |

### Preview

Require `ENABLE_PREVIEW_FEATURES=true`. May change without a major version bump.
See [Feature Lifecycle](../README.md#feature-lifecycle).

| Capability | Configure (L1) | Behaviour (L2) | Design (L3) |
|------------|----------------|----------------|-------------|
| Config-driven hooks | [CONFIGURATION — Hooks](../CONFIGURATION.md#hooks-configuration) / [README](../README.md#hooks-preview) | — | [config_driven_hooks.md](./designs/config_driven_hooks.md) |
| Dynamic tool discovery | [CONFIGURATION — Tool discovery](../CONFIGURATION.md#tool-discovery-configuration) / [README](../README.md#dynamic-tool-discovery-preview) | — | [dynamic_tool_discovery.md](./designs/dynamic_tool_discovery.md) |
| Web fetch (`internal_web_fetch`) | [CONFIGURATION — Web fetch](../CONFIGURATION.md#web-fetch-configuration) / [README](../README.md#web-fetch-preview) | — | [web_fetch_tool.md](./designs/web_fetch_tool.md) |
| Tool-result offload | [CONFIGURATION — DIAL files offload](../CONFIGURATION.md#tool-call-result-offload-preview) | — | [large_tool_responses.md](./designs/large_tool_responses.md) |
| Representation add-attachment | [CONFIGURATION — Representation tooling](../CONFIGURATION.md#representation-tooling-configuration) | — | [add_attachment_to_response.md](./designs/add_attachment_to_response.md) |
| Folder context | [CONFIGURATION — Folder context](../CONFIGURATION.md#folder-context-type-folder-preview) | — | [folder_context.md](./designs/folder_context.md) |
| DIAL skill resources (`dial-skill`) | [CONFIGURATION — Skills](../CONFIGURATION.md#skills-configuration) | [skills.md](./skills.md) | [skills_as_dial_resource.md](./designs/skills_as_dial_resource.md) |
| Skill invocation from a message | [README env](../README.md#environment-variables) / [skills.md](./skills.md#invoking-a-skill-from-a-message-preview) | [skills.md](./skills.md) | [skill_invocation.md](./designs/skill_invocation.md) |
| Citation annotation propagation | [CONFIGURATION — Citations](../CONFIGURATION.md#citation-annotations) | [agent.md](./agent.md) | — |

## Contents (L2 guides)

| Document                                      | Description                                                                                                                          |
|-----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [Agent Design](./agent.md)                    | Internal architecture of the Quick Apps agent system, including the orchestrator loop, tool system, and message processing pipeline. |
| [Application Schema](./application-schema.md) | How to configure QuickApps in DIAL Core (schema endpoint vs full schema).                                                            |
| [ChatHub](./chathub.md)                       | Configuration guide for ChatHub variants — variant structure, authoring, and customization recipes.                                  |
| [Error Handling](error_handling.md)           | How runtime failures become user-facing errors: resolution precedence, error-reference correlation, DIAL protocol delivery.          |
| [File Transfer](file_transfer.md)             | How Quick Apps handles file parameters in tool calls (`file:{prefix}::` convention, preprocessing pipeline).                         |
| [Logging](logging.md)                         | Console log configuration: levels, text and JSON output modes, OTEL trace correlation, OTLP log export.                              |
| [Agent Skills](skills.md)                     | How to create and manage reusable agent skills (directory layout, metadata, DIAL sources, invocation).                               |
| [Time Awareness](time_awareness.md)           | How the agent knows the current time and reasons about data freshness.                                                               |
| [Custom CA Certificates](custom_ca_certificates.md) | How to trust a private/corporate Root CA when running behind a TLS-intercepting proxy (`USE_SYSTEM_CA_CERTS`).               |

## Diagrams

Architecture diagrams are stored in `content/svg/` as editable draw.io files. To modify a diagram:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/)
2. Make your changes
3. Export as SVG with `Appearance -> Light`, `Embed images` & `Embed fonts` checked.

## Related Documentation

- [Configuration Reference](../CONFIGURATION.md) - Application configuration, environment variables, and examples
- [Main README](../README.md) - Quick start and local development setup
- [Design documents](./designs/README.md) - Design lifecycle and writing guidelines
