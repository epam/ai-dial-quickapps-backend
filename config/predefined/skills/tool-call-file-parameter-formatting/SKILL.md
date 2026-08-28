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

### 1. Decide first: content or reference?

Inspect the **Parameter Name** and **Parameter Description**, and answer one question before
choosing any prefix: **does the tool want the file's bytes, or a locator it resolves itself?**

*   **Requirement: URL/Path reference — the tool resolves the location itself**
    *   *Clues:* The parameter names a location — a URL, URI, link, path, or attachment
        reference — and the description does **not** offer to accept inline content.
        A parameter name containing `url`, `urls`, `uri`, `link`, `path`, or `href` is a
        reference by default.
    *   *Action:* Use the `url` prefix, then go to step 2.
*   **Requirement: Inline file content**
    *   *Clues:* Description mentions "content," "base64," "encoded," "file data," `data:` URI,
        RFC 2397, or a URI that accepts schemes including `data:` (e.g. `http:`, `https:`,
        `file:`, or `data:`).
    *   *Action:* Pick the content prefix in step 1b.

An explicit description always overrides the name: a parameter called `uri` whose description
lists `data:` among its accepted schemes wants content, not a reference (Example 8).

**When the parameter gives no clear signal either way, use `url`.** The two mistakes do not cost
the same — a reference the tool rejects is one cheap, retryable error, while an inlined file the
tool never wanted is a multi-megabyte payload in the conversation that cannot be taken back.

### 1a. `attachment_urls` is always a reference

`attachment_urls` accepts **only** `file:url::` references — a DIAL file path
(`file:url::files/bucket/report.pdf`) or an external URL
(`file:url::https://example.com/report.pdf`). This holds for files the user just uploaded: pass
the path as a reference, never as inlined bytes. `file:data::`, `file:base64::`, and
`file:text::` are not valid here and will be rejected.

### 1b. If the parameter wants content, pick the content prefix

*   **Encoded bytes (default for content):** Use the `data` prefix (RFC 2397 data URI). Prefer
    this over plain `base64` for first attempts.
*   **Plain text:** Use the `text` prefix when the tool expects the actual text file content as
    the parameter — the description mentions "text" or "string content" and does **not** ask for
    a URI or encoded bytes. When a file is marked with the `text` prefix, the tool-call processor
    will read the file's contents and pass that text as the tool call parameter.

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
2.  **Content or reference:** "Does this parameter want the file's bytes, or a locator? The name suggests [...]; the description suggests [...]. If neither is clear, it is a reference."
3.  **Apply Format:** "Therefore, I will use the `[url | data | text]` prefix (`data` is the default only once content is established; `base64` only as a fallback after a failed `data` call)."

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
*   **Reasoning:** Description explicitly supports `data:` URIs, which overrides the reference-shaped name; do **not** use `url` for an uploaded file.
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
*   **Reasoning:** Name `attachment_urls` and description "URLs pointing to the files" indicate URL references for each element.
*   **Result:** `["file:url::https://example.com/doc1.pdf", "file:url::https://example.com/doc2.pdf"]`

### Example 10a: `attachment_urls` with an uploaded DIAL file
*   **Tool Definition:**
    *   `name`: `rag`
    *   `parameter`: `attachment_urls` (type: array of strings)
    *   `description`: "The list of attachment urls related to tool call."
*   **Context:** The user uploaded `files/bucket/report.pdf` in this conversation.
*   **Reasoning:** `attachment_urls` is reference-only (step 1a). A DIAL path is passed as a reference; the tool resolves it itself. Inlining the bytes here would be rejected.
*   **Result:** `["file:url::files/bucket/report.pdf"]`

### Example 11: Fallback after MCP failure
*   **First attempt:** `file:data::files/uploads/document.pdf` → MCP tool call fails.
*   **Retry:** `file:base64::files/uploads/document.pdf` (plain base64 payload).

> **Note:** The `file:{prefix}::` format works for both single string parameters and individual elements within array parameters.

## Common Mistakes
*   ❌ Reaching for `data` before deciding whether the parameter wants content at all — the content/reference question comes first.
*   ❌ Inlining a file into a parameter that names a URL or attachment reference; `file:data::` into `attachment_urls` sends a `data:` URI the tool cannot resolve.
*   ❌ Ignoring the tool description and defaulting to `url` for local files that need content.
*   ❌ Mapping a parameter named `uri` to `url` when the description allows `data:` URIs — use `data`.
*   ❌ Passing `file:base64::...` on the first attempt when `file:data::...` is the default for content.
*   ❌ After a failed `file:data::...` MCP call, retrying `data` again instead of falling back to `file:base64::...`.
*   ❌ Passing raw paths (`files/doc.pdf`) without the `file:...` schema.

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
