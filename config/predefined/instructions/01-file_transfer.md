# File Transfer Instructions for Tool Calls

When creating tool call parameters for file transferring, you MUST ALWAYS construct the file or file data parameter
according to the following rules:

## Base Format

All file parameters must follow this pattern:

```
file:{prefix}::{file_url}
```

## ❌ INCORRECT Examples - Never Use These

- `https://example.com/document.pdf` (raw URL without prefix)
- `files/documents/report.pdf` (raw file path without prefix)
- `document.pdf` (filename only)
- `{{file_1}}` or `{{ref}}` (placeholder references)
- `@file_1` or `@{ref}` (reference notation)
- `(file_1)` or `(ref)` (parenthetical references)
- `/path/to/file.pdf` (local file paths)
- Base64 content directly in parameter (without proper format)

**Critical Rule**: Never reference files with raw URLs, file paths, file names, placeholders, or any reference notation.
Always use the `file:{prefix}::{file_url}` format.

---

## Prefix Types

### 1. Base64 Prefix

- **Use when**: The tool/API specifically requires base64-encoded file content
- **Behavior**: The system will automatically retrieve and encode the file from the URL
- **Result format**: `file:base64::{file_url}`
- **Example**: `file:base64::files/documents/report.pdf`
- **Common use cases**: APIs that accept base64 strings, email attachments, embedded images

### 2. URL Prefix

- **Use when**: The tool/API accepts direct URLs for remote file access
- **Behavior**: The file URL is passed directly; the receiving system fetches the file
- **Result format**: `file:URL::{file_url}`
- **Example**: `file:URL::files/images/chart.png`
- **Common use cases**: Webhook notifications, file download endpoints, external processors

### 3. Text Prefix

- **Use when**: The user attaches a file and requests to call a tool with plain text data from that attachment
- **Behavior**: The system extracts plain text content from the file at the given URL
- **Result format**: `file:text::{file_url}`
- **Example**: `file:text::files/data/content.txt`
- **Common use cases**: Text file processing, document analysis, content extraction from .txt, .md, .csv files

---

## File URL Formats

Your system uses two types of file URLs:

### 1. System Files (Internal Storage)

- **Format**: `files/<file_path>/<file_name>`
- **When to use**: When files are mentioned in context, user attachments, or files stored in the system
- **Examples**:
    - `files/documents/report.pdf`
    - `files/uploads/2024/invoice.xlsx`
    - `files/images/screenshot.png`
    - `files/data/analysis.csv`

### 2. External Files (Web URLs)

- **Format**: `https://domain.com/path/to/file`
- **When to use**: When user explicitly references external web URLs in the conversation
- **Examples**:
    - `https://cdn.com/image.png`
    - `https://example.com/public/document.pdf`
    - `https://storage.googleapis.com/bucket/file.jpg`

---

## Selection Logic

Follow these steps to construct the correct parameter:

1. **Identify the file source**:
    - File in context or user attachment → use `files/<file_path>/<file_name>` format
    - External URL mentioned by user → use the full `https://...` URL

2. **Identify the tool's requirements**: Check what format the tool expects (base64 data, URL reference, or text
   content)

3. **Select the appropriate prefix**:
    - Tool needs encoded content → `base64`
    - Tool accepts URL references → `URL`
    - Tool needs plain text extraction → `text`

4. **Construct the parameter**: `file:{selected_prefix}::{file_url}`

---

## Examples by Scenario

### Scenario 1: System File with Base64 Encoding

**Context**: File `files/reports/Q4_summary.pdf` is mentioned in context  
**Tool requirement**: Needs base64-encoded content  
**Correct parameter**:

```
file:base64::files/reports/Q4_summary.pdf
```

### Scenario 2: External URL with URL Prefix

**User says**: "Process this image https://cdn.example.com/photo.jpg"  
**Tool requirement**: Accepts URL references  
**Correct parameter**:

```
file:URL::https://cdn.example.com/photo.jpg
```

### Scenario 3: User Attachment with Text Extraction

**Context**: User uploads a file, stored as `files/uploads/user123/notes.txt`  
**Tool requirement**: Needs plain text content  
**Correct parameter**:

```
file:text::files/uploads/user123/notes.txt
```

### Scenario 4: System Image File

**Context**: File `files/images/charts/sales_graph.png` in context  
**Tool requirement**: Needs base64 encoding  
**Correct parameter**:

```
file:base64::files/images/charts/sales_graph.png
```

### Scenario 5: External Document

**User says**: "Analyze https://website.com/public/data.csv"  
**Tool requirement**: Needs text extraction  
**Correct parameter**:

```
file:text::https://website.com/public/data.csv
```

---

## User Attachments

When a user attaches a file in the conversation:

- The file is stored in the system with a path like `files/uploads/<user_id>/<filename>`
- Use that system path as `{file_url}` in the format
- Apply the appropriate prefix based on tool requirements
- **Example**: If user uploads "report.pdf" stored as `files/uploads/user456/report.pdf`:
  ```
  file:base64::files/uploads/user456/report.pdf
  ```

---

## Multiple Files

When handling multiple files:

- Create separate parameters for each file
- Each must have its own complete `file:{prefix}::{file_url}` format
- Files can be mix of system paths and external URLs
- **Example**:
  ```json
  {
    "file1": "file:base64::files/documents/doc1.pdf",
    "file2": "file:URL::https://cdn.com/image.png",
    "file3": "file:text::files/data/sheet.csv"
  }
  ```

---

## Important Notes

- **System files**: Always use `files/<path>/<name>` format for files in context or attachments
- **External files**: Use complete `https://...` URLs only when user explicitly references web URLs
- **Prefix case sensitivity**: Use lowercase for `base64` and `text`, uppercase for `URL`
- **No modifications**: Don't modify, shorten, or alter the file path/URL
- **Separator**: Always use double colons `::` between prefix and file path/URL
- **No content insertion**: Never insert actual file content or base64 strings directly—only use the format

---

## Validation Checklist

Before finalizing any file parameter, verify:

- [ ] Starts with `file:`
- [ ] Contains valid prefix (`base64`, `URL`, or `text`)
- [ ] Has double colon separator `::`
- [ ] File path uses correct format:
    - [ ] System files: `files/<path>/<name>`
    - [ ] External files: `https://...`
- [ ] No placeholders, references, or raw paths/URLs used
- [ ] Prefix matches tool requirements

---

## ✅ Correct Examples Summary

| Scenario               | File Source                     | Correct Format                               |
|------------------------|---------------------------------|----------------------------------------------|
| PDF document in system | `files/docs/report.pdf`         | `file:base64::files/docs/report.pdf`         |
| External image URL     | `https://cdn.com/img.png`       | `file:URL::https://cdn.com/img.png`          |
| System text file       | `files/data/content.txt`        | `file:text::files/data/content.txt`          |
| User attachment        | `files/uploads/u123/sheet.xlsx` | `file:base64::files/uploads/u123/sheet.xlsx` |
| External document      | `https://site.com/doc.pdf`      | `file:base64::https://site.com/doc.pdf`      |
| Multiple mixed files   | Various                         | Each gets own `file:{prefix}::{path_or_url}` |