# Quick Apps Documentation

This folder contains technical documentation for the Quick Apps backend.

## Contents

| Document                                      | Description                                                                                                                          |
|-----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [Agent Design](./agent.md)                    | Internal architecture of the Quick Apps agent system, including the orchestrator loop, tool system, and message processing pipeline. |
| [Application Schema](./application-schema.md) | How to configure QuickApps in DIAL Core (schema endpoint vs full schema).                                                            |
| [ChatHub](./chathub.md)                       | Configuration guide for ChatHub variants — variant structure, authoring, and customization recipes.                                  |
| [File Transfer](file_transfer.md)             | How Quick Apps handles file parameters in tool calls (`file:{prefix}::` convention, preprocessing pipeline).                         |
| [Agent Skills](skills.md)                     | How to create and manage reusable agent skills (directory layout, metadata).                                                         |

## Preview Features

Preview features may change in breaking ways without a major version bump.
See [Feature Lifecycle](../README.md#feature-lifecycle) for details.

| Document                              | Description                                                                  |
|---------------------------------------|------------------------------------------------------------------------------|
| [Time Awareness](time_awareness.md) `[Preview]`  | How the agent knows the current time and reasons about data freshness.       |

## Diagrams

Architecture diagrams are stored in `content/svg/` as editable draw.io files. To modify a diagram:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/)
2. Make your changes
3. Export as SVG with `Appearance -> Light`, `Embed images` & `Embed fonts` checked.

## Related Documentation

- [Configuration Reference](../CONFIGURATION.md) - Application configuration, environment variables, and examples
- [Main README](../README.md) - Quick start and local development setup
