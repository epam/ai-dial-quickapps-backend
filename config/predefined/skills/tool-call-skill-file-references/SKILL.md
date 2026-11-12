---
name: tool-call-skill-file-references
description: Passes a file bundled with a skill (typically a script) to a tool without retyping it. Use whenever a skill's instructions say to run, send, or hand a bundled file to a tool, by writing it as a skill reference behind a file prefix.
metadata:
  version: "1.0"
---

# Skill File References

A skill's `<skill_files>` block lists its bundled files as ready-to-copy references:
`skill://<skill_name>/<path>`. To give such a file to a tool, put that reference behind a `file:` prefix.
QuickApps delivers the file byte-for-byte; **never read a bundled script and retype it into a tool
argument** — it costs tokens and risks altering code the skill author tested.

A bare `skill://...` value, or a bare path, is not a valid file argument. Always write `file:{prefix}::skill://<skill_name>/<path>`.

## Which prefix

Choose by what the tool parameter wants, using the rules of `tool-call-file-parameter-formatting`:

| The parameter | Prefix | Why |
|---|---|---|
| An MCP tool parameter marked `"dial_url": true` in its schema | `file:url::` | QuickApps grants the server access to the skill, and the server downloads the file itself. Nothing but the reference passes through you. |
| Takes the code or text itself (`code`, `script`, "the python code to run") | `file:text::` | QuickApps replaces the reference with the file's text before the call. |
| Takes encoded bytes ("base64-encoded contents"), or the server cannot reach DIAL | `file:base64::` (or `file:data::` for a data URI) | The file is delivered inline; the server needs no DIAL access. |

`file:url::` works only for a `dial_url` parameter of an MCP tool registered in DIAL. For any other tool use
`file:text::`, `file:base64::` or `file:data::`.

## Examples

| Tool parameter | Its description | Value to send |
|---|---|---|
| `script_url`, schema has `"dial_url": true` | "Path of the script to run." | `file:url::skill://data-cleanup/scripts/clean.py` |
| `code` | "The python code to run." | `file:text::skill://data-cleanup/scripts/clean.py` |
| `file_contents` | "The base64-encoded file." | `file:base64::skill://data-cleanup/scripts/clean.py` |

## When a reference is rejected

The error names the problem and lists the files the skill does have. Retry with a reference copied from that
list or from the skill's `<skill_files>` block. A skill with no bundled files cannot be referenced this way.

## Running the file

Executing the file is the receiving tool's job. This instruction only covers how to hand the file over.
