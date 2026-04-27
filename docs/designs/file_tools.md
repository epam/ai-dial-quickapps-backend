# Design: File Management Tools

- **Status:** Draft
- **Owner:** Andrii Novikov
- **Dependencies:** [large_tool_responses](large_tool_responses.local.md) (forward dependency — file tools ship without offload integration; offload integration lands when that design is approved)


## Problem Statement

QuickApps agents have no first-class way to create or selectively read files in DIAL file storage. Today:

- **Agents cannot create files of their own.** Tools can emit attachments as a side effect (REST tools, Python interpreter), but there is no tool the LLM can call to deliberately write a named text file — e.g., to save an intermediate result, a generated report, or a note it wants to refer back to later in the conversation.
- **Agents cannot read files selectively.** If an attachment is on the conversation (a user upload, a prior tool output, an offloaded response), the agent's only option is to load it wholesale into its context — wasteful for anything longer than a few KB.

Both gaps matter in isolation. Together, they prevent agents from using DIAL file storage as a working surface: producing files, reading back slices, and chaining those slices into follow-up reasoning.

## Design Goals

- Expose a minimal, reliable set of **file-management tools** to the LLM: create a file, read a slice by line range, search a file for a substring, edit a file by string replacement, delete a file.
- Favor line-based addressing over byte/character offsets — LLMs can reason about lines, not bytes.
- Keep the tool surface small and orthogonal: one tool per concern, no mode-switching parameters.
- Fail loudly on invalid input so the LLM can self-correct.
- Namespace agent-generated files away from user uploads and other machine-generated artifacts — write/edit/delete are scoped to `generated-files/`; read tools accept any accessible file URL.
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
**Outcome:** The LLM sees a clear error. It can choose a different filename, or modify the existing file via `edit_file`. There is no overwrite path — `write_file` is create-only in v1. No silent clobber.

### UC-5: Agent provides invalid read parameters

**Trigger:** The LLM calls `read_file_lines(start_line=-5, end_line=10)` or `end_line < start_line`.\
**Behavior:** The tool raises `InvalidToolCallParameterException`, surfaced to the LLM as a tool-call error.\
**Outcome:** The LLM sees a descriptive error and can retry.

### UC-6: Repeated reads of the same file in one request

**Trigger:** The LLM calls `read_file_lines` / `search_in_file` multiple times against the same `file_url` within a single user turn.\
**Behavior:** `DialFileService` caches the download (request-scoped, keyed by `SHA256(url)`, 10 MB limit per file). Subsequent calls hit the cache.\
**Outcome:** No repeated GETs to DIAL.

### UC-7: Agent edits an existing file

**Trigger:** The LLM calls `edit_file(file_url=..., old_string="foo", new_string="bar")`.\
**Behavior:** The tool downloads the file (capturing its current ETag via metadata), requires `old_string` to occur **exactly once** in the content, substitutes `new_string`, re-uploads with `If-Match: <etag>` so the write fails if anyone else modified the file in the meantime, then invalidates the request-scoped cache entry for that URL.\
**Outcome:** The file at the same URL now contains the edit. Subsequent `read_file_lines`/`search_in_file` calls within the same turn see the updated content. The tool returns a short confirmation with the URL.

### UC-8: Edit fails because the match is not unique

**Trigger:** `old_string` occurs zero times or more than once in the file.\
**Behavior:** The tool raises `InvalidToolCallParameterException("old_string", "...")` — either "not found" or "found N times; provide more surrounding context to disambiguate". No upload happens.\
**Outcome:** The LLM sees a precise error and can retry with a more specific `old_string`.

### UC-9: Edit fails because the file changed concurrently

**Trigger:** Between the tool's `download` and `upload`, another writer updates the same `file_url` (rare within a single request; possible across concurrent agents sharing a file).\
**Behavior:** DIAL responds `412 Precondition Failed` on the conditional upload. The tool surfaces a descriptive error to the LLM, instructing it to re-read the file and retry.\
**Outcome:** Lost-update is prevented by the `If-Match` guard.

### UC-10: Agent deletes a file

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

**What:** Internal tool that returns a line-range slice of a UTF-8 text file. Accepts any accessible file URL — not restricted to `generated-files/`.

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

**What:** Internal tool that returns matching lines with surrounding context, grep-style. Accepts any accessible file URL — not restricted to `generated-files/`.

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
4. If no matches → return `ToolCallResult(content="No matches found.", content_type="text/plain")`.
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
| `filename` | string | yes | File name. Must be a simple name — no `/`, no `..`, no leading/trailing whitespace. |
| `content`  | string | yes | File content. UTF-8 text. |

**Algorithm:**

1. Validate `filename`: non-empty, no `/`, no `..`, no leading/trailing whitespace. Else raise `InvalidToolCallParameterException("filename", ...)`.
2. Resolve bucket (`dial_client.bucket.get_raw()`).
3. Build target URL: `url = f"files/{bucket}/{GENERATED_FILES_ROOT}{filename}"` (e.g., `files/{bucket}/generated-files/notes.md`).
4. Call `DialFileService.upload_text(url=url, content=content, if_none_match="*")`.
5. On `412 Precondition Failed` → raise `InvalidToolCallParameterException("filename", "file already exists: {url}")`.
6. On success → build an `Attachment` pointing at the returned URL and return:
   ```
   ToolCallResult(
       content=f"File written: {url}",
       content_type="text/plain",
       attachments=[attachment],
   )
   ```

**Owner:** `src/quickapp/file_tooling/_write_file_tool.py`

**Design notes:**
- **Create-only** (`If-None-Match: *`) was chosen over silent overwrite so the LLM never clobbers a prior write by accident. There is no overwrite tool in v1 — to modify an existing file, use `edit_file`. An explicit overwrite primitive (separate tool or `overwrite=true`) can be added later if the pattern becomes common.
- **`GENERATED_FILES_ROOT` constant.** The prefix `generated-files/` (and by extension the URL patterns in `write_file` and `delete_file`'s path guard) is a single string constant defined in `_base_file_tool.py`, referenced from `_write_file_tool.py` and `_delete_file_tool.py`. No hardcoded strings at call sites.
- Files land flat under `generated-files/{filename}` to keep agent output distinct from user-uploaded files at the bucket root. There is no LLM-controlled subdirectory — internal subsystems that need their own namespace (e.g., a future `large_tool_responses` offloader) construct URLs directly via `DialFileService.upload_text` with their own prefix, not through this tool.
- Returns a **small confirmation string** (plus attachment)

**DialFileService extension:** `write_file` and `edit_file` both use a new lower-level `DialFileService.upload_text` method rather than `AttachmentService.upload_attachment_to_core`. The existing `upload_attachment_to_core` has three problems that make it unsuitable: (1) it short-circuits when `attachment.url is not None`, but `edit_file` re-uploads to an existing URL; (2) it silently swallows upload exceptions, preventing 412 from being translated to `InvalidToolCallParameterException`; (3) it is Attachment-shaped, not URL + raw-bytes shaped. `AttachmentService` is **not modified**.

New method: `DialFileService.upload_text(url: str, content: str, *, if_none_match: Literal["*"] | None = None, if_match: str | None = None) -> str` — encodes content as UTF-8, calls `dial_client.files.upload` with the appropriate conditional header, propagates 412 directly, and returns the confirmed URL.

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

1. Obtain the file's ETag and content via a new `DialFileService.download_file_with_etag(file_url) -> tuple[bytes, str]` method: it first calls `dial_client.files.get_metadata(file_url)` to read `FileMetadata.etag`, then calls the existing `DialFileService.download_file(file_url)` for the bytes (hits the request-scoped cache). Returns `(bytes, etag)`. Decode UTF-8. Note: `AsyncFiles.download` does not expose response headers, so the ETag must come from a separate metadata call.
2. If `old_string == new_string` → raise `InvalidToolCallParameterException("new_string", "new_string must differ from old_string")`.
3. `count = content.count(old_string)`. If `count == 0` → raise `"old_string not found in file"`. If `count > 1` → raise `"old_string found {count} times; provide more surrounding context to disambiguate"`.
4. `new_content = content.replace(old_string, new_string, 1)` (explicit count=1 for safety, even though uniqueness is already verified).
5. Re-upload via `DialFileService.upload_text(url=file_url, content=new_content, if_match=etag)`.
6. On `412 Precondition Failed` → raise `InvalidToolCallParameterException("file_url", "file changed concurrently; re-read and retry")`.
7. On success → invalidate the request-scoped cache entry for `file_url` via `DialFileService.invalidate_cache(file_url)` so that subsequent `read_file_lines`/`search_in_file` calls in the same turn see the updated content. Return `ToolCallResult(content=f"Edited: {url}", content_type="text/plain")`. No attachment — the URL is unchanged; returning it as text is sufficient.

**Owner:** `src/quickapp/file_tooling/_edit_file_tool.py`

**Design notes:**
- **Unique-match requirement** matches Claude's own Edit tool semantics and is the most reliable primitive for LLMs: it forces the model to include enough surrounding context to disambiguate, which is also what a human reviewer would expect.
- **Why string replacement over line-range replacement.** Line numbers drift after any prior edit in the same conversation; the LLM would have to re-read the file before every subsequent edit. Anchoring on substring content keeps edits locally consistent.
- **ETag optimistic concurrency.** `If-Match: <etag>` catches the narrow case where two tool calls modify the same file in parallel (e.g., concurrent agents). Without it, one edit silently overwrites the other. The check is cheap; the failure mode is a clean error the LLM can react to.
- **Cost of the round-trip.** Edit is a full download + full upload. For large files this is wasteful; the offload-read-back exclusion (`excluded_tools`) does not apply here because `edit_file` doesn't return the file content — just a confirmation. Clients that need frequent edits on large files should consider restructuring (e.g., splitting into multiple smaller files).
- **No partial-update primitive is available.** DIAL's file API has no PATCH; the download+upload shape is the only option. If DIAL later exposes partial updates, `edit_file` can be migrated without changing its LLM-facing contract.
- **Post-edit cache invalidation.** `DialFileService` caches downloads in a request-scoped dict keyed by `SHA256(url)`. A successful `edit_file` call must evict the cache entry for the edited URL via `DialFileService.invalidate_cache(url)`. Without invalidation, same-turn `read_file_lines`/`search_in_file` calls would return pre-edit bytes.
- **No attachment in response (accepted UX trade-off).** `edit_file` returns only a confirmation string; it does not re-emit the file as an attachment. This means the DIAL UI's Attachments panel does not refresh after an edit. The trade-off is accepted: the URL is unchanged, the LLM already has it, and emitting an attachment on every edit would clutter the UI for workflows that make multiple edits to the same file. If the UX need arises, re-emitting the same URL as an attachment is harmless and can be added without changing the LLM-facing contract.

---

### Component 6: `delete_file`

**What:** Internal tool that removes a file from DIAL storage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file_url` | string | yes | URL of the file in DIAL storage to delete. |

**Algorithm:**

1. Check that `file_url` falls under `GENERATED_FILES_ROOT` (i.e., the URL path segment after the bucket contains `generated-files/` as a prefix). If not → raise `InvalidToolCallParameterException("file_url", "delete is restricted to agent-generated files under generated-files/")`. This prevents an LLM from deleting user uploads, or any other artifact it happens to have a URL for.
2. Call `dial_client.files.delete(file_url)`.
3. On success → return `ToolCallResult(content=f"Deleted: {file_url}", content_type="text/plain")`.
4. On `404 Not Found` → raise `InvalidToolCallParameterException("file_url", "file not found: {file_url}")` — consistent with `write_file`/`edit_file` error shape.
5. Other errors → propagate as tool-call errors (LLM-visible).

**Owner:** `src/quickapp/file_tooling/_delete_file_tool.py`

**Design notes:**
- **No ETag guard.** Delete is unconditional: if the LLM has the URL and permission, it can remove the file. Conditional delete (`If-Match`) is out of scope; the concurrency window for delete is rarely meaningful (you either want it gone or you don't).
- **No soft-delete / trash.** DIAL's `files.delete` is a hard delete. Agents should confirm they no longer need the file before calling this tool; there is no undo.
- **Path-scoped guardrail.** `delete_file` enforces a client-side allowlist: only URLs under `GENERATED_FILES_ROOT` (`generated-files/`) can be deleted. This is not instead of DIAL's permission model — it is in addition to it. The three alternatives considered were: (a) path-scoped allowlist (chosen — cheap, aligns with `write_file`'s namespace), (b) same-session creation guard via `StateHolder` (tighter but loses cross-turn deletion of older files), (c) two-phase confirm with a token (most defensive but adds a round-trip and tool complexity). Options (b) and (c) are deferred.

---

### Component 7: `FileToolingModule` (DI wiring)

**What:** `injector.Module` that:

- Binds `_FileStageWrapper`, `_ReadFileLinesTool`, `_SearchInFileTool`, `_WriteFileTool`, `_EditFileTool`, `_DeleteFileTool` in `request_scope`.
- Contributes all five tools to the shared `list[StagedBaseTool]` multiprovider via its own `@multiprovider`-decorated `_provide_file_tools` method (same pattern as `InternalToolModule._provide_internal_tools`). `app_factory.py` wires `Injector([..., FileToolingModule()])` and the injector merges all `@multiprovider` contributions automatically.
- These tools are **not** gated by `InternalToolSet` or `app_config.tool_sets`. Per-app configuration lives on the `Features` container at `app_config.features.file_tools` (see Component 9), alongside the existing `timestamp` feature.
- Is **preview-feature-gated** via `@preview_module` — when `ENABLE_PREVIEW_FEATURES=false`, nothing is bound and the tools are invisible to the LLM.
- Does **not** depend on or import `tool_call_result_offload`. The offload module's `excluded_tools` will reference the read tools' names as strings once that design ships.

**Owner:** `src/quickapp/file_tooling/file_tooling_module.py`

**Registration:** Added to the module list in `src/quickapp/app_factory.py`.

---

### Component 8: Tool configs and stage display

**What:** `OpenAiToolConfig` definitions with JSON-schema parameters, plus `ToolDisplayConfig` for the DIAL stage UI.

**Highlights:**
- Stage titles are human-readable: `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`.
- The `file_url` parameter renders in the stage as `**File:** {basename}` (last path segment only) so the UI stays compact.

**Owner:** `src/quickapp/file_tooling/_tool_configs.py`

**Design notes:**
- **Python vs. JSON config.** The existing `internal_code_execution_python_interpreter` tool is defined via `config/predefined/tool/py_interpreter.json` and a corresponding toolset JSON, enabling operator opt-in through `app_config.tool_sets`. File tools use a different surface — a dedicated `features.file_tools` field on `ApplicationConfig` (see Component 9) — so defining `OpenAiToolConfig` in Python avoids the JSON config + `InternalToolSet` dispatch machinery entirely and keeps the preview gate alongside the per-app toggle.

---

### Component 9: Per-app config (`features.file_tools`)

**What:** A new `FileToolsConfig` field on the existing `Features` container in `src/quickapp/config/application.py`. Mirrors the shape of the existing `timestamp` preview feature and lets app authors restrict which file tools are exposed.

**Schema:**

```python
# src/quickapp/file_tooling/_config.py
from typing import Literal
from pydantic import BaseModel, Field

FileToolName = Literal[
    "read_file_lines", "search_in_file", "write_file", "edit_file", "delete_file"
]

class FileToolsConfig(BaseModel):
    enabled_tools: Literal["all"] | list[FileToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['read_file_lines', 'search_in_file'])."
        ),
    )
```

**Wiring on `Features`:**

```python
# src/quickapp/config/application.py
class Features(BaseModel):
    timestamp: TimestampConfig | None = PreviewField(
        default_factory=ToolCallTimestampConfig, ...
    )
    file_tools: FileToolsConfig | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Built-in file read/write/edit/delete tools.",
    )
```

**Resolution in `FileToolingModule`:**

```python
cfg = app_config.features.file_tools
if cfg is None:
    return []  # feature not enabled for this app
if cfg.enabled_tools == "all":
    return ALL_FILE_TOOLS
return [t for t in ALL_FILE_TOOLS if t.name in cfg.enabled_tools]
```

**Design notes:**
- **Default semantics.** `features.file_tools` defaults to `None` on `Features` — file tools are off unless the app author explicitly opts in by adding `features.file_tools: {}` (or any object) to the manifest. Once enabled, `enabled_tools` defaults to `"all"`, which is visible in the schema (no hidden behavior).
- **Why `"all"` as a literal.** Using a `Literal["all"] | list[FileToolName]` keeps the surface single-field while making the "every tool" case explicit and self-documenting. Alternatives — e.g. an unset field meaning "all", or a separate `preset` field — were rejected as either implicit or redundant.
- **Preview gating.** `file_tools` is a `PreviewField`. When `ENABLE_PREVIEW_FEATURES=false`, `nullify_preview_fields` clears it back to `None` and `FileToolingModule` (also preview-gated) contributes nothing.
- **Future knobs.** `FileToolsConfig` is the natural home for later additions like `max_file_size_bytes`, allow/deny path prefixes for reads, or a per-app `namespace` (subdir under `generated-files/`) — added as sibling fields without breaking the schema.

**Owner:** `src/quickapp/file_tooling/_config.py` and a small edit to `src/quickapp/config/application.py`.

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
| `file_url` missing or DIAL GET fails | Error propagates from `DialFileService`; the tool returns an error result. |
| File exceeds 10 MB download limit (`DialFileService` cap) | Translated to `InvalidToolCallParameterException("file_url", "file is too large to read (limit: 10 MB)")` — the raw `ValueError` from `DialFileService` is caught and re-raised with a clear message so the LLM can react. |
| File is not valid UTF-8 | `UnicodeDecodeError` propagates; LLM sees the error. Binary files are out of scope. |
| `delete_file` URL not under `generated-files/` | `InvalidToolCallParameterException("file_url", "delete is restricted to agent-generated files under generated-files/")` — client-side path guard. |
| `delete_file` target not found (404) | `InvalidToolCallParameterException("file_url", "file not found: <url>")` — same shape as `write_file`/`edit_file` errors for a uniform LLM-visible format. |
| LLM requests an oversized slice | Intended to bypass `LargeResponseProcessor` once that feature ships (read tools will be in `excluded_tools`). Content fills the context directly — expected self-correction. |

---

## Out of Scope

- **List files / browse a directory.** `dial_client.metadata.get("files", ...)` exists in the SDK and could power a `list_files` tool. Deferred — the first use cases don't require directory browsing, and exposing a list API invites follow-on decisions (pagination, filtering, permission surfaces) that are better made once we see real demand.
- **Rename / move / copy.** No primitive in the DIAL API; would be a download + upload + delete. Deferred — most agent workflows can substitute "write new + delete old".
- **Conditional / soft delete.** `delete_file` has a path-scoped client-side guardrail (see Component 6) but is otherwise unconditional and hard within that scope. ETag-guarded delete, same-session creation guards, two-phase confirm, and trash/undo semantics are all deferred.
- **Multi-edit in one call.** `edit_file` replaces a single unique `old_string` per invocation. Batching multiple independent edits (Claude's `MultiEdit` shape) is deferred — the LLM can loop if needed.
- **Binary / non-UTF-8 files.** All three tools assume UTF-8 text. A separate tool (or content-type-aware dispatch) would be needed for binary formats.
- **Regex search.** `search_in_file` ships with substring + `case_insensitive` only. Regex requires DoS protection (timeout, catastrophic backtracking mitigation), bounds checks, and careful error surfaces — addressed in a follow-up when the use case becomes concrete.
- **Character/byte offset reading.** Rejected: LLMs cannot reliably estimate character positions in an opaque file. Line numbers are surfaced naturally by search results.
- **Combined `file_query(mode=...)` tool.** Considered and rejected — conditional parameters (either `pattern` or `start_line`/`end_line` depending on mode) confuse weaker models for marginal token savings. The same orthogonality argument applies to `read_file_lines` vs. `search_in_file` specifically: a merged `read_file(file_url, *, lines=None, search=None)` with two optional, mutually-exclusive parameter groups makes both calling conventions harder to describe in the tool schema and forces the LLM to reason about which group applies. Two tools with entirely disjoint required parameters are unambiguous.
- **LLM-controlled subdirectories for `write_file`.** Files always land flat under `generated-files/{filename}`. Partitioning by module or purpose is a code-level concern: internal subsystems construct their own URL prefix and call `DialFileService.upload_text` directly. If per-application LLM-level namespacing ever becomes a concrete need, a `namespace` config field on `FileToolingModule` (not a free-form LLM parameter) is the right surface.
- **Overwrite semantics for `write_file`.** v1 is create-only. A deliberate overwrite path (separate tool, explicit `overwrite=true`, or an ETag-conditional `replace_file`) is deferred until a concrete need emerges.
- **Directory operations.** No `list_files` tool in v1; deferred pending real demand and decisions around pagination and permission surfaces.
- **Multi-file search.** Deferred — most use cases can loop over a known set of URLs.
- **Hard limits on read parameters** (truncation, pagination tokens). Deferred — the 10 MB download cap is the only enforced limit in v1.

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
  "description": "Create a new UTF-8 text file in DIAL storage under generated-files/. Fails if a file with the same name already exists. Returns the file URL.",
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

### Per-app manifest

```jsonc
// All five tools enabled
{
  "features": {
    "file_tools": {}            // defaults: enabled_tools = "all"
  }
}

// Read-only research agent
{
  "features": {
    "file_tools": {
      "enabled_tools": ["read_file_lines", "search_in_file"]
    }
  }
}

// File tools off (default — omit the field entirely)
{
  "features": {}
}
```

---

## Migration

### Breaking changes

None. Net-new capability, preview-gated.

### Non-breaking changes

- `DialFileService` gains three new methods (`upload_text`, `download_file_with_etag`, `invalidate_cache`) — all additive, no impact on existing callers.
- `AttachmentService` is unchanged.
- New module registered in `app_factory.py` — skipped when `ENABLE_PREVIEW_FEATURES=false`.
- Tool names `read_file_lines`, `search_in_file`, `write_file`, `edit_file`, `delete_file` enter the internal-tool namespace when preview is on. Any existing REST/MCP tool sharing these names in a user manifest would collide — acceptable given the preview gate.

---

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `file_tooling/_base_file_tool.py` | `_FileTool` base class with `DialFileService` + `AttachmentService` wiring; defines `GENERATED_FILES_ROOT = "generated-files/"` constant used by `write_file` and `delete_file`. |
| `file_tooling/_read_file_lines_tool.py` | `read_file_lines` implementation. |
| `file_tooling/_search_in_file_tool.py` | `search_in_file` implementation. |
| `file_tooling/_write_file_tool.py` | `write_file` implementation. |
| `file_tooling/_edit_file_tool.py` | `edit_file` implementation (download + string-replace + conditional upload). |
| `file_tooling/_delete_file_tool.py` | `delete_file` implementation. |
| `file_tooling/_stage_wrapper.py` | Stage wrapper for the DIAL UI display. |
| `file_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all five tools. |
| `file_tooling/file_tooling_module.py` | Preview-gated DI module; contributes tools to the internal-tool multiprovider; reads `app_config.features.file_tools` to filter which tools are exposed. |
| `file_tooling/_config.py` | `FileToolsConfig` model — `enabled_tools: Literal["all"] \| list[FileToolName]` with default `"all"`. |

### Modified files

| File | Change |
|------|--------|
| `dial_core_services/attachment_service.py` | No changes — `write_file` and `edit_file` use `DialFileService` directly. |
| `dial_core_services/dial_file_service.py` | Add `upload_text(url, content, *, if_none_match=None, if_match=None) -> str` — creates or updates a UTF-8 text file at an explicit URL, propagates 412 directly. Add `download_file_with_etag(url) -> tuple[bytes, str]` — fetches ETag via `get_metadata` then downloads bytes (cache-backed). Add `invalidate_cache(url)` — evicts the request-scoped cache entry for a URL after a successful edit. |
| `app_factory.py` | Register `FileToolingModule`. |
| `config/application.py` | Add `file_tools: FileToolsConfig \| None` as a `PreviewField` on the existing `Features` container. |

### New tools exposed to the LLM

- `read_file_lines(file_url, start_line, end_line)`
- `search_in_file(file_url, pattern, context_lines=0, case_insensitive=False)`
- `write_file(filename, content)` — writes to `generated-files/{filename}`; no LLM-controlled subdirectory
- `edit_file(file_url, old_string, new_string)`
- `delete_file(file_url)`

### Tests

- Unit: `src/tests/unit_tests/file_tooling/` — slice boundaries, invalid ranges, match/no-match, context expansion and window merging, case-insensitivity, `write_file` success / filename validation / collision (412) error path, UTF-8 encoding, `edit_file` unique-match success / not-found / non-unique / same-string / concurrent-modification (412) / cache invalidated after success, `delete_file` success / 404 → `InvalidToolCallParameterException` / URL outside `generated-files/` blocked, 10 MB download limit → `InvalidToolCallParameterException`.
- Integration: offload end-to-end coverage (UC-6 read-back path) is deferred pending the `large_tool_responses` design.

---

## Review Notes — Round 2
- **Reviewer:** Andrii
- **Date:** 2026-04-26

### Verdict
Need to address three suggestions

### Blocking issues
### Suggestions
1. UC-3: Agent creates a new file - we need to give possibility to specify path. For example we will introduce new_module and we want it to write file to /new-module-files/filename.txt instead of generated-files dir. Or it might be additional namespace dir inside generated-files
2. UC-4: Let's avoid giving possibility to rewrite a file. We have edit tool to edit files.
3. UC-10: We need some mechanism to prevent unintended file delitions. Let's think how to achive it best way
### Nits



## Author Response — Rounds 2 & 3

Addressing Round 2 suggestions and all Round 3 items (blocking issues, suggestions, nits):

- **Round 2 #1 / Round 3 Blocking #1 (`write_file` path):** Removed `subdirectory` parameter. LLM-controlled subdirectories are unreliable — the model can hallucinate names, drift across turns, or collide with other modules. Instead, `write_file` always writes to `generated-files/{filename}` (flat). Internal subsystems that need their own namespace (e.g., a future `large_tool_responses` offloader) construct URLs directly via `DialFileService.upload_text` with their own prefix — this is a code-level concern, not an LLM-facing parameter. Updated UC-3, Component 4 (parameters, algorithm, design notes), JSON schema, and tests.
- **Round 2 #2 / Round 3 Suggestion #1 (UC-4 framing):** Removed "re-write in a follow-up turn" from UC-4 Outcome; now states the only options are a different filename or `edit_file`. Added "no overwrite tool" one-liner to Component 4 design notes.
- **Round 2 #3 / Round 3 Blocking #2 (`delete_file` guardrail):** Chose option (a) — path-scoped allowlist. Algorithm step 1 rejects URLs outside `GENERATED_FILES_ROOT`. Design notes document the three alternatives considered (path-scoped, same-session guard, two-phase confirm) and why (a) was chosen. Out of Scope "Conditional / soft delete" bullet updated accordingly. Error Handling table has a new row.
- **Round 3 Suggestion #2 (Dependencies malformed):** Fixed — now correctly references `large_tool_responses.local.md` with forward-dependency note.
- **Round 3 Suggestion #3 (`generated-files/` constant):** `GENERATED_FILES_ROOT` constant added to `_base_file_tool.py` per the design; noted in Component 4 design notes and the new files table.
- **Round 3 Suggestion #4 (`edit_file` attachment UX):** Added design note in Component 5 documenting the accepted trade-off and the easy forward path if needed.
- **Round 3 Nit #1 (Status field):** Reverted to plain `Draft`.
- **Round 3 Nit #2 (heading style):** All Review Notes headings now use em dash.

---

## Author Response — Round 1

All blocking issues and suggestions have been addressed in Revision 1:

- **Blocking #1 (Component 7 registration):** Component 7 now explicitly states that `FileToolingModule` uses `@multiprovider` to contribute `list[StagedBaseTool]` independently of `InternalToolSet`, with no operator opt-in required. Component 8 adds a design note justifying the Python vs. JSON config choice.
- **Blocking #2 (edit_file etag):** Algorithm step 1 rewritten to use a new `DialFileService.download_file_with_etag` that calls `get_metadata` for the ETag and `download_file` for bytes. `AsyncFiles.download` header limitation noted inline.
- **Blocking #3 (write_file upload path):** `AttachmentService` is no longer modified. `write_file` and `edit_file` both use a new `DialFileService.upload_text` method. The three issues with `upload_attachment_to_core` are documented in Component 4's design notes.
- **Blocking #4 (large_tool_responses dependency):** Added to `Dependencies` header; offload references downgraded from "ships with this design" to "once that design ships". The Error Handling table and Tests section are updated accordingly.
- **Suggestion #1 (10 MB limit):** New Error Handling row translates the `DialFileService` `ValueError` into `InvalidToolCallParameterException`.
- **Suggestion #2 (No matches return type):** Step 4 now explicitly shows `ToolCallResult(...)`.
- **Suggestion #3 (cache invalidation):** UC-7, Component 5 algorithm step 7, and Component 5 design notes all specify cache eviction after a successful edit.
- **Suggestion #4 (two-tool justification):** Added to the `Combined file_query` Out-of-Scope bullet.
- **Nit #1 (Owner field):** Added to header.
- **Nit #2 (Python vs JSON config):** Justified in Component 8 design notes.
- **Nit #3 (duplicate Conditional / soft delete):** Catch-all Out-of-Scope line split into three distinct bullets; no duplication remains.
- **Nit #4 (delete_file 404):** Component 6 algorithm step 3 now raises `InvalidToolCallParameterException` for 404, consistent with other tools.

---

## Review Notes — Round 1

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-04-26



`Blocking issues must be addressed`.

The design's LLM-facing surface (five tools, inputs, error semantics, UC coverage) is in good shape — orthogonal, well-scoped, and the unique-match / ETag choices are well-reasoned. What blocks approval is that several load-bearing implementation claims do not match the current codebase, and the integration with `tool_call_result_offload` rests on a doc (`large_tool_responses.md`) that does not yet exist as an approved design. Resolving the codebase-fit issues will likely also tighten the *Summary of Changes* and *Migration* sections.

### Blocking issues

1. **Component 7 (`FileToolingModule`) — internal-tool registration story does not match the existing wiring.** The design says the module "Contributes all five tools to the internal-tool `list[StagedBaseTool]` multiprovider alongside other internal tools", but `InternalToolModule._provide_internal_tools` (`src/quickapp/internal_tooling/internal_tooling_module.py:36-64`) iterates `app_config.tool_sets` and only emits a tool when an `InternalToolSet` declares one whose name starts with `internal_code_execution_python_interpreter`. There is no generic dispatch; new internal tools require either (a) an entry in a predefined toolset/tool JSON under `config/predefined/tool/` and `config/predefined/toolset/` plus matching dispatch logic, or (b) a different pattern entirely. The doc does not say which.
   **Suggestion:** Specify the activation contract end-to-end. Either (i) introduce a new `config/predefined/tool/*.json` per tool plus a `config/predefined/toolset/file_tools.json` (mirroring `py_interpreter.json`/`location.json`) and explain how `FileToolingModule._provide_*` recognises these tools (likely a per-tool name match in the new module's own `@multiprovider`, since each `*Module` contributes its own `list[StagedBaseTool]` — `app_factory.py` lines 40–62 confirm injector merges the multiproviders), or (ii) state explicitly that these tools are unconditional internals not gated by `InternalToolSet` and explain how the orchestrator picks them up. As written, a reader cannot tell whether a user has to opt in via app config and, if so, what the schema looks like.

2. **Component 5 (`edit_file`) Algorithm step 1 — `dial_client.files.download` does not return the etag the way the doc implies.** The doc says download "returns both the bytes and the response headers/metadata"; in the SDK (`aidial_client/resources/files.py:147-170` and `aidial_client/types/file.py`), `AsyncFiles.download` returns a `FileDownloadResponse` whose only public surface is `aget_content()`, `awrite_to(...)`, iteration, and a `filename` property. Headers are not exposed. The actual etag accessor is `await dial_client.files.get_metadata(file_url).etag` (see `FileMetadata.etag` in `aidial_client/types/metadata.py`).
   **Suggestion:** Rewrite step 1 to call `get_metadata` for the etag (or fetch metadata first to also enforce the existing 10 MB cap consistently, then `download`). Also reconcile this with the *Summary of Changes* row that says `dial_file_service.py` will "expose the file's ETag alongside its bytes on download" — the cleanest fix is for `DialFileService` to return `(bytes, etag)` from a new method that fetches metadata + bytes in one call, and to spell that out here.

3. **Component 4 (`write_file`) — `AttachmentService.upload_attachment_to_core` is the wrong extension point.** Today (`src/quickapp/dial_core_services/attachment_service.py:28-49`) the method takes an `Attachment` whose `data` is base64-or-text, derives a name, picks the bucket, and silently swallows exceptions on failure (returning the original attachment). Three problems for `write_file`/`edit_file`:
   - Adding `if_none_match`/`if_match` keyword args still leaves the method skipping work whenever `attachment.url is not None` — but `edit_file` deliberately re-uploads to an existing URL.
   - The method swallows the upload exception and logs it; `write_file` needs the 412 to propagate so it can be translated into `InvalidToolCallParameterException`.
   - `attachment.title` is used as the path segment, which is not the right input shape for "create at `files/{bucket}/generated-files/{filename}`".
     **Suggestion:** Either (a) add a separate, lower-level `AttachmentService.upload_text(url, content, *, if_match=..., if_none_match=...) -> FileMetadata` (or move that primitive into `DialFileService`) that does not silently swallow errors and is not Attachment-shaped, and have `write_file`/`edit_file` call it; or (b) rework `upload_attachment_to_core` so it can be driven by an explicit URL + raw bytes without the current `if attachment.url is None and attachment.data` short-circuit, and document the new contract for existing callers (REST tool, MCP tool — `_rest_api_tool.py:102`, `_mcp_tool.py:194`). Either way, the doc should name the method that actually exists post-change, not just "extended `upload_attachment_to_core`".

4. **Forward reference to `large_tool_responses.md`.** The doc references `large_tool_responses.md` twice (Error Handling table footnote and *Tests* section) and assumes that design defines `excluded_tools` containing `read_file_lines`/`search_in_file`. The actual file in the repo is `docs/designs/large_tool_responses.local.md` and it is in pre-draft state — no Status field, no Proposed Design, only an Open Questions list ("file search, read lines, read characters enough?"). There is no `excluded_tools`, no `LargeResponseProcessor` in code (`src/quickapp/tool_call_result_offload/` is empty save for `__pycache__`), and no committed contract for the file-tools design to depend on.
   **Suggestion:** Either (i) downgrade the dependency: state that `read_file_lines`/`search_in_file` are *intended to be excluded from offload* and reference the future design without claiming a default that does not exist yet, or (ii) add `large_tool_responses` (or the equivalent) to the **Dependencies** header field and block this design's approval on that one shipping first. The current "None" in *Dependencies* is misleading given the doc's reliance on offload internals.

### Suggestions

1. **Use Cases — UC-6 vs. error handling row "LLM requests an oversized slice".** UC-6 says cache is keyed by `SHA256(url)` with a 10 MB per-file limit (matches `DialFileService.__content_size_limit`, `dial_file_service.py:21`). The Error Handling row says oversized slice content "fills the context directly — expected self-correction." It is worth also calling out the *upstream* 10 MB cap: any file larger than that fails at download time with a `ValueError` from `DialFileService`, before `read_file_lines` ever sees it. The LLM will see a less-helpful error than the design implies.
   **Suggestion:** Add an explicit row for "file exceeds 10 MB download limit" → translate the `ValueError` into a clearer `InvalidToolCallParameterException` (or a dedicated tool error) with the limit in the message.

2. **Component 3 (`search_in_file`) Algorithm step 4 — `"No matches found."` content-type.** The "Configuration / Usage Examples" section shows the literal string `"No matches found."`, but the algorithm and Component 3's return shape don't pin down whether that is wrapped in a `ToolCallResult` (it should be, for consistency with other tools and stage display) or returned raw.
   **Suggestion:** State explicitly: `ToolCallResult(content="No matches found.", content_type="text/plain")`.

3. **Component 5 (`edit_file`) — write-back path interaction with the request-scoped file cache.** `DialFileService` caches downloads in `StateHolder._file_data_dict` keyed by `SHA256(url)` (`state_holder.py:36-43`). After a successful `edit_file`, the cached bytes for that URL are stale; subsequent same-turn `read_file_lines` / `search_in_file` calls will return pre-edit content.
   **Suggestion:** State the post-edit cache invalidation contract: either `edit_file` invalidates/overwrites the cache entry for the same URL (preferred, via a new `StateHolder` method), or this is documented as expected and the LLM is told to re-read after edit. UC-6 currently says caching is good; UC-7 is silent on cache invalidation.

4. **Out of Scope — case for omitted alternatives.** The "Combined `file_query(mode=...)` tool" rejection is well-argued, but the README of `docs/designs/` ("Name the trade-offs") would be served by adding a brief note on why `read_file_lines` and `search_in_file` are separate tools rather than a single `read_file(file_url, *, lines=None, search=None)` with optional parameters — the same orthogonality argument as for `file_query` applies here and is the clearest defence of the two-tool split.

### Nits

1. **Header metadata.** Other approved designs in this directory carry an `Owner` field; this one omits it. `template.md` doesn't strictly require it, but matching existing approved docs (e.g., `dial_prompts_as_skills.md`, `configurable_timeouts.md`) helps reviewers route follow-up questions.

2. **Component 8 (`_tool_configs.py`) vs. predefined-config convention.** The repo's other internal tool (`internal_code_execution_python_interpreter`) is configured via `config/predefined/tool/py_interpreter.json` and a toolset entry, not a Python module of `OpenAiToolConfig` instances. If `FileToolingModule` is going to construct `OpenAiToolConfig` in Python instead, that is a deviation from the existing pattern and worth a one-line justification — or change to JSON. Closely tied to blocking issue #1.

3. **Out of Scope — duplicate "Conditional / soft delete" entry.** The bullet list mentions "Conditional / soft delete" once in its own bullet and again under "Directory operations, multi-file search, hard limits on read parameters". The latter line also reads as a catch-all dump rather than three distinct deferrals — split into individual bullets or remove.

4. **Component 6 (`delete_file`) — 404 framing.** Step 3 says 404 "propagate[s] as a tool-call error (LLM-visible)". For consistency with how `write_file`/`edit_file` translate 412 into `InvalidToolCallParameterException`, consider translating 404 ("file not found") into the same shape so the LLM sees a uniform error format.

---

## Review Notes — Round 3

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-04-26

### Verdict

`Blocking issues must be addressed`.

Round 1's structural issues are well-resolved: `FileToolingModule`'s registration story is now explicit, `download_file_with_etag` matches the SDK, `upload_text` lives on `DialFileService` (and `AttachmentService` is left alone), the offload dependency is reframed as forward-looking, and the unique-match / cache-invalidation / 404-uniformity nits are folded in cleanly. What blocks approval is the three open items the author flagged in their own Round 2 self-review (none of them yet reflected in the design body), plus a couple of small regressions introduced during Revision 1.

### Blocking issues

1. **Author's Round 2 #1 — `write_file` cannot target subdirectories.** UC-3 and Component 4 hard-code the path to `files/{bucket}/generated-files/{filename}`. The author wants the ability to namespace agent output (e.g., `new-module-files/...` or a sub-folder under `generated-files/`), but the current parameter shape does not allow it (`filename` is explicitly "no path separators").
   **Suggestion:** Pick one of two shapes and write it down explicitly:
   - **Caller-supplied namespace** — add an optional `subdirectory: str | None` parameter (validated as a single safe segment, no `/`, no `..`), so the URL becomes `files/{bucket}/generated-files/{subdirectory}/{filename}`. Keeps the `generated-files/` umbrella; gives the LLM (or a calling module) one extra axis of organisation.
   - **Per-module namespace** — instead of (or in addition to) an LLM-controlled segment, let the *registering module* declare its namespace (e.g., `FileToolingModule(namespace="agent-notes")`), so that future modules wiring file tools can land their files under their own subdirectory without touching the LLM-facing schema. This is the safer default if the goal is operator-level partitioning rather than LLM-level organisation.
   Either way, the doc should state which one is in scope for v1, justify the choice, and update UC-3, Component 4 (parameter table + algorithm step 3), the JSON schema in *Configuration / Usage Examples*, and the *Out of Scope* / *Migration* sections accordingly. As written, UC-3 contradicts the author's stated requirement.

2. **Author's Round 2 #3 — `delete_file` has no client-side guardrail against unintended deletions.** Component 6 explicitly defers protection to DIAL's permission model ("This tool does not artificially restrict deletion to `generated-files/`"). The author's Round 2 suggestion is to add a mechanism. Today, an LLM that has any `file_url` it has seen in the conversation can issue an unconditional hard delete — including user uploads, prior tool outputs, or anything visible in attachments. A single LLM hallucination wipes the file with no recovery (the doc itself notes "Hard delete; no undo").
   **Suggestion:** Pick one mechanism and document it; do not leave this as "DIAL will handle it". Reasonable options, in increasing strictness:
   - **(a) Path-scoped allowlist** — `delete_file` succeeds only when `file_url` falls under `generated-files/` (or under the per-module namespace from blocking #1). Reject anything else with `InvalidToolCallParameterException("file_url", "delete is restricted to agent-generated files")`. Cheapest to implement; aligns with the existing distinction in Component 4.
   - **(b) Same-session creation guard** — track URLs created via `write_file` in `StateHolder`, allow `delete_file` only on those URLs within the same request. Tighter, but loses cross-turn / cross-session deletion of older agent files.
   - **(c) Two-phase confirm** — first `delete_file` call returns a confirmation token + summary; only a second call with the token executes the delete. Most defensive but adds an extra LLM round-trip and tool-shape complexity.
   Whatever is picked, the doc should explain the rejected alternatives in the design notes (mirroring how unique-match was justified for `edit_file`), and the *Out of Scope* "Conditional / soft delete" bullet should be reconciled with the new guardrail.

### Suggestions

1. **Author's Round 2 #2 — UC-4 framing.** The author's stated intent is "no overwrite path; use `edit_file`". The design *already* enforces this via `If-None-Match: *`, but UC-4's *Outcome* line ("can choose a different filename **or explicitly decide to re-write in a follow-up turn**") plants the idea that a re-write path exists. There is no such path in v1. Tighten the wording: the LLM's options are (i) pick a different filename, or (ii) edit the existing file via `edit_file`. Drop the "re-write in a follow-up turn" phrasing. Also worth a one-liner in Component 4's design notes: "There is no overwrite tool. Modifications to existing files go through `edit_file`."

2. **Header `Dependencies` field is malformed.** Line 5 reads `- **Dependencies:**: - ` — an extra colon and a bare dash with nothing after it. Author Response — Round 1 says "Added to `Dependencies` header" (in response to Round 1 Blocking #4), but the actual content was lost during the edit. Either replace with `- None` (and accept that the offload dependency is forward-looking, as the body now states), or list the offload design explicitly as `- [large_tool_responses](large_tool_responses.local.md) (forward dependency; file tools ship without offload integration; offload integration lands when that design is approved)`.

3. **`generated-files/` is now a load-bearing prefix in two places.** Component 4 puts files there; Component 6's design notes name-check it. If blocking #2 is resolved with option (a) — path-scoped delete — the `generated-files/` prefix becomes a hard-coded constant referenced from at least three call sites (`_write_file_tool`, `_delete_file_tool`, possibly `_base_file_tool`). Worth pulling into a single constant in `_base_file_tool.py` (or in `FileToolingModule`) and naming it in the design so reviewers know where it lives.

4. **`edit_file` return value still does not include the attachment.** Component 5 step 7 says "No attachment — the URL is unchanged; returning it as text is sufficient." That is reasonable for the LLM, but it means the DIAL UI's *Attachments* panel will not refresh after an edit, even though the file content has changed. Worth either (i) noting this explicitly as an accepted UX trade-off, or (ii) re-emitting the attachment so the UI surfaces the same URL (which is harmless on the client side and matches `write_file`'s shape).

### Nits

1. **Status field convention.** Header reads `Draft (Revision 1)`. Other approved docs in this directory use plain `Draft` / `Approved` / `Implemented` / `Superseded` per the lifecycle table in `docs/designs/README.md`. Move "Revision 1" out of `Status` — either drop it (the review-notes rounds already encode the revision history) or add a separate `- **Revision:** 1` line. As written, it doesn't match the four documented statuses.

2. **Inconsistent Review Notes heading style.** Round 2 uses `## Review Notes — Round 2` (ASCII hyphen) while Round 1 uses `## Review Notes — Round 1` (em dash). Pick one. The skill template specifies the em-dash form.

### Changes since previous round

Tracking the four blocking and four suggestion items from Round 1 (Andrii's Round 2 was a separate self-review and did not address Round 1; its three suggestions are now Round 3 blocking items #1, #2, and suggestion #1).

- **Round 1 Blocking #1 (Component 7 registration):** **resolved.** Component 7 now spells out `@multiprovider` contribution to `list[StagedBaseTool]`, no `InternalToolSet` opt-in, preview-gated. Component 8 design note justifies Python-vs-JSON config.
- **Round 1 Blocking #2 (`edit_file` etag):** **resolved.** Algorithm step 1 routes through `DialFileService.download_file_with_etag` which calls `get_metadata` + `download_file`; SDK header limitation noted inline.
- **Round 1 Blocking #3 (`AttachmentService` extension):** **resolved.** `AttachmentService` is unchanged. New `DialFileService.upload_text` with `if_none_match` / `if_match` is documented in Component 4. The three problems with `upload_attachment_to_core` are listed.
- **Round 1 Blocking #4 (`large_tool_responses` forward reference):** **partially addressed.** Body now says "once that design ships" and Tests section defers the integration. The `Dependencies` header was *intended* to list the dependency but actually contains `- **Dependencies:**: - ` (see Round 3 Suggestion #2).
- **Round 1 Suggestion #1 (10 MB limit):** **resolved.** New Error Handling row translates the `ValueError` into `InvalidToolCallParameterException`.
- **Round 1 Suggestion #2 (`No matches found.` shape):** **resolved.** Step 4 now wraps in `ToolCallResult(...)`.
- **Round 1 Suggestion #3 (post-edit cache invalidation):** **resolved.** UC-7, Component 5 algorithm step 7, and Component 5 design notes all specify cache eviction; new `DialFileService.invalidate_cache` listed in *Modified files*.
- **Round 1 Suggestion #4 (two-tool justification):** **resolved.** Folded into the *Combined `file_query`* Out-of-Scope bullet.
- **Round 1 Nits #1–#4:** **resolved** (Owner field, Python vs JSON config rationale, Out-of-Scope bullets de-duplicated, `delete_file` 404 → `InvalidToolCallParameterException`).
