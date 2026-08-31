# Agent Skills

Agent skills are reusable instruction modules that enhance agent capabilities. Skills follow the
[Agent Skills](https://agentskills.io/) open standard and are defined as Markdown files with YAML frontmatter inside
named directories. They are automatically loaded and made available to the agent at runtime.

> [!NOTE]
> Quick Apps implements a subset of the [Agent Skills specification](https://agentskills.io/specification). See
> [Supported vs unsupported features](#supported-vs-unsupported-features) below for details.

## How Skills Work

- Skills come from two places: **predefined** skills loaded from `config/predefined/skills/` at startup, and
  **DIAL skill resources** referenced per app in its config. Both present the same model to the agent.
- Each skill is presented to the agent as XML metadata in the system prompt — name and description only, never
  its file tree.
- The agent reads a skill's instructions on demand with the internal `read_skill` tool, which also tells it which
  files the skill bundles.
- The agent reads one of those bundled files by calling `read_skill` again with `file_path` — this is
  *progressive disclosure*: a short manifest plus detail fetched only when it is actually needed.
- Bundled files are currently served by **DIAL skill resources** only. A predefined skill is its `SKILL.md`:
  anything else in its directory is ignored, and it reports an empty file inventory.
- Skills support metadata including name, description, license, compatibility, and allowed tools.
- Extra skill directories can be layered via `PREDEFINED_EXTRA_PATHS` (see [README](../README.md) for env var details).

## Directory Layout

A skill is a directory. `SKILL.md` is required at its root. For a DIAL skill resource anything alongside it is
offered to the agent on demand; for a predefined skill only `SKILL.md` is read today.

A DIAL skill resource:

```
skills/<bucket>/my-skill/
├── SKILL.md
├── references/
│   └── api-schema.md
├── scripts/
│   └── validate.py
└── assets/
    └── template.csv
```

A predefined skill — anything beside `SKILL.md` is ignored today:

```
config/predefined/skills/
└── my-skill/
    └── SKILL.md
```

The directory name **should** match the `name` field in the YAML frontmatter. A mismatch is logged as a warning
and the skill still loads, keyed by its frontmatter `name` — that is the name the agent sees and passes to
`read_skill`.

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
| Directory-based layout (`skill-name/SKILL.md`) | Supported | A directory name that differs from the frontmatter `name` is warned about, not rejected; the skill is keyed by its frontmatter `name`. |
| `name` validation (length, charset, consecutive hyphens) | Supported | |
| `description`, `license`, `compatibility`, `metadata` | Supported | |
| `allowed-tools` | Partial | Exposed in XML metadata but **not enforced** at runtime. |
| Optional subdirectories (`scripts/`, `references/`, `assets/`) | Partial | Readable on demand via `read_skill(skill_name, file_path)` for DIAL skill resources. Predefined skills expose `SKILL.md` only. |
| Progressive disclosure (on-demand file references) | Supported | A manifest read lists the skill's bundled files; the agent fetches one at a time by path. |
| Binary bundled files | Partial | They appear in the file inventory, but `read_skill` refuses to return non-UTF-8 content rather than emit mojibake. |
| Dynamic skill registration | Partial | Predefined skills load once at startup and need a restart. DIAL skill resources are resolved per request, so editing one takes effect on the next message. |

For the full specification, see [agentskills.io/specification](https://agentskills.io/specification).
For design rationale and known limitations, see [the design doc](designs/skills_and_file_transfer.md).

## DIAL Skill Resources

Beyond the skills bundled into the image, users can reference **DIAL skill resources** — folder-shaped
resources stored in DIAL Core under `skills/<bucket>/<path>`. Unlike a prompt, a skill resource is a real
directory: it holds `SKILL.md` plus whatever `references/`, `scripts/`, or `assets/` the author bundles, and it
is shared and published as a unit.

> [!NOTE]
> `dial-skill` is a **preview feature** — the config variant is stripped from the published schema and its
> entries are dropped at runtime unless `ENABLE_PREVIEW_FEATURES=true`.

### Configuration

```json
{
  "skills": [
    {
      "type": "dial-skill",
      "url": "skills/<bucket>/<folder>/<skill-name>"
    }
  ]
}
```

The `url` addresses the skill **as a unit** — never a file inside it, never a grouping folder. It includes the
`skills/` resource-type prefix, following the same convention as `files/<bucket>/...` and
`prompts/<bucket>/...`. A URL with a trailing slash, a `files/` segment, or a missing `skills/` prefix is
reported in the *Initialization issues* stage and the skill is skipped; the request is still served.

### What the agent sees

At initialization QuickApps fetches the skill's `SKILL.md` and lists its files — two small requests, no
whole-archive download. Reading a bundled file later costs exactly one more request.

`read_skill("refund-policy")` returns the manifest followed by an inventory:

```
<skill_files>
references/refund-matrix.md
scripts/validate_claim.py
</skill_files>
```

`read_skill("refund-policy", "references/refund-matrix.md")` returns that file's text.

### Limits

| Setting | Env var | Default | Bounds |
|---|---|---|---|
| File size | `SKILLS_FILE_MAX_BYTES` | 40000 | Any single skill file returned to the agent, `SKILL.md` included. Over the limit the read is **refused**, not truncated. |
| Inventory size | `SKILLS_INVENTORY_MAX_ENTRIES` | 200 | How many bundled files are listed — and, for DIAL skills, how many are fetched. A truncated inventory says so. |
| Configured skills | `DIAL_SKILLS_MAX_CONFIGURED_SKILLS` | 20 | Unique `dial-skill` URLs resolved per request. Repeating a URL costs one slot; each URL beyond the cap is reported and skipped. |

These sit *inside* DIAL Core's own per-resource limits, so a skill Core stores happily can still exceed what
QuickApps is willing to spend context on.

### Known gap

A skill declared in an app config is not yet auto-shared to the app's per-request key — DIAL Core's
referenced-resource collector does not accept `skills/` URLs. Until that lands, a skill the app cannot already
read returns 403 and is reported in the *Initialization issues* stage.

For design details, see [the design doc](designs/skills_as_dial_resource.md).

---

## DIAL Prompt Skills

> [!NOTE]
> Prefer `dial-skill` for new configurations — a prompt cannot carry bundled files. Migration is two steps you
> can perform without QuickApps' involvement: create a skill resource whose `SKILL.md` is the prompt's body, then
> swap the entry's `type` to `dial-skill` and its `url` to `skills/<bucket>/<path>`. The frontmatter contract is
> identical on both sides, so a prompt that works as a skill today transfers unchanged.

Skills sourced from **DIAL prompts** — text content stored via the DIAL Core prompts API (`/v1/prompts/`). A DIAL
prompt whose content follows the Agent Skills specification (valid YAML frontmatter with `name` and
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

Precedence spans every source, and is owned in one place:

1. A **predefined** skill wins over anything configured.
2. Among configured skills — `dial-skill` and `dial-prompt` alike — the one appearing **earliest in the
   `skills` array** wins.
3. Every loser is reported in the *Initialization issues* stage with its URL, so a shadowed skill is never
   silently absent.

The one deliberately silent case is the same URL configured twice: the skill is still there, only the
redundant entry is gone.

### Error Handling

- **Invalid prompt**: Skipped with a warning. Other skills remain available.
- **Inaccessible prompt** (404, 403): Skipped with a warning. The request is served with remaining skills.
- **DIAL Core outage**: Falls back to predefined-only skills. A DIAL Core failure never prevents
  the request from being served.

### Limitations

- DIAL prompts are single text documents — they cannot contain `scripts/`, `references/`, or `assets/`
  subdirectories, so `read_skill` with a `file_path` always fails for them. Use `dial-skill` when a skill needs
  bundled files.
- DIAL prompts are fetched fresh on each request (no cross-request caching).

For design details, see [the design doc](designs/dial_prompts_as_skills.md).

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

   The `name` should match the directory name — a mismatch is warned about and the skill still loads, keyed by the
   frontmatter `name`. The `description` should help the agent decide when to read the skill.

3. Remove the `config/predefined/instructions/` directory.

4. If you were using `PREDEFINED_BASE_PATH` to point to a custom instructions directory, switch to
   `PREDEFINED_EXTRA_PATHS` (see [README](../README.md) for details).
