# Agent Skills

Agent skills are reusable instruction modules that enhance agent capabilities. Skills follow the
[Agent Skills](https://agentskills.io/) open standard and are defined as Markdown files with YAML frontmatter inside
named directories. They are automatically loaded and made available to the agent at runtime.

> [!NOTE]
> Quick Apps implements a subset of the [Agent Skills specification](https://agentskills.io/specification). See
> [Supported vs unsupported features](#supported-vs-unsupported-features) below for details.

## How Skills Work

Skills come from three sources, merged per request:

| Source | Origin | Bundled files |
|---|---|---|
| Predefined | `config/predefined/skills/`, loaded at startup | No |
| [DIAL prompt](#dial-prompt-skills) | `prompts/<bucket>/<path>`, per request | No |
| [DIAL skill resource](#dial-skill-resources) | `skills/<bucket>/<path>`, per request | Yes, text files |

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
| Optional subdirectories (`scripts/`, `references/`, `assets/`) | Partial | Supported for [DIAL skill resources](#dial-skill-resources) (text files only). Predefined and DIAL-prompt skills read `SKILL.md` alone. |
| Progressive disclosure (on-demand file references) | Partial | Supported for [DIAL skill resources](#dial-skill-resources) via `read_skill(skill_name, file_path)`. Not available for the other two sources. |
| Dynamic skill registration | Partial | DIAL-prompt and DIAL-skill sources are resolved fresh per request. Predefined skills are loaded once at startup; adding or modifying them requires a restart. |

For the full specification, see [agentskills.io/specification](https://agentskills.io/specification).
For design rationale and known limitations, see [the design doc](designs/skills_and_file_transfer.md).

## DIAL Prompt Skills

In addition to predefined skills bundled at build time, users can configure skills sourced from
**DIAL prompts** — text content stored via the DIAL Core prompts API (`/v1/prompts/`). A DIAL prompt
whose content follows the Agent Skills specification (valid YAML frontmatter with `name` and
`description`) can be referenced in a QuickApp config and used as a skill.

### Configuration

Add a `skills` array to the application config:

```json
{
  "orchestrator": { "..." : "..." },
  "contexts": [],
  "tool_sets": [],
  "skills": [
    {
      "type": "dial-prompt",
      "url": "prompts/<bucket>/<folder>/<prompt-name>"
    }
  ]
}
```

The `url` field must be a relative path including the `prompts/` resource type prefix
(e.g. `prompts/my-bucket/skills/code-review`). This follows the same convention as file context URLs
(`files/<bucket>/...`). DIAL Core auto-shares the referenced prompt at deployment time via the
`dial:resource` annotation.

### Skill Validation

DIAL prompt skills are validated at request time using the same rules as predefined skills:

- Must have YAML frontmatter delimited by `---`
- `name` (required): max 64 chars, lowercase alphanumeric + hyphens
- `description` (required): max 1024 chars
- Prompts with no content, empty content, or invalid frontmatter are silently skipped with a warning log

### Name Collision

If a DIAL prompt skill has the same `name` as a predefined (admin-configured) skill, the **predefined
skill takes precedence**. The DIAL prompt skill is skipped and a warning is logged.

### Error Handling

- **Invalid prompt**: Skipped with a warning. Other skills remain available.
- **Inaccessible prompt** (404, 403): Skipped with a warning. The request is served with remaining skills.
- **DIAL Core outage**: Falls back to predefined-only skills. A DIAL Core failure never prevents
  the request from being served.

### Limitations

- DIAL prompts are single text documents — they cannot contain `scripts/`, `references/`, or `assets/`
  subdirectories.
- DIAL prompts are fetched fresh on each request (no cross-request caching).
- A prompt cannot bundle files. Use a [DIAL skill resource](#dial-skill-resources) when the skill
  needs reference material the agent can open on demand.

For design details, see [the design doc](designs/dial_prompts_as_skills.md).

---

## DIAL Skill Resources

DIAL Core stores skills as **folder-shaped resources**: a mandatory `SKILL.md` plus an arbitrary file
hierarchy, served through the `/v2/skills` API. Unlike a DIAL prompt, such a skill can bundle the
reference material its manifest points at, and the agent reads those files **on demand**.

### Configuration

```json
{
  "skills": [
    {
      "type": "dial-skill",
      "url": "skills/<bucket>/<path>"
    }
  ]
}
```

The `url` is a relative path including the `skills/` resource type prefix
(e.g. `skills/my-bucket/refund-policy`), following the same convention as `dial-prompt` and file
context URLs.

### Progressive Disclosure

At request time QuickApps reads the skill's `SKILL.md` and lists its bundled files. The file list is
appended to the manifest as a `<skill_files>` block, so the agent sees it the moment it calls
`read_skill`:

```markdown
---
name: refund-policy
description: How to handle refund requests, by region.
---

# Refund Policy

Determine the customer's region, then read the matching reference file.

<skill_files>
references/eu-rules.md
references/us-rules.md
</skill_files>
```

The agent then opens one with `read_skill(skill_name="refund-policy", file_path="references/eu-rules.md")`
— one request to DIAL Core per file, and only for files it actually asks for. Repeat reads within a
request are served from memory.

A path is readable **only if it appears in that skill's `<skill_files>` block**. Anything else — a
traversal attempt, a hidden file, a path the model invented — is refused, and the error hands the
inventory back so the agent can correct itself.

### Which Files Are Advertised

A bundled file is listed and readable when it is a regular file whose extension is one of
`.md`, `.markdown`, `.txt`, `.json`, `.yaml`, `.yml`, `.csv`, `.tsv`, `.xml`, `.html`, `.toml`,
`.ini`, `.sql`, `.py`, `.sh`, `.js`, `.ts`.

Excluded: subfolders, hidden entries at any depth (including Core's own `.dial-resource` marker),
`SKILL.md` itself (already returned by `read_skill` without a `file_path`), and everything binary —
images, PDFs and other assets are **not** available in this release.

### Limits

| Variable | Default | Purpose |
|---|---|---|
| `DIAL_SKILLS_FILE_MAX_BYTES` | `262144` | Cap on a single file read, `SKILL.md` included. |
| `DIAL_SKILLS_MAX_FILES` | `200` | Maximum files advertised per skill. |
| `DIAL_SKILLS_LISTING_MAX_PAGES` | `10` | Maximum listing pages followed per skill. |

An over-cap `SKILL.md` drops the skill; an over-cap bundled file fails that one read. Files must be
valid UTF-8.

### Name Collision

Precedence is **predefined > dial-prompt > dial-skill**, and first configured wins within a source.
A skill that loses a collision is skipped and reported in the initialization issues stage.

### Error Handling

- **Inaccessible skill** (403, 404): skipped with a reported reason; other skills stay available.
- **Invalid `SKILL.md`**: skipped, same as a DIAL prompt skill.
- **File listing fails**: the skill is still loaded, without its bundled files, and a warning is
  reported.
- **DIAL Core outage**: all DIAL skills are dropped and the request is served with the remaining
  sources.

### Limitations

- **Access**: DIAL Core does not yet auto-share config-declared skills to the application's
  per-request key. A `dial-skill` therefore resolves only when the caller's own key already has
  access — a skill in the user's own bucket, one shared with them, or a published one.
- Skills are fetched fresh on each request (no cross-request caching).
- Binary and asset files are not readable.
- Validation of a `dial-skill` URL is not offered by `/skills/validate`: DIAL Core validates
  `SKILL.md` when the skill is written, so a stored skill is already valid.

For design details, see [the design doc](designs/skills_as_dial_resource.md).

---

## Migrating from Agent Instructions

The `config/predefined/instructions/` directory convention and `AgentInstructionsProvider` have been removed. The skills
framework is their replacement.

Previously, `.md` files placed in `config/predefined/instructions/` were concatenated in filename order and appended to
the system prompt. Skills differ in several ways:

- Each skill lives in its own directory with a `SKILL.md` file containing YAML frontmatter.
- Skills are not concatenated into the system prompt directly. Instead, their metadata (name, description) appears as
  an `<available_skills>` XML block, and the agent reads full content on demand via the `read_skill` tool.
- Skills support metadata fields (`license`, `compatibility`, `allowed-tools`) that instructions did not have.

### Migration steps

1. For each `.md` file in `config/predefined/instructions/`, create a skill directory:

   ```
   # Before
   config/predefined/instructions/my-guidelines.md

   # After
   config/predefined/skills/my-guidelines/SKILL.md
   ```

2. Add YAML frontmatter to the top of each `SKILL.md`:

   ```yaml
   ---
   name: my-guidelines
   description: Brief description of what these guidelines cover
   ---
   ```

   The `name` must match the directory name. The `description` should help the agent decide when to read the skill.

3. Remove the `config/predefined/instructions/` directory.

4. If you were using `PREDEFINED_BASE_PATH` to point to a custom instructions directory, switch to
   `PREDEFINED_EXTRA_PATHS` (see [README](../README.md) for details).
