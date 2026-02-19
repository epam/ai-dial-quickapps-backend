---
name: tool-call-file-parameter-formatting
description: Formats file and URL parameters for tool calls. You must analyze the target tool's parameter names and descriptions to choose the correct format (base64, text, or URL ref).
metadata:
  version: "1.3"
---

# File Parameter Formatting

## Purpose
Standardize file and URL inputs for tool calls using the `file:{prefix}::{path_or_url}` schema. You must determine the correct prefix by strictly analyzing the target tool's parameter definition.

## Instructions

When a tool parameter requires a file or URL, follow this process:

### 1. Analyze Tool Parameter Definition
Inspect the **Parameter Name** and **Parameter Description** in the tool definition to determine the requirement:

*   **Requirement: Base64 Content**
    *   *Clues:* Description mentions "content," "base64," "encoded," "file data," or the tool processes media (images/audio).
    *   *Action:* Use `base64` prefix.
*   **Requirement: Plain Text**
    *   *Clues:* Description mentions "text," "string content," "read file," or the file type is code/markdown/logs.
    *   *Action:* Use `text` prefix.
*   **Requirement: URL/Path Reference**
    *   *Clues:* Parameter name contains `url`, `link`, `uri`, or description says "pass the link" or "reference."
    *   *Action:* Use `url` prefix.

### 2. Format the Value
Construct the string using the format: `file:{prefix}::{path_or_url}`

*   **Separator:** Always use `::`
*   **Path:**
    *   For system files: `files/path/to/file.ext`
    *   For web resources: `https://example.com/resource`

## Thinking Process
Before executing the tool call, perform this check:

1.  **Inspect Definition:** "I am calling tool `[tool_name]`. The parameter `[param_name]` has the description: `[description]`."
2.  **Deduce Type:** "Based on the name/description, this tool expects [raw content | text string | URL reference]."
3.  **Apply Format:** "Therefore, I will use the `[base64 | text | url]` prefix."

## Examples

### Example 1: Visual Analysis Tool
*   **Tool Definition:**
    *   `name`: `analyze_image`
    *   `parameter`: `image_data`
    *   `description`: "The base64 encoded contents of the image file."
*   **Reasoning:** Description explicitly asks for "encoded contents."
*   **Result:** `file:base64::files/images/chart.png`

### Example 2: Browser Tool
*   **Tool Definition:**
    *   `name`: `web_browser`
    *   `parameter`: `target_url`
    *   `description`: "The URL to navigate to."
*   **Reasoning:** Parameter name is `target_url` and expects a navigation link.
*   **Result:** `file:url::https://google.com`

### Example 3: Code Reader
*   **Tool Definition:**
    *   `name`: `read_script`
    *   `parameter`: `script_content`
    *   `description`: "The text content of the python script."
*   **Reasoning:** Description asks for "text content."
*   **Result:** `file:text::files/scripts/main.py`

## Common Mistakes
*   ❌ Ignoring the tool description and defaulting to `url` for local files.
*   ❌ Passing `file:base64::...` to a tool that only asks for a URL string (parameter name `url`).
*   ❌ Passing raw paths (`files/doc.pdf`) without the `file:...` schema.