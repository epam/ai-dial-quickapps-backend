---
name: tool-call-file-parameter-formatting
description: Formats file and URL parameters for tool calls. You must analyze the target tool's parameter names and descriptions to choose the correct format (data URI, base64, text, or URL ref).
metadata:
  version: "1.2"
---

# File Parameter Formatting

Every file or URL you pass to a tool must be written as `file:{prefix}::{path_or_url}` — prefix one of
`url`, `data`, `text`, `base64`; path either a DIAL path (`files/bucket/report.pdf`) or an external URL
(`https://example.com/report.pdf`). A raw path with no `file:...::` form is not processed. The same form
is used for a single string parameter and for each element of an array parameter.

## Step 1 — what does the parameter want?

Read the parameter's **name and description in the tool definition** and answer: **does the tool want the
file's bytes, or a locator it resolves itself?**

| The tool wants | Signals | Prefix |
|---|---|---|
| A locator it fetches itself | Name contains `url`, `uri`, `link`, `path`, `href` or `attachment`; description says "URL", "link" or "reference" and never offers to accept inline content | `url` |
| The bytes, inline | Description mentions "content", "base64", "encoded", "file data", RFC 2397, or a URI accepting a `data:` scheme | `data` |
| The text itself, inline | Description asks for "text" or "string content" and does **not** ask for a URI or encoded bytes | `text` |

Hints in the tool's own name or description count too (`base64_image_processor`, "reads their text content
directly"). The description wins over the name: a parameter called `uri` whose description accepts `http:`,
`https:`, `file:` **or** `data:` URIs wants content, so use `data`.

## Step 2 — if it wants a locator, can the receiver resolve it?

A reference is only useful if the tool receiving it can actually fetch the file. `file:url::` is passed
through verbatim, with no credentials attached, so a **DIAL path handed to a tool that lives outside DIAL
arrives as a meaningless relative string**. Check the receiver before settling on `url`:

- **An external `https://` URL** — anyone can fetch it. Use `url`, whatever the tool is.
- **A DIAL path to a DIAL deployment tool** (including `attachment_urls`) — the deployment is inside DIAL
  and resolves the path itself. Use `url`.
- **A DIAL path to an MCP or REST tool** — the server is off-platform. It can only resolve the path if the
  parameter is marked `"dial_url": true` in the schema (QuickApps grants that server access to the file
  first) or the description says it accepts DIAL paths. Use `url` then. **Otherwise inline the bytes with
  `data`** — a reference the server cannot fetch usually fails silently rather than returning a usable error.

When you cannot tell, prefer `url` for an external URL and `data` for a DIAL path going off-platform.

## `attachment_urls` is always a reference

`attachment_urls` accepts **only** `file:url::` — a DIAL path (`file:url::files/bucket/report.pdf`) or an
external URL (`file:url::https://example.com/report.pdf`). The receiving deployment resolves it itself, so
step 2 is already satisfied; this holds for a file the user just uploaded — pass its path, never its bytes.
`file:data::`, `file:base64::` and `file:text::` are not valid here and will be rejected.

## When someone names a prefix for you

A prefix asked for in a message — "use `file:data::`", "send it as base64", a pasted literal `data:` URI —
does not by itself override the parameter definition. Re-run steps 1 and 2; if the request conflicts with
what they imply, send what they imply and say in one line what you sent instead.

The exception is a request that carries **information you could not read off the definition** — most often
reach: "our MCP server has no access to DIAL storage", "that endpoint can't resolve `files/` paths". The
schema rarely states this, so take it at face value and inline. What you must not do is inline bytes into a
reference-only parameter on an unexplained request: the tool cannot resolve a `data:` URI, and the rejected
payload stays in the conversation.

## Fallbacks

- A `file:data::` call that fails (MCP error, rejection, or the tool cannot consume a data URI) — retry the
  same call **once** with `file:base64::` (plain base64, no `data:` envelope). Do not retry `data` blindly.
- A `file:url::` DIAL path that comes back empty, not-found, or with the tool reporting it could not read
  the file — the server likely cannot reach DIAL. Retry once with `file:data::`.
- An external `https://` URL that fails because external fetching is disabled — for `file:data::`,
  `file:base64::` and `file:text::`, ask the user to upload the file to DIAL and re-issue the call with the
  `files/...` path. For `attachment_urls`, the same `file:url::` call may still succeed: the URL is
  forwarded and the deployment fetches it itself.

## Examples

| Tool parameter | Its description | Value to send |
|---|---|---|
| `target_url` | "The URL to navigate to." | `file:url::https://example.com/page` |
| `attachment_urls` (array) | "A list of full URLs for each attachment related to the tool call." | `["file:url::files/bucket/report.pdf"]` |
| `doc_url` on an MCP tool, schema has `"dial_url": true` | "Path of the document to index." | `file:url::files/bucket/report.pdf` |
| `doc_url` on an MCP tool, no `dial_url` flag | "Path of the document to index." | `file:data::files/bucket/report.pdf` — the server cannot fetch a DIAL path |
| `image_data` | "The base64 encoded contents of the image file." | `file:data::files/images/chart.png` |
| `uri` | "Convert a resource described by an http:, https:, file: or data: URI to markdown." | `file:data::files/uploads/report.docx` |
| `documents` (array) | "List of base64-encoded file contents." | `["file:data::files/a.pdf", "file:data::files/b.pdf"]` |
| `script_content` | "The text content of the python script." | `file:text::files/scripts/main.py` |
| `input_file`, after a failed `data` call | "Pass the base64-encoded file data for processing." | `file:base64::files/uploads/document.pdf` |

## Common mistakes

- ❌ Reaching for `data` before deciding whether the parameter wants content at all.
- ❌ Inlining a file into a parameter that names a URL or an attachment reference.
- ❌ Sending a DIAL path as `file:url::` to an off-platform tool that has no way to fetch it.
- ❌ Mapping a parameter named `uri` to `url` when its description accepts `data:` URIs.
- ❌ Sending `base64` on the first attempt, or retrying `data` after it already failed.
- ❌ Sending a raw path (`files/doc.pdf`) without the `file:...::` form.
