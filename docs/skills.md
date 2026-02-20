# Agent Skills

Agent skills are reusable instruction modules that enhance agent capabilities. Skills follow the
[Agent Skills](https://agentskills.io/) open standard and are defined as Markdown files with YAML frontmatter inside
named directories. They are automatically loaded and made available to the agent at runtime.

> **Partial support.** Quick Apps implements a subset of the
> [Agent Skills specification](https://agentskills.io/specification). See
> [Supported vs unsupported features](#supported-vs-unsupported-features) below for details.

## How Skills Work

- Skills are loaded from `config/predefined/skills/` at startup. Each skill lives in its own subdirectory
  (e.g. `skills/my-skill/SKILL.md`).
- Each skill is presented to the agent as XML metadata in the system prompt.
- The agent can read detailed skill instructions on-demand using the internal `read_skill` tool.
- Skills support metadata including name, description, license, compatibility, and allowed tools.
- Extra skill directories can be layered via `PREDEFINED_EXTRA_PATHS` (see [README](../README.md) for env var details).

## Directory Layout

```
config/predefined/skills/
└── my-skill/
    └── SKILL.md
```

The directory name **must** match the `name` field in the YAML frontmatter. Skills that fail this check are skipped at
startup.

## Creating a Skill

Create a directory under `config/predefined/skills/` named after the skill, then add a `SKILL.md` file:

```markdown
---
name: my-skill
description: Brief description of what this skill does
license: MIT
compatibility: Requires specific tools or environment
metadata:
  version: "1.0"
  author: "Your Name"
allowed-tools: tool1 tool2 tool3
---

# Skill Title

Detailed instructions and guidelines for the agent...
```

## Metadata Fields

| Field           | Required | Description                                          | Constraints                                                                                        |
|-----------------|----------|------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| `name`          | Yes      | Unique skill identifier                              | Max 64 chars, lowercase letters/numbers/hyphens only, no leading/trailing or consecutive hyphens   |
| `description`   | Yes      | Brief skill description                              | Max 1024 chars, non-empty                                                                          |
| `license`       | No       | License name or reference                            | Any string                                                                                         |
| `compatibility` | No       | Environment or tool requirements                     | Max 500 chars                                                                                      |
| `metadata`      | No       | Arbitrary key-value mappings                         | Dictionary of strings                                                                              |
| `allowed-tools` | No       | Space-delimited list of tool names the skill can use | List or space-delimited string                                                                     |

## Example

```
config/predefined/skills/
└── data-analysis-helper/
    └── SKILL.md
```

```markdown
---
name: data-analysis-helper
description: Provides guidelines for analyzing and visualizing data using available tools
compatibility: Requires Python interpreter and plotting libraries
metadata:
  version: "1.0"
  category: data-science
allowed-tools: py_interpreter plot_generator
---

# Data Analysis Helper

## Purpose

Guide the agent through systematic data analysis workflows.

## Instructions

1. First examine the data structure
2. Identify patterns and outliers
3. Create visualizations when appropriate
4. Provide statistical summaries
```

## Notes

- Skills are validated at startup; invalid skills are logged and skipped.
- The agent receives skill metadata automatically but must explicitly call `read_skill` to access full content.
- Skills can reference specific tools via the `allowed-tools` field.
- Built-in skills (e.g. `tool-call-file-parameter-formatting`) are included by default.
- Restart the service after adding or modifying skills to reload them.
- Flat `.md` files placed directly in `skills/` (not in a subdirectory) are ignored.

## Supported vs Unsupported Features

Quick Apps implements the core of the [Agent Skills specification](https://agentskills.io/specification) but not all
optional features. The table below summarises what is and isn't supported.

| Feature | Status | Notes |
|---|---|---|
| `SKILL.md` with YAML frontmatter | Supported | All standard frontmatter fields are parsed and validated. |
| Directory-based layout (`skill-name/SKILL.md`) | Supported | Directory name must match `name` in frontmatter. |
| `name` validation (length, charset, consecutive hyphens) | Supported | |
| `description`, `license`, `compatibility`, `metadata` | Supported | |
| `allowed-tools` | Partial | Exposed in XML metadata but **not enforced** at runtime. |
| Optional subdirectories (`scripts/`, `references/`, `assets/`) | Not supported | Only `SKILL.md` is read; other directory contents are ignored. |
| Progressive disclosure (on-demand file references) | Not supported | The agent can read `SKILL.md` content via `read_skill` but cannot access referenced files within the skill directory. |
| Dynamic skill registration | Not supported | Skills are loaded once at startup; adding or modifying skills requires a restart. |

For the full specification, see [agentskills.io/specification](https://agentskills.io/specification).
For design rationale and known limitations, see [the design doc](designs/skills_and_file_transfer.md).