# Design: File Management Tools

- **Status:** Draft
- **Dependencies:** None

## Problem Statement

QuickApps agents have no first-class way to create or selectively read files in DIAL file storage. Today:

- **Agents cannot create files of their own.** Tools can emit attachments as a side effect (REST tools, Python interpreter, large-response offload), but there is no tool the LLM can call to deliberately write a named text file — e.g., to save an intermediate result, a generated report, or a note it wants to refer back to later in the conversation.
- **Agents cannot read files selectively.** If an attachment is on the conversation (a user upload, a prior tool output, an offloaded response), the agent's only option is to load it wholesale into its context — wasteful for anything longer than a few KB.

Both gaps matter in isolation. Together, they prevent agents from using DIAL file storage as a working surface: producing files, reading back slices, and chaining those slices into follow-up reasoning.

## Design Goals

- Expose a minimal, reliable set of **file-management tools** to the LLM: create a file, read a slice by line range, search a file for a substring, edit a file by string replacement, delete a file.
- Favor line-based addressing over byte/character offsets — LLMs can reason about lines, not bytes.
- Keep the tool surface small and orthogonal: one tool per concern, no mode-switching parameters.
- Fail loudly on invalid input so the LLM can self-correct.
- Namespace agent-generated files away from user uploads and other machine-generated artifacts.
- Be preview-gated until the write semantics settle, with no footprint when the feature flag is off.

---

## Use Cases

### UC-1: Agent reads a line range from a stored file

**Trigger:** The LLM calls `read_file_lines(file_url=..., start_line=0, end_line=50)`.\
**Behavior:** The tool downloads the file via `DialFileService` (request-scoped cache), splits on `\n`, slices `[start_line:end_line]`, and returns the joined lines as `text/plain`.\
**Outcome:** The LLM gets exactly the requested slice.

### UC-2: Agent searches for a substring

**Trigger:** The LLM calls `search_in_file(file_url=..., pattern="ERROR", context_lines=2, case_insensitive=True)`.\
**Behavior:** The tool downloads the file, finds every line containing the (optionally lower-cased) pattern, expands each match by ±`context_lines`, merges overlapping windows, and returns the lines with 1-indexed line numbers. Non-adjacent windows are separated by `--`.\
**Outcome:** The LLM gets a focused, grep-style snippet with enough surrounding context to act on it.

### UC-3: Agent creates a new file

**Trigger:** The LLM calls `write_file(filename="notes.md", content="...")`.\
**Behavior:** The tool uploads `content` as a UTF-8 text file to `files/{bucket}/generated-files/{filename}` using DIAL's `files.upload` with `If-None-Match: *` (create-only). DIAL returns the file URL; the tool returns that URL in the `ToolCallResult`, with the file attached.\
**Outcome:** The agent can pass the returned `file_url` straight to `read_file_lines` / `search_in_file` later in the turn, or reference it in subsequent tool calls.

### UC-4: Agent attempts to overwrite an existing file

**Trigger:** `write_file` is called with a `filename` that already exists under `generated-files/`.\
**Behavior:** DIAL rejects the upload with `412 Precondition Failed` (because of `If-None-Match: *`). The tool surfaces `InvalidToolCallParameterException("filename", "file already exists: <url>")` back to the LLM via the existing `FallbackProcessor`.\
**Outcome:** The LLM sees a clear error and can choose a different filename or explicitly decide to re-write in a follow-up turn. No silent clobber.

### UC-5: Agent provides invalid read parameters

**Trigger:** The LLM calls `read_file_lines(start_line=-5, end_line=10)` or `end_line < start_line`.\
**Behavior:** The tool raises `InvalidToolCallParameterException`, surfaced to the LLM as a tool-call error.\
**Outcome:** The LLM sees a descriptive error and can retry.

### UC-6: Agent requests an oversized slice (no recursive offload)

**Trigger:** The LLM calls `read_file_lines(start_line=0, end_line=1_000_000)` on a very large file.\
**Behavior:** The tool returns the full slice. Because `read_file_lines` and `search_in_file` are on `LargeResponseProcessor`'s default `excluded_tools` list (see [Large Tool Response Processing](large_tool_responses.md)), the oversized result is **not** re-offloaded.\
**Outcome:** The LLM sees its own oversized request fill the context and narrows the next call. No infinite offload loop; no duplicate storage.

### UC-7: Repeated reads of the same file in one request

**Trigger:** The LLM calls `read_file_lines` / `search_in_file` multiple times against the same `file_url` within a single user turn.\
**Behavior:** `DialFileService` caches the download (request-scoped, keyed by `SHA256(url)`, 10 MB limit per file). Subsequent calls hit the cache.\
**Outcome:** No repeated GETs to DIAL.

### UC-8: Agent edits an existing file

**Trigger:** The LLM calls `edit_file(file_url=..., old_string="foo", new_string="bar")`.\
**Behavior:** The tool downloads the file (capturing its current etag), requires `old_string` to occur **exactly once** in the content, substitutes `new_string`, and re-uploads with `If-Match: <etag>` so the write fails if anyone else modified the file in the meantime.\
**Outcome:** The file at the same URL now contains the edit. The tool returns a short confirmation with the URL.

### UC-9: Edit fails because the match is not unique

**Trigger:** `old_string` occurs zero times or more than once in the file.\
**Behavior:** The tool raises `InvalidToolCallParameterException("old_string", "...")` — either "not found" or "found N times; provide more surrounding context to disambiguate". No upload happens.\
**Outcome:** The LLM sees a precise error and can retry with a more specific `old_string`.

### UC-10: Edit fails because the file changed concurrently

**Trigger:** Between the tool's `download` and `upload`, another writer updates the same `file_url` (rare within a single request; possible across concurrent agents sharing a file).\
**Behavior:** DIAL responds `412 Precondition Failed` on the conditional upload. The tool surfaces a descriptive error to the LLM, instructing it to re-read the file and retry.\
**Outcome:** Lost-update is prevented by the `If-Match` guard.

### UC-11: Agent deletes a file

**Trigger:** The LLM calls `delete_file(file_url=...)`.\
**Behavior:** The tool calls `dial_client.files.delete(file_url)` and returns a short confirmation.\
**Outcome:** The file is removed from DIAL storage. Subsequent reads on that URL fail.

---

## Proposed Design

### Component 1: `_FileTool` base class

**What:** A thin internal base class that holds the common dependencies (`DialFileService`, `AttachmentService`, stage-wrapper plumbing) and extends `StagedBaseTool`. Concrete tools implement `_run_in_stage_async`.

**Owner:** `src/quickapp/file_tooling/_base_file_tool.py`

**Semantics:** Provides `self._dial_file_service` and `self._attachment_service` to subclasses. Tools write their `ToolCallResult` to the stage via the injected stage wrapper so the raw text is always visible in the DIAL UI regardless of offload.

---

### Component 2: `read_file_lines`

**What:** Internal tool that returns a line-range slice of a UTF-8 text file.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file_url` | string | yes | URL of the file in DIAL storage. |
| `start_line` | integer | yes | First line (0-indexed, inclusive). |
| `end_line` | integer | yes | First line to exclude (0-indexed, like a Python slice end). |

**Algorithm:**

1. Validate `start_line >= 0` and `end_line >= start_line` — else raise `InvalidToolCallParameterException`.
2. Download file bytes via `DialFileService.download_file(file_url)` (cached per request).
3. Decode UTF-8, split on `\n` (via `splitlines()`).
4. Return `"\n".join(lines[start_line:end_line])` as `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/file_tooling/_read_file_lines_tool.py`

---

### Component 3: `search_in_file`

**What:** Internal tool that returns matching lines with surrounding context, grep-style.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `file_url` | string | yes | — | URL of the file in DIAL storage. |
| `pattern` | string | yes | — | Substring to search for. |
| `context_lines` | integer | no | `0` | Lines of context around each match. |
| `case_insensitive` | boolean | no | `false` | If true, compare lower-cased. |

**Algorithm:**

1. Download and decode UTF-8 text (cached per request).
2. Split into lines via `splitlines()`.
3. For each line index, test `pattern in line` (lower-casing both if `case_insensitive`).
4. If no matches → return `"No matches found."` as `text/plain`.
5. Build the union of `[i - context_lines, i + context_lines]` windows around each match (clamped to file bounds), deduplicate, sort.
6. Emit each included line as `"{i+1}:{line}"` (1-indexed for human readability). Insert a `--` separator between non-adjacent windows.
7. Return joined lines as `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/file_tooling/_search_in_file_tool.py`

**Design notes:**
- Substring only. Regex is out of scope (see below).
- Output line numbers are **1-indexed**, matching standard grep/editor conventions. `read_file_lines` inputs are **0-indexed** to match Python slice semantics — this asymmetry is intentional and documented in each tool's description.

---

### Component 4: `write_file`

**What:** Internal tool that creates a new UTF-8 text file in DIAL file storage. Create-only: fails if the target path is already occupied.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `filename` | string | yes | File name. Must be a simple name — no path separators, no `..`. |
| `content` | string | yes | File content. UTF-8 text. |

**Algorithm:**

1. Validate `filename`: non-empty, no `/`, no `..`, no leading/trailing whitespace. Else raise `InvalidToolCallParameterException`.
2. Resolve bucket (`dial_client.bucket.get_raw()`).
3. Upload via `dial_client.files.upload(url=f"files/{bucket}/generated-files/{filename}", file=content.encode("utf-8"), etag_if_none_match="*")`.
4. On `412 Precondition Failed` → raise `InvalidToolCallParameterException("filename", "file already exists: <url>")`.
5. On success → build an `Attachment` pointing at the returned URL and return:
   ```
   ToolCallResult(
       content=f"File written: {url}",
       content_type="text/plain",
       attachments=[attachment],
   )
   ```

**Owner:** `src/quickapp/file_tooling/_write_file_tool.py`

**Design notes:**
- **Create-only** (`If-None-Match: *`) was chosen over silent overwrite so the LLM never clobbers a prior write by accident. If the agent genuinely needs to replace a file, it must acknowledge the collision (see UC-4) — a separate overwrite tool or explicit `overwrite=true` parameter can be added later if the pattern becomes common.
- Files land under `generated-files/` to keep agent output distinct from `offloaded-responses/` and from user-uploaded files at the bucket root.
- Returns a **small confirmation string** (plus attachment), so it never trips the offload size threshold — no need to add `write_file` to `LargeResponseProcessor.excluded_tools`.

**AttachmentService extension:** `AttachmentService.upload_attachment_to_core` is extended with two keyword-only parameters: `if_none_match: Literal["*"] | None = None` and `if_match: str | None = None`, forwarded to `dial_client.files.upload` as `etag_if_none_match` / `etag_if_match`. Defaults (`None`) preserve today's unconditional-overwrite behavior for existing callers; `write_file` passes `if_none_match="*"` (create-only), and `edit_file` passes `if_match=<etag>` (update-if-unchanged).

---

### Component 5: `edit_file`

**What:** Internal tool that applies a single string-replacement edit to an existing UTF-8 text file, guarded by the file's ETag to prevent lost updates.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file_url` | string | yes | URL of the file in DIAL storage. |
| `old_string` | string | yes | Exact substring to replace. Must occur **exactly once** in the file. |
| `new_string` | string | yes | Replacement text. May be empty (deletes the `old_string` occurrence). |

**Algorithm:**

1. Download the file and capture its `etag` via `dial_client.files.download(file_url)` (which returns both the bytes and the response headers/metadata). Decode UTF-8.
2. If `old_string == new_string` → raise `InvalidToolCallParameterException("new_string", "new_string must differ from old_string")`.
3. `count = content.count(old_string)`. If `count == 0` → raise `"old_string not found in file"`. If `count > 1` → raise `"old_string found {count} times; provide more surrounding context to disambiguate"`.
4. `new_content = content.replace(old_string, new_string, 1)` (explicit count=1 for safety, even though uniqueness is already verified).
5. Re-upload via `AttachmentService.upload_attachment_to_core(..., if_match=etag)` pointing at the same `file_url`.
6. On `412 Precondition Failed` → raise `InvalidToolCallParameterException("file_url", "file changed concurrently; re-read and retry")`.
7. On success → return `ToolCallResult(content=f"Edited: {url}", content_type="text/plain")`. No attachment — the URL is unchanged; returning it as text is sufficient.

**Owner:** `src/quickapp/file_tooling/_edit_file_tool.py`

**Design notes:**
- **Unique-match requirement** matches Claude's own Edit tool semantics and is the most reliable primitive for LLMs: it forces the model to include enough surrounding context to disambiguate, which is also what a human reviewer would expect.
- **Why string replacement over line-range replacement.** Line numbers drift after any prior edit in the same conversation; the LLM would have to re-read the file before every subsequent edit. Anchoring on substring content keeps edits locally consistent.
- **ETag optimistic concurrency.** `If-Match: <etag>` catches the narrow case where two tool calls modify the same file in parallel (e.g., concurrent agents). Without it, one edit silently overwrites the other. The check is cheap; the failure mode is a clean error the LLM can react to.
- **Cost of the round-trip.** Edit is a full download + full upload. For large files this is wasteful; the offload-read-back exclusion (`excluded_tools`) does not apply here because `edit_file` doesn't return the file content — just a confirmation. Clients that need frequent edits on large files should consider restructuring (e.g., splitting into multiple smaller files).
- **No partial-update primitive is available.** DIAL's file API has no PATCH; the download+upload shape is the only option. If DIAL later exposes partial updates, `edit_file` can be migrated without changing its LLM-facing contract.

---

### Component 6: `delete_file`

**What:** Internal tool that removes a file from DIAL storage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file_url` | string | yes | URL of the file in DIAL storage to delete. |

**Algorithm:**

1. Call `dial_client.files.delete(file_url)`.
2. On success → return `ToolCallResult(content=f"Deleted: {file_url}", content_type="text/plain")`.
3. On `404 Not Found` or other error → propagate as a tool-call error (LLM-visible).

**Owner:** `src/quickapp/file_tooling/_delete_file_tool.py`

**Design notes:**
- **No ETag guard.** Delete is unconditional: if the LLM has the URL and permission, it can remove the file. Conditional delete (`If-Match`) is out of scope; the concurrency window for delete is rarely meaningful (you either want it gone or you don't).
- **No soft-delete / trash.** DIAL's `files.delete` is a hard delete. Agents should confirm they no longer need the file before calling this tool; there is no undo.
- **Permission scoping.** This tool does not artificially restrict deletion to `generated-files/`. The DIAL permission model governs what the caller can actually delete — this design relies on DIAL's enforcement rather than a client-side allowlist. An operator who wants to prevent agents from deleting user uploads should configure DIAL permissions accordingly.

---

### Component 7: `FileToolingModule` (DI wiring)

**What:** `injector.Module` that:

- Binds `_FileStageWrapper`, `_ReadFileLinesTool`, `_SearchInFileTool`, `_WriteFileTool`, `_EditFileTool`, `_DeleteFileTool` in `request_scope`.
- Contributes all five tools to the internal-tool `list[StagedBaseTool]` multiprovider alongside other internal tools.
- Is **preview-feature-gated** via `@preview_module` — when `ENABLE_PREVIEW_FEATURES=false`, nothing is bound and the tools are invisible to the LLM.
- Does **not** depend on or import `tool_call_result_offload`. The offload module's default `excluded_tools` references the read tools' names (`read_file_lines`, `search_in_file`) as strings.

**Owner:** `src/quickapp/file_tooling/file_tooling_module.py`

**Registration:** Added to the module list in `src/quickapp/app_factory.py`.

---

### Component 8: Tool configs and stage display

**What:** `OpenAiToolConfig` definitions with JSON-schema parameters, plus `ToolDisplayConfig` for the DIAL stage UI.

**Highlights:**
- Stage titles are human-readable: `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`.
- The `file_url` parameter renders in the stage as `**File:** {basename}` (last path segment only) so the UI stays compact.

**Owner:** `src/quickapp/file_tooling/_tool_configs.py`

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| `start_line < 0` or `end_line < start_line` (read_file_lines) | `InvalidToolCallParameterException` → surfaced to LLM. |
| Invalid `filename` on `write_file` (empty, path separator, `..`) | `InvalidToolCallParameterException` → surfaced to LLM. |
| `write_file` target already exists (DIAL `412`) | `InvalidToolCallParameterException("filename", "file already exists: <url>")` → surfaced to LLM. |
| `edit_file` `old_string` not found | `InvalidToolCallParameterException("old_string", "not found in file")` → surfaced to LLM. |
| `edit_file` `old_string` matches multiple places | `InvalidToolCallParameterException("old_string", "found N times; disambiguate with more context")` → surfaced to LLM. |
| `edit_file` `new_string == old_string` | `InvalidToolCallParameterException("new_string", ...)` → surfaced to LLM. |
| `edit_file` conditional upload fails (DIAL `412`) | `InvalidToolCallParameterException("file_url", "file changed concurrently; re-read and retry")`. |
| `delete_file` target missing or forbidden | Error propagates from `dial_client.files.delete`; surfaced to LLM. |
| `file_url` missing or DIAL GET fails | Error propagates from `DialFileService`; the tool returns an error result. |
| File is not valid UTF-8 | `UnicodeDecodeError` propagates; LLM sees the error. Binary files are out of scope. |
| LLM requests an oversized slice | Result bypasses `LargeResponseProcessor` (read tools are in its default `excluded_tools`). Content fills the context directly — expected self-correction. |

---

## Out of Scope

- **List files / browse a directory.** `dial_client.metadata.get("files", ...)` exists in the SDK and could power a `list_files` tool. Deferred — the first use cases don't require directory browsing, and exposing a list API invites follow-on decisions (pagination, filtering, permission surfaces) that are better made once we see real demand.
- **Rename / move / copy.** No primitive in the DIAL API; would be a download + upload + delete. Deferred — most agent workflows can substitute "write new + delete old".
- **Conditional / soft delete.** `delete_file` is unconditional and hard. ETag-guarded delete and trash/undo semantics are deferred.
- **Multi-edit in one call.** `edit_file` replaces a single unique `old_string` per invocation. Batching multiple independent edits (Claude's `MultiEdit` shape) is deferred — the LLM can loop if needed.
- **Binary / non-UTF-8 files.** All three tools assume UTF-8 text. A separate tool (or content-type-aware dispatch) would be needed for binary formats.
- **Regex search.** `search_in_file` ships with substring + `case_insensitive` only. Regex requires DoS protection (timeout, catastrophic backtracking mitigation), bounds checks, and careful error surfaces — addressed in a follow-up when the use case becomes concrete.
- **Character/byte offset reading.** Rejected: LLMs cannot reliably estimate character positions in an opaque file. Line numbers are surfaced naturally by search results.
- **Combined `file_query(mode=...)` tool.** Considered and rejected — conditional parameters (either `pattern` or `start_line`/`end_line` depending on mode) confuse weaker models for marginal token savings.
- **Overwrite semantics for `write_file`.** v1 is create-only. A deliberate overwrite path (separate tool, explicit `overwrite=true`, or an ETag-conditional `replace_file`) is deferred until a concrete need emerges.
- **Directory operations**, **multi-file search**, **hard limits on read parameters** (truncation, pagination tokens).

---

## Configuration / Usage Examples

### Tool schemas (abridged)

```jsonc
// read_file_lines
{
  "name": "read_file_lines",
  "description": "Read a range of lines from a file stored in DIAL. Use start_line and end_line (0-indexed, end exclusive) to retrieve a slice.",
  "parameters": {
    "file_url":   {"type": "string",  "description": "URL of the file to read."},
    "start_line": {"type": "integer", "description": "First line to include (0-indexed)."},
    "end_line":   {"type": "integer", "description": "First line to exclude (0-indexed). Like Python slice end."}
  },
  "required": ["file_url", "start_line", "end_line"]
}

// search_in_file
{
  "name": "search_in_file",
  "description": "Search for a substring in a file stored in DIAL. Returns matching lines with optional surrounding context.",
  "parameters": {
    "file_url":         {"type": "string",  "description": "URL of the file to search."},
    "pattern":          {"type": "string",  "description": "Substring to search for."},
    "context_lines":    {"type": "integer", "description": "Lines of context around each match. Default: 0."},
    "case_insensitive": {"type": "boolean", "description": "If true, search is case-insensitive. Default: false."}
  },
  "required": ["file_url", "pattern"]
}

// write_file
{
  "name": "write_file",
  "description": "Create a new UTF-8 text file in DIAL storage. Fails if a file with the same name already exists. Returns the file URL, which can be passed to read_file_lines or search_in_file.",
  "parameters": {
    "filename": {"type": "string", "description": "Simple file name (no path separators, no '..')."},
    "content":  {"type": "string", "description": "UTF-8 text content of the file."}
  },
  "required": ["filename", "content"]
}

// edit_file
{
  "name": "edit_file",
  "description": "Replace a unique substring in an existing UTF-8 text file. old_string must occur exactly once. Fails if the file changed concurrently.",
  "parameters": {
    "file_url":   {"type": "string", "description": "URL of the file to edit."},
    "old_string": {"type": "string", "description": "Exact substring to replace. Must occur exactly once. Include surrounding context to disambiguate."},
    "new_string": {"type": "string", "description": "Replacement text. May be empty to delete the match."}
  },
  "required": ["file_url", "old_string", "new_string"]
}

// delete_file
{
  "name": "delete_file",
  "description": "Delete a file from DIAL storage. Hard delete; no undo.",
  "parameters": {
    "file_url": {"type": "string", "description": "URL of the file to delete."}
  },
  "required": ["file_url"]
}
```

### `search_in_file` output format

```
12:before match
13:LINE WITH MATCH
14:after match
--
57:another match
```

- Lines are prefixed with `1-indexed line number:`.
- `--` separates non-adjacent windows when `context_lines > 0`.
- No matches → literal string `"No matches found."`.

### `write_file` on success

```
File written: https://dial-storage/.../files/<bucket>/generated-files/notes.md
```

### `write_file` on collision

```
InvalidToolCallParameterException: file already exists: https://dial-storage/.../files/<bucket>/generated-files/notes.md
```

### `edit_file` on success / failure

```
// success
Edited: https://dial-storage/.../files/<bucket>/generated-files/notes.md

// old_string not unique
InvalidToolCallParameterException: old_string found 3 times; provide more surrounding context to disambiguate

// concurrent modification (412)
InvalidToolCallParameterException: file changed concurrently; re-read and retry
```

### `delete_file` on success

```
Deleted: https://dial-storage/.../files/<bucket>/generated-files/notes.md
```

### Interaction with offload

The `LargeResponseProcessor` default configuration lists `read_file_lines` and `search_in_file` in its `excluded_tools` set — their outputs are never re-offloaded. `write_file` is not excluded: its output is always a short confirmation string. See [Large Tool Response Processing](large_tool_responses.md).

---

## Migration

### Breaking changes

None. Net-new capability, preview-gated.

### Non-breaking changes

- `AttachmentService.upload_attachment_to_core` gains two keyword-only parameters: `if_none_match: Literal["*"] | None = None` and `if_match: str | None = None`. Defaults preserve current unconditional-overwrite behavior for all existing callers (large-response offload, REST tools, Python interpreter).
- New module registered in `app_factory.py` — skipped when `ENABLE_PREVIEW_FEATURES=false`.
- Tool names `read_file_lines`, `search_in_file`, `write_file`, `edit_file`, `delete_file` enter the internal-tool namespace when preview is on. Any existing REST/MCP tool sharing these names in a user manifest would collide — acceptable given the preview gate.

---

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `file_tooling/_base_file_tool.py` | `_FileTool` base class with `DialFileService` + `AttachmentService` wiring. |
| `file_tooling/_read_file_lines_tool.py` | `read_file_lines` implementation. |
| `file_tooling/_search_in_file_tool.py` | `search_in_file` implementation. |
| `file_tooling/_write_file_tool.py` | `write_file` implementation. |
| `file_tooling/_edit_file_tool.py` | `edit_file` implementation (download + string-replace + conditional upload). |
| `file_tooling/_delete_file_tool.py` | `delete_file` implementation. |
| `file_tooling/_stage_wrapper.py` | Stage wrapper for the DIAL UI display. |
| `file_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all five tools. |
| `file_tooling/file_tooling_module.py` | Preview-gated DI module; contributes tools to the internal-tool multiprovider. |

### Modified files

| File | Change |
|------|--------|
| `dial_core_services/attachment_service.py` | Add keyword-only `if_none_match` and `if_match` parameters to `upload_attachment_to_core`, forward to `dial_client.files.upload`. |
| `dial_core_services/dial_file_service.py` | Expose the file's ETag alongside its bytes on download (needed by `edit_file`) — either return a `(bytes, etag)` tuple from a new method or stash the etag in the request-scoped cache keyed by URL. |
| `app_factory.py` | Register `FileToolingModule`. |

### New tools exposed to the LLM

- `read_file_lines(file_url, start_line, end_line)`
- `search_in_file(file_url, pattern, context_lines=0, case_insensitive=False)`
- `write_file(filename, content)`
- `edit_file(file_url, old_string, new_string)`
- `delete_file(file_url)`

### Tests

- Unit: `src/tests/unit_tests/file_tooling/` — slice boundaries, invalid ranges, match/no-match, context expansion and window merging, case-insensitivity, `write_file` success, filename validation, collision (412) error path, UTF-8 encoding, `edit_file` unique-match success / not-found / non-unique / same-string / concurrent-modification (412), `delete_file` success and not-found error.
- Integration: covered via the offload end-to-end case in [Large Tool Response Processing](large_tool_responses.md) (read-back path, UC-6 here).
