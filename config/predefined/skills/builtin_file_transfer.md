---
name: file-parameter-formatting
description: Format file and URL parameters correctly when calling tools
metadata:
  version: "1.0"
---

# File Parameter Formatting

## Description

When calling tools that accept file or URL parameters, you must use a specific format to ensure proper file handling and encoding. This skill teaches you how to correctly format file parameters using the `file:{prefix}::{path_or_url}` pattern.

## Instructions

For any tool parameter that accepts a file or URL, you **must** use this format:

```
file:{prefix}::{path_or_url}
```

### Components:
- **Prefixes** (lowercase): 
  - `base64` - File content will be fetched and base64-encoded
  - `url` - Pass URL/URI reference as-is without fetching
  - `text` - File content will be fetched as plain text
- **Path/URL**: 
  - System files use `files/...` (e.g. `files/uploads/doc.pdf`)
  - External URLs use full `https://...`
- **Separator**: Always use double colon `::`

### Step-by-step process:
1. **Identify param type**: Does the parameter expect base64-encoded content, a URL/URI reference, or plain text from a file? (Check param name and description.)
2. **Choose prefix**: 
   - base64 → `base64`
   - URL/URI reference → `url`
   - plain text from file → `text`
3. **Build value**: Combine as `file:{prefix}::{path_or_url}`. Use `files/...` for system/attachment paths, `https://...` for external URLs.

### Important rules:
- Never use raw paths, raw URLs, or placeholders like `{{file_1}}`
- **Never** pass raw base64 or data URIs (e.g. `data:audio/wav;base64,UklGR...`). Use `file:base64::{path_or_url}` instead; the system will fetch and encode the file.

## Examples

**Wrong** → **Right**:
- `files/docs/report.pdf` → `file:base64::files/docs/report.pdf` or `file:url::files/docs/report.pdf`
- `https://example.com/img.png` → `file:url::https://example.com/img.png`

**Correct examples**:
- `file:base64::files/reports/Q4.pdf` - Base64-encoded PDF
- `file:url::https://cdn.com/photo.jpg` - External image URL
- `file:text::files/data/notes.txt` - Plain text file content
