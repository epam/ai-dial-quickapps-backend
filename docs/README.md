# Quick Apps Documentation

This folder contains technical documentation for the Quick Apps backend.

## Contents

| Document                    | Description                                                                                                                          |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [Agent Design](./agent.md)  | Internal architecture of the Quick Apps agent system, including the orchestrator loop, tool system, and message processing pipeline. |

## Preview Features

Documentation for features in [Preview](../README.md#feature-lifecycle) status lives in [`preview/`](./preview/).
These features may change in breaking ways without a major version bump.

| Document                                         | Description                                                                   |
|--------------------------------------------------|-------------------------------------------------------------------------------|
| [Agent Skills](./preview/skills.md) `[Preview]`  | How to create and manage reusable agent skills (directory layout, metadata).  |

## Diagrams

Architecture diagrams are stored in `content/svg/` as editable draw.io files. To modify a diagram:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/)
2. Make your changes
3. Export as SVG with `Appearance -> Light`, `Embed images` & `Embed fonts` checked.

## Related Documentation

- [Configuration Reference](../CONFIGURATION.md) - Application configuration, environment variables, and examples
- [Main README](../README.md) - Quick start and local development setup