---
name: tool-call-file-parameter-formatting
description: Formats file and URL parameters for tool calls. You must analyze the target tool's parameter names and descriptions to choose the correct format (data URI, base64, text, or URL ref).
metadata:
  version: "1.2"
---

# File Parameter Formatting

## Purpose
Standardize file and URL inputs for tool calls using the `file:{prefix}::{path_or_url}` schema. You must determine the correct prefix by strictly analyzing the target tool's parameter definition.

## Instructions

When a tool parameter requires a file or URL, follow this process:

### 1. Analyze Tool Parameter Definition
Inspect the **Parameter Name** and **Parameter Description** in the tool definition to determine the requirement:

*   **Requirement: Inline file content (default)**
    *   *Clues:* Description mentions "content," "base64," "encoded," "file data," `data:` URI, RFC 2397, or a URI that accepts schemes including `data:` (e.g. `http:`, `https:`, `file:`, or `data:`).
    *   *Action:* Use `data` prefix (RFC 2397 data URI). Prefer this over plain `base64` for first attempts.
*   **Requirement: Plain Text**
    *   *Purpose:* Use this mode when the tool expects the actual text file content as the parameter. When a file is marked with the `text` prefix, the tool-call processor will read the file's contents and pass that text as the tool call parameter.
    *   *Clues:* Description mentions "text", "string content" (and does **not** ask for a URI or encoded bytes).
    *   *Action:* Use `text` prefix.
*   **Requirement: URL/Path Reference only**
    *   *Clues:* Parameter is a navigation target or path reference with **no** inline-content / `data:` scheme support (e.g. "URL to navigate to", "pass the link").
    *   *Action:* Use `url` prefix.
    *   *Do not* map bare names like `uri` to `url` when the description says the value may be a `data:` URI — use `data` instead.

> **Rule — a parameter that names URLs takes `url`, never inline content.** If the parameter name says URL,
> path, or link (`attachment_urls`, `file_url`, `source_url`, `image_urls`), the receiving side fetches the
> reference itself; it has no use for content pasted into the field. Always use `file:url::` or the bare
> DIAL path there, never `data`, `base64`, or `text` — including when the description also mentions the
> files being "ingested," "read," or "processed." This rule takes precedence over the inline-content default
> above.

### 2. Format the Value
Construct the string using the format: `file:{prefix}::{path_or_url}`

*   **Prefix:** One of `data`, `base64`, `text`, or `url` (determined from step 1)
*   **Separator:** Always use `::`
*   **Path:**
    *   For system files: `files/path/to/file.ext`
    *   For web resources: `https://example.com/resource`

### 3. MCP / tool failure fallback
If a tool call that used `file:data::...` fails (MCP communication error, rejection, or the tool cannot consume a data URI), retry the **same** call once with `file:base64::...` (plain base64, no `data:` envelope). Do not keep retrying `data` blindly.

## Thinking Process
Before executing the tool call, perform this check:

1.  **Inspect Definition:** "I am calling tool `[tool_name]`. The parameter `[param_name]` has the description: `[description]`."
2.  **Deduce Type:** "Based on the name/description, this tool expects [inline content | text string | URL reference]."
3.  **Apply Format:** "Therefore, I will use the `[data | text | url]` prefix (default `data` for content; `base64` only as fallback after failure)."

## Examples

### Example 1: Visual Analysis Tool
*   **Tool Definition:**
    *   `name`: `analyze_image`
    *   `parameter`: `image_data`
    *   `description`: "The base64 encoded contents of the image file."
*   **Reasoning:** Description asks for encoded contents — default to RFC 2397 data URI.
*   **Result:** `file:data::files/images/chart.png`

### Example 2: Browser Tool
*   **Tool Definition:**
    *   `name`: `web_browser`
    *   `parameter`: `target_url`
    *   `description`: "The URL to navigate to."
*   **Reasoning:** Parameter name is `target_url` and expects a navigation link (no inline content).
*   **Result:** `file:url::https://google.com`

### Example 3: Code Reader
*   **Tool Definition:**
    *   `name`: `read_script`
    *   `parameter`: `script_content`
    *   `description`: "The text content of the python script."
*   **Reasoning:** Description asks for "text content."
*   **Result:** `file:text::files/scripts/main.py`

### Example 4: Format Hint in Tool Name
*   **Tool Definition:**
    *   `name`: `base64_image_processor`
    *   `parameter`: `image_input`
    *   `description`: "Image to process."
*   **Reasoning:** Tool name mentions "base64," indicating encoded content — still prefer `data` first.
*   **Result:** `file:data::files/photos/portrait.jpg`

### Example 5: Format Hint in Tool Description
*   **Tool Definition:**
    *   `name`: `document_analyzer`
    *   `description`: "Analyzes documents by reading their text content directly."
    *   `parameter`: `document`
    *   `description`: "Document to analyze."
*   **Reasoning:** Tool description mentions "reading text content directly," suggesting text mode.
*   **Result:** `file:text::files/reports/annual_report.txt`

### Example 6: Format Hint in Argument Name
*   **Tool Definition:**
    *   `name`: `fetch_resource`
    *   `parameter`: `resource_url`
    *   `description`: "The resource to fetch."
*   **Reasoning:** Parameter name ends with `_url`, indicating a URL reference is expected.
*   **Result:** `file:url::https://api.example.com/data.json`

### Example 7: Document bytes / encoded file data
*   **Tool Definition:**
    *   `name`: `process_file`
    *   `parameter`: `input_file`
    *   `description`: "Pass the base64-encoded file data for processing."
*   **Reasoning:** Description asks for encoded file data — default to `data`.
*   **Result:** `file:data::files/uploads/document.pdf`

### Example 8: Multi-scheme URI (MarkItDown-style)
*   **Tool Definition:**
    *   `name`: `convert_to_markdown`
    *   `parameter`: `uri`
    *   `description`: "Convert a resource described by an http:, https:, file: or data: URI to markdown."
*   **Reasoning:** Description explicitly supports `data:` URIs; do **not** use `url` for an uploaded file.
*   **Result:** `file:data::files/uploads/report.docx`

### Example 9: Multi-file upload tool (array parameter, inline content)
*   **Tool Definition:**
    *   `name`: `batch_processor`
    *   `parameter`: `documents` (type: array of strings)
    *   `description`: "List of base64-encoded file contents."
*   **Reasoning:** Description asks for encoded file contents for each element — default to `data`.
*   **Result:** `["file:data::files/doc1.pdf", "file:data::files/doc2.pdf"]`

### Example 10: Multi-file upload tool (array parameter, URL references)
*   **Tool Definition:**
*  `name`: `rag`
    *   `parameter`: `attachment_urls` (type: array of strings)
    *   `description`: "List of URLs pointing to the files to be ingested."
*   **Reasoning:** Name `attachment_urls` and description "URLs pointing to the files" indicate URL references for each element. The URL-reference rule applies whether the file lives in DIAL or on the web.
*   **Result:** `["file:url::https://example.com/doc1.pdf", "file:url::https://example.com/doc2.pdf"]`
*   **Uploaded file:** `["file:url::files/uploads/report.docx"]` — *not* `file:data::`, even though the description says the files are "ingested."

### Example 11: Fallback after MCP failure
*   **First attempt:** `file:data::files/uploads/document.pdf` → MCP tool call fails.
*   **Retry:** `file:base64::files/uploads/document.pdf` (plain base64 payload).

> **Note:** The `file:{prefix}::` format works for both single string parameters and individual elements within array parameters.

## Common Mistakes
*   ❌ Ignoring the tool description and defaulting to `url` for local files that need content.
*   ❌ Mapping a parameter named `uri` to `url` when the description allows `data:` URIs — use `data`.
*   ❌ Passing `file:base64::...` on the first attempt when `file:data::...` is the default for content.
*   ❌ After a failed `file:data::...` MCP call, retrying `data` again instead of falling back to `file:base64::...`.
*   ❌ Passing raw paths (`files/doc.pdf`) without the `file:...` schema.
*   ❌ Using `data`/`base64`/`text` on a parameter whose name says URL or path (`attachment_urls`) — it takes `url`.

## External URL Fallback

External `https://` URLs are valid file references — `attachment_urls` accepts them, and `file:data::https://...`
/ `file:base64::https://...` / `file:text::https://...` will inline external content. They may fail with a clear
error when the operator has disabled external egress (`EXTERNAL_URL_FETCH_ENABLED=false`) or the per-app config
has opted out (`features.external_url_fetch.enabled: false`). When that happens:

*   For `file:data::https://...`, `file:base64::https://...`, and `file:text::https://...`, retry by asking the
    user to upload the file to DIAL and re-issue the call with `files/...` instead.
*   For deployment-tool `attachment_urls`, the same call may still succeed against a deployment that supports
    `features.url_attachments` (the URL is forwarded as a `reference_url` and the deployment fetches the bytes
    itself, never via QuickApps).
