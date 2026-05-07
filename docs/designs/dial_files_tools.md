# Design: DIAL Files Tools

- **Status:** Draft
- **Owner:** Andrii Novikov
- **Supersedes:** [file_tools.md](file_tools.md)

## Problem Statement

The previous iteration ([`file_tools.md`](file_tools.md), Status: Implemented) shipped five **text-only** tools (`read_file_lines`, `search_in_file`, `write_file`, `edit_file`, `delete_file`) anchored to a hard-coded `generated-files/` subdirectory under the bucket. Real-world testing surfaced two gaps:

- **No discovery.** Agents can read/edit files only when they already know the URL. There is no `ls` primitive, so workflows that need to find an existing artifact (a previously written report, a user-uploaded folder) are impossible. The agent can write a file, lose track of the URL, and have no way to recover it.
- **Write surface is too narrow.** The `generated-files/` constraint, the lack of nested paths, and the single hard-coded `text/plain` content type mean agents can only produce flat-namespace plain-text files. They cannot organize their working surface into folders or write files of other text types (`text/markdown`, `text/csv`, `application/json`) that downstream consumers (renderers, parsers) rely on for correct handling.

Both gaps prevent agents from using DIAL file storage as a real working surface. This design generalizes the toolkit: agents get a discovery primitive, can organize files into nested directories, can pick the content type, and can explicitly opt into overwriting an existing file.

## Design Goals

- Expose a small, orthogonal set of **DIAL files tools** to the LLM: list a folder, read a slice, search for a substring, edit by string replacement, write a new (or overwrite an existing) text file, delete a file.
- Treat appdata isolation as the safety boundary. The previous design layered `generated-files/` on top of the bucket as redundant safety; with appdata always populated in our deployments, the subdir is unnecessary and obscures the more powerful surface.
- Allow nested paths and caller-chosen content types so agents can produce structured outputs (folders of CSVs, a report set, a JSON manifest plus its assets).
- Default to safe behavior (`overwrite=False`) but make the destructive path explicit and reachable.
- Keep the read/search/edit contracts byte-identical to the previous design — there is no reason to churn them.
- Be preview-gated. No footprint when the feature flag is off.
- Path-traversal-restrict every appdata-anchored operation. The agent cannot escape its appdata namespace via constructed `..` paths.

---

## Use Cases

### UC-1: Agent lists the immediate contents of a folder

**Trigger:** The LLM calls `list_files(path="files/{appdata}/reports/", max_depth=1)`.\
**Behavior:** The tool calls `DialFileService.list_folder(folder_url, max_depth=1)`, which wraps `dial_client.metadata.get("files", folder_url)` and returns only the immediate children. The tool formats the response as a compact text listing.\
**Outcome:** The LLM sees one entry per child (file or folder) with name, type, size, and URL.

### UC-2: Agent lists a folder recursively, depth-bounded

**Trigger:** `list_files(path=..., max_depth=3)`.\
**Behavior:** The service walks the tree, calling `metadata.get("files", folder_url)` for each subfolder up to `max_depth` levels. Folder entries beyond the depth bound are listed by name but not expanded (so the LLM knows they exist and can drill down explicitly).\
**Outcome:** A bounded, traversable listing — the LLM gets enough to navigate without the risk of an unbounded recursion on a deep tree.

### UC-3: Agent writes into a nested path (default content type)

**Trigger:** `write_file(path="reports/2026-Q1/summary.md", content="...")`.\
**Behavior:** The tool validates `path` against path traversal, resolves to `files/{appdata}/reports/2026-Q1/summary.md`, and uploads with `If-None-Match: *`. `content_type` defaults to `"text/plain"`. DIAL creates the implicit `reports/` and `2026-Q1/` folders.\
**Outcome:** A new plain-text file lands at the nested URL; the URL is returned in the `ToolCallResult` along with an `Attachment` so the file appears in the DIAL UI.

### UC-4: Agent writes a non-default content type (flat path)

**Trigger:** `write_file(path="orders.csv", content="id,total\\n1,42", content_type="text/csv")`.\
**Behavior:** The path is intentionally flat — this use case isolates `content_type` selection, not nesting. The upload propagates `text/csv` as the MIME type. Downstream UI renders the file as a CSV preview rather than raw text.\
**Outcome:** The file is stored with the correct content type so renderers and consumers handle it appropriately.

### UC-5: Agent overwrites an existing file

**Trigger:** `write_file(path="reports/summary.md", content="...", overwrite=True)`.\
**Behavior:** The tool fetches the current ETag via the existing metadata path, then uploads with `If-Match: <etag>`. If the file does not exist yet, the upload falls through to create. If a concurrent writer modified the file between the metadata fetch and the upload, DIAL returns `412 Precondition Failed` and the tool surfaces a clear error.\
**Outcome:** The file at the same URL contains the new content. Subsequent same-turn reads see the update (cache invalidated). On `EtagMismatchError`, the LLM is told to re-read and retry.

### UC-6: Agent reads a line range from a stored file

**Trigger:** `read_file_lines(file_url=..., start_line=0, end_line=50)`.\
**Behavior / Outcome:** Unchanged from the previous design. Read tools accept any accessible URL (appdata or otherwise).

### UC-7: Agent searches for a substring

**Trigger:** `search_in_file(file_url=..., pattern="ERROR", context_lines=2, case_insensitive=True)`.\
**Behavior / Outcome:** Unchanged from the previous design.

### UC-8: Agent edits an existing file

**Trigger:** `edit_file(file_url=..., old_string="foo", new_string="bar")`.\
**Behavior / Outcome:** Unchanged from the previous design (unique-match string replacement, ETag-guarded upload, post-edit cache invalidation).

### UC-9: Agent deletes an arbitrary file in appdata

**Trigger:** `delete_file(file_url="files/{appdata}/reports/old.md")`.\
**Behavior:** The tool calls `dial_client.files.delete(file_url)`. Appdata isolation constrains the blast radius; the tool no longer enforces a `generated-files/` prefix or any client-side path validation.\
**Outcome:** The file is removed. Subsequent reads on that URL fail.

### UC-10: Agent provides an invalid path

**Trigger:** `write_file(path="../escape.md", ...)` or `write_file(path="/absolute.md", ...)` or `write_file(path="foo//bar", ...)`.\
**Behavior:** The path validator raises `InvalidToolCallParameterException("path", ...)` before any IO.\
**Outcome:** The LLM gets a precise, actionable error and self-corrects.

### UC-11: Repeated reads of the same file in one request

**Trigger:** Multiple `read_file_lines` / `search_in_file` calls against the same `file_url`.\
**Behavior / Outcome:** Unchanged — `DialFileService` caches the download per request.

---

## Proposed Design

### Component 1: `_DialFileTool` base class

**What:** A thin internal base class that holds the common dependencies (`DialFileService`, the `_dial_client` for bucket resolution, stage-wrapper plumbing) and extends `StagedBaseTool`. Concrete tools implement `_run_in_stage_async`.

**Owner:** `src/quickapp/dial_files_tooling/_base_file_tool.py`

**Semantics:**

- Provides `self._dial_file_service` to subclasses (download + upload + cache primitives).
- Provides an `async _resolve_appdata_url(path: str) -> str` helper that:
  1. Validates `path` is a non-empty string.
  2. Rejects any leading `/`, any literal `../` substring, any segment equal to `..`, any empty segment (e.g. `foo//bar`), and trailing whitespace. All failures raise `InvalidToolCallParameterException("path", "...")` with a precise message.
  3. Calls `await dial_client.my_appdata_home()`. If it returns `None`, raises `InvalidToolCallParameterException("path", "appdata namespace is not available in this deployment; write/delete tools are disabled")`. `my_appdata_home()` is the SDK's high-level helper; it caches the bucket response internally, so repeated calls within a request do not incur additional HTTP round-trips. Read/search/list tools never call this helper, so they remain functional even when appdata is missing.
  4. Returns `f"files/{home}/{path}"` where `home = str(appdata_home)`. **Trailing slash is preserved as-is**: a trailing `/` on the input means a folder URL (used by `list_files`); no trailing `/` means a file URL (used by `write_file`). The helper does not add or strip slashes — the caller controls the shape.
- The previous design's `GENERATED_FILES_ROOT` constant is removed.

`AttachmentService` is **not** a base-class dependency — `write_file` constructs its `Attachment` directly from the URL returned by `DialFileService.upload_text`.

---

### Component 2: `list_files`

**What:** Internal tool that lists the entries under a folder in DIAL storage, with depth-bounded recursion.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | Folder URL or relative path. Folder URLs end with `/`. |
| `max_depth` | integer | no | `1` | Recursion depth. `1` = immediate children only. Must be `>= 1` and `<= 10`. |

**Algorithm:**

1. Validate `max_depth` in `[1, 10]` — else raise `InvalidToolCallParameterException("max_depth", "...")`.
2. Normalize `path` into a folder URL of shape `files/{bucket}/{relative}/`:
   - If `path` starts with `files/`, treat it as already-resolved.
   - Otherwise, ensure it ends with `/` (DIAL Core requires the trailing slash for folder listing — append one if missing) and pass through `_resolve_appdata_url(path)` to anchor under appdata.
3. Call `DialFileService.list_folder(folder_url, max_depth)`. The service calls `dial_client.metadata.get("files", folder_url)` directly — `metadata.get` joins its second argument onto `/v1/metadata/`, so the input must already include the `files/` segment; the `files/{bucket}/{relative}/` URL is passed through unchanged. (The `e2e_runner.py` helper bypasses the SDK and hits `{api_url}metadata/{folder}/` directly via `httpx`; we use the SDK path here for consistency with every other DIAL call in the codebase.)
4. Format the response as a compact text listing, one entry per line:
   ```
   D    -      reports/                          files/{appdata}/reports/
     F  1234   summary.md                        files/{appdata}/reports/summary.md
     F  56789  data.csv                          files/{appdata}/reports/data.csv
     D    -    images/                           files/{appdata}/reports/images/
       F  2048 logo.png                          files/{appdata}/reports/images/logo.png
   ```
   - Column 1: `F` (file) or `D` (folder).
   - Column 2: size in bytes (or `-` for folders).
   - Column 3: name (with trailing `/` for folders).
   - Column 4: full URL — included so the LLM can hand it directly to `read_file_lines` / `search_in_file` / `edit_file` / `delete_file` without reconstructing it. This costs a few tokens per row but removes a class of LLM-side bugs.
   - **Indentation: two spaces per depth level**, applied to the name column only (URL stays left-aligned in column 4).
   - Folders at the depth bound are listed by name with no expansion (so the LLM knows they exist and can drill down explicitly with another `list_files` call).
5. Return `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_list_files_tool.py`

**Design notes:**

- **Why text output over JSON.** Tabular text is cheaper in tokens and easier for the LLM to scan. The URL column is included inline (rather than only via structured `attachments` metadata) because the rest of the file-tools surface returns text content as the primary signal, and there is no precedent in the codebase for tools surfacing structured `attachments` for the LLM to consume directly.
- **Depth bound exists.** Without it, an LLM could trigger an unbounded walk on a deep user-uploaded folder. Each subfolder at each depth level requires one metadata call to Core; a depth-D listing over a tree with W subfolders per level costs O(W^D) calls in the worst case — the `max_depth <= 10` bound limits this. `max_depth <= 10` is generous in practice and safe in the worst case.
- **Pagination is out of scope.** When folder sizes warrant it, this tool can grow `next_token` semantics without breaking the contract (additive optional param + sentinel in the listing).
- **Reuse.** `DialFileService.list_folder` mirrors the recursion shape used in `src/tests/integration_tests/test_runner/e2e_runner.py`. That helper hits the metadata endpoint via raw `httpx`; the service uses the SDK's `dial_client.metadata.get("files", ...)` instead so the call participates in the same auth/header plumbing as every other DIAL call in the codebase. The recursion shape (depth-bounded BFS over `items`) is the part that's reused.

---

### Component 3: `read_file_lines`

**What / Parameters / Algorithm:** Unchanged from the previous design. See [`file_tools.md`](file_tools.md) Component 2.

**Owner:** `src/quickapp/dial_files_tooling/_read_file_lines_tool.py`

---

### Component 4: `search_in_file`

**What / Parameters / Algorithm:** Unchanged from the previous design. See [`file_tools.md`](file_tools.md) Component 3.

**Owner:** `src/quickapp/dial_files_tooling/_search_in_file_tool.py`

---

### Component 5: `write_file`

**What:** Internal tool that creates or overwrites a UTF-8 text file in DIAL appdata. Path-traversal-restricted; caller chooses the content type; overwrite is opt-in.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | Relative path under appdata. Forward slashes for nesting. **Rejected:** leading `/`, any segment equal to `..`, any literal `../` substring, empty segments (`foo//bar`), trailing whitespace. |
| `content` | string | yes | — | UTF-8 text content. |
| `content_type` | string | no | `"text/plain"` | MIME type sent to DIAL on upload. Common: `text/markdown`, `text/csv`, `application/json`. |
| `overwrite` | boolean | no | `false` | If `false`, fails when the target already exists. If `true`, replaces an existing file (ETag-guarded). |

**Algorithm:**

1. Resolve `url = _resolve_appdata_url(path)`. (Validation + appdata resolution happen here; failures raise before any IO.)
2. Branch on `overwrite`:
   - `overwrite == false`: call `DialFileService.upload_text(url=url, content=content, content_type=content_type, if_none_match="*")`. On `EtagMismatchError` (HTTP 412) → `InvalidToolCallParameterException("path", "file already exists: {url}; pass overwrite=True to replace")`.
   - `overwrite == true`:
     - Try `dial_client.files.get_metadata(url)` to read the current ETag.
       - On `ResourceNotFoundError` (HTTP 404, no prior file): call `upload_text(..., if_none_match="*")` — clean create. (Falls through; not an error.)
       - On success: call `upload_text(url=url, content=content, content_type=content_type, if_match=etag)`.
         - On `EtagMismatchError` (HTTP 412): `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`.
     - On a successful overwrite, call `DialFileService.invalidate_cache(url)` so same-turn reads see the new bytes.
3. Build an `Attachment` pointing at `url` (so the DIAL UI shows the file).
4. Return `ToolCallResult(content=f"File written: {url}", content_type="text/plain", attachments=[attachment])`.

**Owner:** `src/quickapp/dial_files_tooling/_write_file_tool.py`

**Design notes:**

- **Overwrite is opt-in.** Default safety net (`If-None-Match: *`) preserved from the previous design. The `overwrite=True` path is the explicit, ETag-guarded escape hatch — no silent clobber.
- **Why one tool, not two.** A separate `overwrite_file` tool was considered. Folding the toggle into a parameter keeps the surface small; the LLM sees one tool with a clearly named optional flag.
- **`content_type` is caller-controlled.** Sniffing was rejected: the agent already knows what it is producing, and sniffing risks misclassification (e.g., a JSON file beginning with `<` due to embedded HTML). Default `text/plain` matches the previous behavior exactly. Client-side validation is intentionally minimal — there is no MIME-type allowlist (the set is open-ended) — but the value is rejected if it contains `\n` or `\r` to prevent header-injection-style abuse before the string reaches DIAL's HTTP layer.
- **Path-traversal validation runs first.** No partial work — invalid path → no IO, no cache mutation. Validation errors are precise so the LLM can retry without guessing.
- **`appdata` is required.** The base-class helper raises a descriptive error when the bucket response has no appdata. In our supported deployments this never fires; if it does, the agent gets a clear signal rather than silently writing into the user's personal bucket.
- **`edit_file` still exists.** `write_file(overwrite=True)` is for full rewrites; `edit_file` is for surgical patches with concurrency safety. The two are complementary, not redundant.
- **`get_metadata` does double duty.** In the `overwrite=True` branch the metadata fetch serves two purposes: (a) obtain the ETag for the conditional upload, and (b) detect "no prior file" via the 404 so the call falls through to a clean create. There is no separate existence probe — both signals come from the same call.
- **Alternative considered: try-create-then-retry.** A simpler shape would be: always call `upload_text(if_none_match="*")` first; on 412, call `get_metadata` for the ETag and retry with `if_match=etag`. That removes the metadata round-trip on the common new-file path. Rejected for v1 because the typical `overwrite=True` call is an explicit replacement (the agent expects the file to exist), so the optimistic-create path adds complexity that pays off only for edge cases. Worth revisiting if profiling shows the metadata call dominates write latency.

**`DialFileService.upload_text` extension.** The existing method is extended with a `content_type` keyword (default `"text/plain"`, so existing callers — `_EditFileTool` — are unaffected). The MIME is propagated to the underlying `dial_client.files.upload(file=(name, bytes, mime))` call.

---

### Component 6: `edit_file`

**What / Parameters / Algorithm:** Unchanged from the previous design. See [`file_tools.md`](file_tools.md) Component 5.

**Owner:** `src/quickapp/dial_files_tooling/_edit_file_tool.py`

---

### Component 7: `delete_file`

**What:** Internal tool that removes a file from DIAL storage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file_url` | string | yes | URL of the file in DIAL storage to delete. |

**Algorithm:**

1. Call `dial_client.files.delete(file_url)`.
2. On success → `ToolCallResult(content=f"Deleted: {file_url}", content_type="text/plain")`.
3. On `ResourceNotFoundError` (HTTP 404) → `InvalidToolCallParameterException("file_url", "file not found: {file_url}")` — same shape as `write_file`/`edit_file` errors.
4. Other errors → propagate as tool-call errors.

**Owner:** `src/quickapp/dial_files_tooling/_delete_file_tool.py`

**Design notes:**

- **No client-side validation.** Appdata isolation is the safety boundary; an LLM running in app context cannot delete files outside its own appdata namespace. The previous `generated-files/` guard, and an earlier draft's `..`-substring check, are both removed: the substring check would have rejected legitimate filenames containing `..` (e.g. `v1.2..3/log.txt`) and was redundant with appdata isolation, not a real safety layer (it could not prevent escape, only block one syntactic form).
- **No ETag guard.** Delete is unconditional within the appdata scope; the concurrency window for delete is rarely meaningful.
- **No soft delete.** DIAL's `files.delete` is a hard delete. No undo.

---

### Component 8: `DialFilesToolingModule` (DI wiring)

**What:** `injector.Module` that:

- Binds `_FileStageWrapper`, `_ListFilesTool`, `_ReadFileLinesTool`, `_SearchInFileTool`, `_WriteFileTool`, `_EditFileTool`, `_DeleteFileTool` in `request_scope`.
- Contributes all six tools to the shared `list[StagedBaseTool]` multiprovider via its own `@multiprovider`-decorated provider method (same pattern as the prior `TextFileToolingModule`).
- Tools are gated per app via `app_config.features.dial_files`. The resolution logic is unchanged from the previous design — `enabled_tools="all"` returns every tool; a list returns only the matching subset.
- Is **preview-feature-gated** via `@preview_module` — when `ENABLE_PREVIEW_FEATURES=false`, nothing is bound and the tools are invisible to the LLM.

**Owner:** `src/quickapp/dial_files_tooling/dial_files_tooling_module.py`

**Registration:** Added to the module list in `src/quickapp/app_factory.py`.

---

### Component 9: Tool configs and stage display

**What:** `OpenAiToolConfig` definitions with JSON-schema parameters, plus `ToolDisplayConfig` for the DIAL stage UI.

**Highlights:**
- Tool prefix renamed from `internal_text_file_` to `internal_file_`. Names: `internal_file_list`, `internal_file_read_lines`, `internal_file_search`, `internal_file_write`, `internal_file_edit`, `internal_file_delete`.
- Stage titles: `List files`, `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`.
- The `file_url` / `path` parameter renders in the stage as `**File:** {basename}` (last path segment only) so the UI stays compact.

**Owner:** `src/quickapp/dial_files_tooling/_tool_configs.py`

---

### Component 10: Per-app config (`features.dial_files`)

**What:** A new `DialFilesConfig` field on the existing `Features` container in `src/quickapp/config/application.py`. Replaces the prior `text_file_tools` field of the same shape.

**Schema:**

```python
# src/quickapp/config/dial_files.py
from typing import Literal
from pydantic import BaseModel, Field

DialFilesToolName = Literal[
    "internal_file_list",
    "internal_file_read_lines",
    "internal_file_search",
    "internal_file_write",
    "internal_file_edit",
    "internal_file_delete",
]

class DialFilesConfig(BaseModel):
    enabled_tools: Literal["all"] | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['internal_file_read_lines', 'internal_file_search'])."
        ),
    )
```

**Wiring on `Features`:**

```python
# src/quickapp/config/application.py
class Features(BaseModel):
    timestamp: TimestampConfig | None = PreviewField(...)
    file_loading: FileLoadingConfig = Field(...)
    dial_files: DialFilesConfig | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Built-in DIAL files tools (list / read / search / write / edit / delete).",
    )
```

**Resolution in `DialFilesToolingModule`:** Same shape as the previous design's resolver, but reads `app_config.features.dial_files` and matches against `DialFilesToolName`.

**Design notes:**

- **Default semantics.** `features.dial_files` defaults to `None` — file tools are off unless the app author explicitly opts in. Once enabled, `enabled_tools` defaults to `"all"`.
- **Preview gating.** `dial_files` is a `PreviewField`. When `ENABLE_PREVIEW_FEATURES=false`, `nullify_preview_fields` clears it back to `None` and the module contributes nothing.
- **Future knobs.** `DialFilesConfig` is the natural home for additions like `max_file_size_bytes`, allow/deny path prefixes, a per-app `subdir` under appdata, or a default `content_type` override.

**Owner:** `src/quickapp/config/dial_files.py` and a small edit to `src/quickapp/config/application.py`.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Invalid `path` (empty, leading `/`, `..` segment, `../` substring, empty segment, trailing whitespace) | `InvalidToolCallParameterException("path", ...)` with the specific rule violated. |
| Appdata not available (`dial_client.my_appdata_home()` returns `None`) | `InvalidToolCallParameterException("path", "appdata namespace is not available in this deployment; write/delete tools are disabled")`. Read/search/list still work. |
| `start_line < 0` or `end_line < start_line` (`read_file_lines`) | `InvalidToolCallParameterException` → surfaced to LLM. |
| `write_file(overwrite=False)` target already exists (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("path", "file already exists: {url}; pass overwrite=True to replace")`. |
| `write_file(overwrite=True)` concurrent modification (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`. |
| `write_file` `content_type` contains `\n` or `\r` | `InvalidToolCallParameterException("content_type", "must not contain newline characters")` — client-side, before any IO. |
| `write_file` otherwise-invalid `content_type` (e.g. malformed `type/subtype`) | Passed through to DIAL; surface DIAL's response if any. No client-side allowlist (the set of valid MIME types is open-ended). |
| `edit_file` `old_string` not found / matches multiple places / equals `new_string` | Unchanged from previous design. |
| `edit_file` conditional upload fails (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("file_url", "file changed concurrently; re-read and retry")`. |
| `list_files` target is not a folder | `InvalidToolCallParameterException("path", "not a folder: {url}")` if DIAL response shape indicates a file. |
| `list_files` target not found (`ResourceNotFoundError`, HTTP 404) | `InvalidToolCallParameterException("path", "folder not found: {url}")`. |
| `list_files` `max_depth < 1` or `max_depth > 10` | `InvalidToolCallParameterException("max_depth", "must be in [1, 10]")`. |
| `delete_file` target not found (`ResourceNotFoundError`, HTTP 404) | `InvalidToolCallParameterException("file_url", "file not found: {url}")`. |
| `file_url` missing or DIAL GET fails | Error propagates from `DialFileService`; the tool returns an error result. |
| File exceeds 10 MB download limit | `InvalidToolCallParameterException("file_url", "file is too large to read (limit: 10 MB)")`. |
| File is not valid UTF-8 (read/search/edit) | `UnicodeDecodeError` propagates; LLM sees the error. Binary files are out of scope. |

---

## Out of Scope

- **Rename / move / copy.** No primitive in the DIAL API; would be a download + upload + delete. Deferred — agents can substitute "write new + delete old".
- **Conditional / soft delete.** `delete_file` remains unconditional within appdata; ETag-guarded delete and trash/undo semantics are deferred.
- **Multi-edit in one call.** `edit_file` replaces a single unique `old_string` per invocation. Batching is deferred.
- **Binary / non-UTF-8 files.** Read/search/edit assume UTF-8 text. `write_file` accepts any `content_type` but content is still UTF-8-encoded text. Binary upload is not supported.
- **Regex search.** `search_in_file` ships with substring + `case_insensitive` only.
- **Character/byte offset reading.** Rejected: line-based addressing is more reliable for LLMs.
- **`upload_file` (fetch from external/DIAL URL).** Considered for this revision and deferred. The existing `AttachmentService` covers the internal upload path for tool-emitted attachments; a dedicated LLM-facing upload tool is not needed yet.
- **Pagination on `list_files`.** Deferred until folder sizes warrant it. Additive optional param + sentinel in the listing when introduced.
- **Recursive delete.** Out of scope — agents loop over a `list_files` result to delete trees explicitly. Reduces blast radius.
- **MIME sniffing for `write_file`.** Caller-provided only. Sniffing risks misclassification.
- **LLM-controlled subdirectories under a fixed root.** The agent now controls the full path under appdata. A per-app `subdir` config field can be added on `DialFilesConfig` if a deployment wants to namespace agents further.
- **Hard limits on read parameters** (truncation, pagination tokens). Deferred — the 10 MB download cap is the only enforced limit in v1.

---

## Configuration / Usage Examples

### Tool schemas (abridged)

```jsonc
// list_files
{
  "name": "internal_file_list",
  "description": "List entries (files and folders) under a folder in DIAL storage. Depth-bounded recursion.",
  "parameters": {
    "path":      {"type": "string",  "description": "Folder URL or relative path. Folder URLs end with '/'."},
    "max_depth": {"type": "integer", "description": "Recursion depth. 1 = immediate children only. Range: [1, 10]. Default: 1."}
  },
  "required": ["path"]
}

// read_file_lines
{
  "name": "internal_file_read_lines",
  "description": "Read a range of lines from a file stored in DIAL. Use start_line and end_line (0-indexed, end exclusive).",
  "parameters": {
    "file_url":   {"type": "string",  "description": "URL of the file to read."},
    "start_line": {"type": "integer", "description": "First line to include (0-indexed)."},
    "end_line":   {"type": "integer", "description": "First line to exclude (0-indexed). Like Python slice end."}
  },
  "required": ["file_url", "start_line", "end_line"]
}

// search_in_file
{
  "name": "internal_file_search",
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
  "name": "internal_file_write",
  "description": "Create or overwrite a UTF-8 text file in DIAL appdata storage. Path is relative to appdata; nested paths allowed; '..' rejected. Default content_type is text/plain. overwrite=False fails on collision; overwrite=True replaces with ETag guard.",
  "parameters": {
    "path":         {"type": "string",  "description": "Path under appdata. Forward slashes for nesting. Rejected: leading '/', '..' segments, '../' substring, empty segments."},
    "content":      {"type": "string",  "description": "UTF-8 text content of the file."},
    "content_type": {"type": "string",  "description": "MIME type. Default: text/plain. Common: text/markdown, text/csv, application/json."},
    "overwrite":    {"type": "boolean", "description": "If true, replace an existing file. Default: false."}
  },
  "required": ["path", "content"]
}

// edit_file
{
  "name": "internal_file_edit",
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
  "name": "internal_file_delete",
  "description": "Delete a file from DIAL storage. Hard delete; no undo.",
  "parameters": {
    "file_url": {"type": "string", "description": "URL of the file to delete."}
  },
  "required": ["file_url"]
}
```

### `list_files` output format

```
D    -      reports/                          files/{appdata}/reports/
  F  1234   summary.md                        files/{appdata}/reports/summary.md
  F  56789  data.csv                          files/{appdata}/reports/data.csv
  D    -    images/                           files/{appdata}/reports/images/
    F  2048 logo.png                          files/{appdata}/reports/images/logo.png
```

Columns: type (`F`/`D`), size, name (indented two spaces per depth level, with trailing `/` for folders), full URL.

### `write_file` on success

```
File written: https://dial-storage/.../files/<appdata>/reports/2026-Q1/summary.md
```

### `write_file` on collision (overwrite=False)

```
InvalidToolCallParameterException: file already exists: https://dial-storage/.../files/<appdata>/reports/summary.md; pass overwrite=True to replace
```

### `write_file` on path traversal

```
InvalidToolCallParameterException: path must not contain '..'
```

### `delete_file` on success

```
Deleted: https://dial-storage/.../files/<appdata>/reports/old.md
```

### Per-app manifest

```jsonc
// All six tools enabled
{
  "features": {
    "dial_files": {}            // defaults: enabled_tools = "all"
  }
}

// Read-only research agent
{
  "features": {
    "dial_files": {
      "enabled_tools": [
        "internal_file_list",
        "internal_file_read_lines",
        "internal_file_search"
      ]
    }
  }
}

// File tools off (default)
// `features` is auto-populated by Features's default_factory even when omitted from
// the manifest, so both omitting `features` entirely and writing `"features": {}` result
// in file tools being off — `dial_files` is None in both cases.
{
  "features": {}
}
```

---

## Migration

### Breaking changes

- **Module rename:** `src/quickapp/text_file_tooling/` → `src/quickapp/dial_files_tooling/`. See *Summary of Changes / New files*.
- **Config-field rename:** `features.text_file_tools` → `features.dial_files`. Any in-flight manifest using the old key must be updated. No back-compat shim.
- **Tool-prefix rename:** `internal_text_file_*` → `internal_file_*`. Any saved chat history or manifest referencing the old names will not match. See *Summary of Changes / New tools exposed*.
- **`write_file` parameter rename and additions:** `filename` → `path`; `content_type` and `overwrite` added.
- **`delete_file` no longer enforces `generated-files/`.** Any caller relying on this guard for safety must migrate to the appdata isolation model.
- **Appdata is now required for write/delete.** `_WriteFileTool` (and the previous design) used `bucket = bucket_resp.appdata or bucket_resp.bucket`, silently falling back to the user's personal bucket when DIAL Core did not populate `appdata`. The new `_resolve_appdata_url` calls `dial_client.my_appdata_home()` and raises `InvalidToolCallParameterException` if it returns `None`. In our deployments QuickApps is always invoked as a DIAL application, so `appdata` is always populated; the breaking case is a deployment that calls QuickApps directly as a user (no app context). In that case, write/delete tools refuse to operate (read/search/list are unaffected). This is intentional — the old fallback could have written agent output into the user's personal upload bucket. If a future deployment needs the old fallback, add it as a `DialFilesConfig` opt-in.

The above bullets are acceptable because the feature is preview-gated and not GA.

### Non-breaking changes

- `DialFileService.upload_text` gains a `content_type` keyword (default `"text/plain"`, so existing `_EditFileTool` continues to work).
- `DialFileService` gains `list_folder` — additive.
- `AttachmentService` is unchanged.

---

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `dial_files_tooling/_base_file_tool.py` | `_DialFileTool` base class with `DialFileService` wiring; provides `_resolve_appdata_url(path)` with path-traversal validation. |
| `dial_files_tooling/_list_files_tool.py` | `list_files` implementation. |
| `dial_files_tooling/_read_file_lines_tool.py` | `read_file_lines` implementation (carried over). |
| `dial_files_tooling/_search_in_file_tool.py` | `search_in_file` implementation (carried over). |
| `dial_files_tooling/_write_file_tool.py` | `write_file` implementation: nested `path`, `content_type`, `overwrite`. |
| `dial_files_tooling/_edit_file_tool.py` | `edit_file` implementation (carried over). |
| `dial_files_tooling/_delete_file_tool.py` | `delete_file` implementation (path guard removed; no client-side validation — appdata isolation is the safety boundary). |
| `dial_files_tooling/_stage_wrapper.py` | Stage wrapper (carried over). |
| `dial_files_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all six tools; renamed prefix. |
| `dial_files_tooling/dial_files_tooling_module.py` | Preview-gated DI module; contributes tools; reads `app_config.features.dial_files`. |
| `config/dial_files.py` | `DialFilesConfig` model — `enabled_tools: Literal["all"] \| list[DialFilesToolName]`. |

### Modified files

| File | Change |
|------|--------|
| `dial_core_services/dial_file_service.py` | Add `list_folder(folder_url, max_depth=1)` (wraps `dial_client.metadata.get("files", folder_url)` with depth-bounded recursion). Extend `upload_text(...)` with `content_type` keyword (default `"text/plain"`). |
| `dial_core_services/attachment_service.py` | No changes. |
| `app_factory.py` | Register `DialFilesToolingModule` (replaces `TextFileToolingModule`). |
| `config/application.py` | Replace `text_file_tools: TextFileToolsConfig \| None` with `dial_files: DialFilesConfig \| None` as a `PreviewField` on `Features`. |

### New tools exposed to the LLM

- `internal_file_list(path, max_depth=1)`
- `internal_file_read_lines(file_url, start_line, end_line)` (carried over)
- `internal_file_search(file_url, pattern, context_lines=0, case_insensitive=False)` (carried over)
- `internal_file_write(path, content, content_type="text/plain", overwrite=False)`
- `internal_file_edit(file_url, old_string, new_string)` (carried over)
- `internal_file_delete(file_url)`

### Tests

- Unit: `src/tests/unit_tests/dial_files_tooling/` — all carried-over coverage from the previous design plus:
  - `list_files`: depth-1 listing, depth-N recursion (depth bound respected), folder-not-found (`ResourceNotFoundError`), target-is-not-a-folder, `max_depth` out of range, empty folder.
  - `write_file`: nested path success, path-traversal rejection (`..` segment, `../` substring, leading `/`, empty segment, trailing whitespace), `content_type` propagated to the upload call, `overwrite=False` collision (`EtagMismatchError` → `InvalidToolCallParameterException`), `overwrite=True` happy path, `overwrite=True` falls through to create when no prior file (`ResourceNotFoundError` on metadata), `overwrite=True` concurrent modification (`EtagMismatchError` → error), cache invalidated after overwrite, appdata-missing → descriptive error.
  - `delete_file`: success on arbitrary appdata path (no `generated-files/` requirement), `ResourceNotFoundError` (404) → `InvalidToolCallParameterException`.
  - `DialFileService.upload_text`: `content_type` defaults to `"text/plain"`, custom content type forwarded to `dial_client.files.upload`.
  - `DialFileService.list_folder`: flat folder, recursion respects `max_depth`, depth-bound folders listed but not expanded.

---

## Review Notes — Round 1

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-06

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-06). Awaiting Round 2 review.**

The design is coherent, well-scoped, and continues a strong tradition from `file_tools.md`. The `list_files` addition, the `path` + `content_type` + `overwrite` write surface, and the prefix rename are all sensible. However, three concrete items must be resolved before approval: (1) the `delete_file` `..` substring check rejects legitimate filenames containing `..`; (2) the `list_files` URL-shape contract is under-specified — the only existing reference implementation in the repo (`e2e_runner._search_file`) requires a fully-qualified `metadata/...` URL, not the `files/{appdata}/...` URL the design implies; and (3) the **appdata-required** posture is described as a no-op for our deployments, but the existing codebase consistently uses `bucket = bucket_resp.appdata or bucket_resp.bucket` as a fallback (4 callsites including the current `_WriteFileTool`) — silently dropping the `bucket` fallback is a behavioral change that deserves an explicit migration note. A handful of suggestions and nits follow.

### Blocking issues

1. **[Resolved]** **Component 7 / UC-9 / Error Handling — `delete_file` `..` check rejects valid filenames.**
   The algorithm states: "Reject `file_url` containing the literal `..` substring". Combined with UC-9's "validates the URL contains no `..` segment", the implementation will reject any URL whose filename or any segment legitimately contains the substring `..` (e.g., `files/{appdata}/v1.2..3/log.txt`, or any filename a previous tool happened to produce). The substring check is also redundant with the `_resolve_appdata_url` validator for write-side paths, but it is the *only* validation here for delete because `delete_file` takes a fully-qualified `file_url` and never passes it through `_resolve_appdata_url`.
   **Suggestion:** Either (a) split the URL on `/` and reject only segments that are exactly `..` (matching the write-side rule in `_resolve_appdata_url`), or (b) drop the check altogether and rely on appdata isolation as the doc itself argues for in Component 7's first design note ("the previous guard added a second layer that, with appdata always populated, was effectively dead code"). The current substring check is the worst of both worlds: looser than appdata isolation (it doesn't prevent escape, only the literal `..`) and false-positive-prone.

2. **[Resolved]** **Component 2 — `list_files` URL contract is under-specified vs. the only existing reference.**
   The design says `DialFileService.list_folder` "wraps `dial_client.metadata.get("files", folder_url)`" and references `e2e_runner.py` as the reference implementation. But `e2e_runner._search_file` constructs its `folder_url` as `f"{dial_client.api_url}metadata/{folder}/"` — a fully-qualified absolute URL, with the `metadata/` segment baked in. The design's UC-1 / UC-2 / Component 2 step 2 implies the input is a `files/{appdata}/...` URL (or a relative path resolved through `_resolve_appdata_url`). It is unclear whether `DialFileService.list_folder` is responsible for the `files/{appdata}/...` → `{api_url}metadata/{appdata}/.../` translation, or whether the calling tool does it, or whether the design is silently assuming the SDK accepts the `files/{appdata}/...` shape directly. Step 2 also says "with the trailing `/` preserved" — but `_resolve_appdata_url` is defined to return `f"files/{appdata}/{path}"` with no trailing slash handling specified.
   **Suggestion:** State the canonical input/output URL shape for `_resolve_appdata_url` (does it preserve a trailing `/`?), state the URL shape `DialFileService.list_folder` accepts, and state which component is responsible for the `metadata/`-prefix translation. Confirm the SDK call works with the chosen shape (either pin to a tested aidial-client version that accepts `files/...` or follow the e2e_runner pattern verbatim).

3. **[Resolved]** **Components 1, 5 / Migration — silently dropping the `bucket` fallback is a real behavioral change.**
   `_resolve_appdata_url` is specified to error out when `bucket_resp.appdata is None`. The current `_WriteFileTool` (and three other callsites: `display_content_processor.py`, `input_file_handler.py`, `attachment_service.py`) all do `bucket = bucket_resp.appdata or bucket_resp.bucket`. The doc rationalizes this as "appdata always populated in our deployments", but that is an operational claim, not a property of DIAL Core. If a deployment exists where `appdata` is `None`, the current code silently falls back to the user's bucket; the new code refuses to write/delete entirely. This is a behavioral change worth flagging in *Migration / Breaking changes* (or *Out of Scope* if the team is comfortable forcing the operational invariant). The Error Handling table mentions the new error but the Migration section does not.
   **Suggestion:** Add a Migration entry: "appdata is now required for write/delete; deployments without an `appdata` bucket lose write/delete tools (read/search/list still work)." Optionally verify with the Core team that this invariant is documented and enforced.

### Suggestions

1. **[Resolved]** **Component 5 — `overwrite=True` race window between `get_metadata` and `upload_text`.**
   The algorithm reads the ETag, then uploads with `If-Match`. The two calls are not atomic; if a writer races in between, the `If-Match` correctly catches it (412 → clear error). But the design should explicitly call out that the metadata fetch is *just* to obtain the ETag, not a "does it exist" probe — the `404 → fall through to create` branch reuses the same `get_metadata` call for double duty, which is fine but worth naming. Also: an alternative (and simpler) shape is to always call `upload_text` with `if_none_match="*"` first, then on 412 fetch the ETag and retry with `if_match`. Worth listing under "alternatives considered" so reviewers don't ask.

2. **[Resolved]** **Component 5 / Error Handling — `content_type` has no client-side validation.**
   The design argues against an allowlist (set of MIME types is open-ended) but does not consider basic syntactic validation (must be `type/subtype`, no whitespace). Without this, an LLM passing a garbage `content_type` like `"text"` or `"text/plain; charset=utf-8\nX-Inject: ..."` reaches DIAL's parser. This is probably fine, but a sentence on the trade-off would help future readers. Consider at least rejecting `content_type` with embedded `\n` or `\r`.

3. **[Resolved]** **Component 2 — `list_files` text format swallows long names and offers no URL.**
   The format shown (`F  1234   summary.md`) is name-only; the LLM cannot then call `read_file_lines(file_url=...)` without first reconstructing the URL. The design notes "the `(name, type, size, url)` tuple per entry is also returned in the JSON `attachments` metadata for tools that prefer structured access" — but the rest of the file tools surface text content as the primary return, and there is no precedent in the codebase for tools returning structured `attachments` for the LLM to consume. The simpler fix is to include the URL in the text listing (one column or one row per entry), at the cost of a few more tokens. Worth reconsidering, or at least naming the trade-off explicitly.

4. **[Resolved]** **Out of Scope — "what is NOT changing" prose in Component 6.**
   The line "`edit_file` continues to call `upload_text` without a `content_type` argument, falling back to the default `"text/plain"`" is exactly the kind of non-change enumeration the rubric flags. The fact is already implied by Component 5's `DialFileService.upload_text` extension note ("default `"text/plain"`, so existing callers — `_EditFileTool` — are unaffected"). Drop the line in Component 6 (or move it to *Migration / Non-breaking changes*).

5. **[Resolved]** **Component 8 — `excluded_tools` reference is forward-looking and slightly stale.**
   "The offload module's `excluded_tools` will reference the read tools' names as strings once that design ships." With the prefix rename, this list will need updating in the `large_tool_responses` design. Worth a one-line cross-reference reminder so the work isn't lost: "Note: the prefix rename invalidates any `excluded_tools` list maintained in `large_tool_responses.local.md` — update there when both designs land."

### Nits

1. **Header — `Owner` is in the doc but the template doesn't have it.**
   The template lists Status + Dependencies. Adding `Owner` is fine and matches `file_tools.md`. No action needed; flagging only because the template (`docs/designs/template.md`) does not include this field.

2. **[Resolved]** **Component 2 — example output uses two-space indent but description says "Indentation = depth".**
   The example renders depth-1 with two leading spaces and depth-2 with four. State the indent unit explicitly ("two spaces per depth level") so implementers don't pick a different convention.

3. **[Resolved]** **Component 10 / Configuration / Usage Examples — `features` defaulting note is dropped vs. `file_tools.md`.**
   The previous design's manifest example included a helpful comment explaining that `"features": {}` and omitting `features` are equivalent (because of `default_factory`). The new doc removes that note. Either re-add it or trust readers to infer; the previous version was clearer.

4. **[Resolved]** **Migration — module rename details are scattered.**
   The breaking-changes bullet says "Module rename" and lists the field/prefix renames in one breath. Splitting into three short bullets (module path, config field, tool prefix) makes the migration easier to apply mechanically; consider also linking each to the corresponding row in *Summary of Changes / Modified files*.

---

## Review Notes — Round 2

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-07

### Verdict

`Blocking issues must be addressed`. Round 1's three blocking items are mostly resolved — `delete_file`'s `..` substring check is gone, the trailing-slash contract is now explicit on `_resolve_appdata_url`, and the appdata-required posture has a clear migration entry. However, the new wording introduced in Round 1's Component 2 fix contains a concrete factual error about the SDK's `metadata.get` URL contract that would break the implementation as written. One additional suggestion and one nit follow.

**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-07). Awaiting Round 3 review.**

### Blocking issues

1. **[Resolved]** **Component 2 — `list_files` URL translation note inverts the SDK contract.**
   Step 3 says `DialFileService.list_folder` "strips the leading `files/` segment because the SDK's `metadata.get(resource, relative_url)` expects the path *under* `files/`, not the full DIAL URL." This is incorrect. Looking at the SDK (`aidial_client/resources/metadata.py`): `metadata.get` calls `urljoin(METADATA_PREFIX, relative_url)` where `METADATA_PREFIX = "/v1/metadata/"`. The DIAL endpoint is `/v1/metadata/files/{bucket}/{path}/`, so the `relative_url` argument must **include** the `files/` segment. The existing in-repo callsite `src/quickapp/dial_deployment_tooling/dial_completion_service.py:190` confirms this: `metadata.get("files", strip_file_prefix(file_relative_url))` is called with paths that begin with `files/`. Stripping `files/` before the SDK call would produce `/v1/metadata/{bucket}/{path}/` and 404.
   **Suggestion:** Either drop the "strip the leading `files/` segment" sentence entirely (the simplest fix — pass the `files/{bucket}/{relative}/` shape straight through to `metadata.get("files", folder_url)`), or replace it with the actually-correct contract: "`metadata.get('files', relative_url)` joins `relative_url` onto `/v1/metadata/`, so the input must already include the `files/` segment; pass `folder_url` through unchanged." Worth verifying with a quick experimental call against a DIAL Core instance during implementation.

### Suggestions

1. **[Resolved]** **Component 5 / Algorithm step 2 — name the SDK exception, not the HTTP status.**
   The algorithm says "On `404` (no prior file): call `upload_text(..., if_none_match=\"*\")`." The aidial-client SDK surfaces missing resources as `ResourceNotFoundError` (see `aidial_client/_exception.py:88`), and the existing `_DeleteFileTool` already catches that specific exception. The design also names raw `412` for ETag mismatches when the implementation actually catches `EtagMismatchError` (see existing `_WriteFileTool`/`_EditFileTool`). Naming the exceptions makes the contract implementable without a translation step. Same comment applies to the `delete_file` algorithm step 3 ("On `404`") and the Error Handling table.

### Nits

1. **[Resolved]** **Migration / "Appdata is now required" bullet — borderline non-change prose.**
   The clause "(read/search/list still work because they accept arbitrary URLs and never resolve appdata)" enumerates a non-change to inform the migration reader, which is the sanctioned use of *Migration / Non-breaking changes*. As-is it reads cleanly here, but consider trimming the parenthetical to its essential half: "read/search/list are unaffected." The longer form duplicates the rationale already given in Component 1's bullet "Read/search/list tools never call this helper."

### Changes since previous round

- Round-1 blocking #1 (`delete_file` `..` substring rejects valid filenames) — **resolved.** Algorithm and Error Handling no longer mention `..` for `delete_file`; design note in Component 7 explains the removal explicitly.
- Round-1 blocking #2 (`list_files` URL contract under-specified) — **partially addressed.** Trailing-slash semantics on `_resolve_appdata_url` are now explicit, the responsibility split between tool and service is named, and the e2e_runner reuse note is clarified. However, the new "strip leading `files/`" sentence introduces a new factual error (see Round-2 blocking #1).
- Round-1 blocking #3 (silently dropping the `bucket` fallback) — **resolved.** Migration / Breaking changes now has a dedicated bullet describing the previous fallback, the new behavior, and the deployment scenarios where this matters.
- Round-1 suggestion #1 (`overwrite=True` race window — name `get_metadata` double duty + alternative considered) — **resolved.** Both bullets added in Component 5.
- Round-1 suggestion #2 (`content_type` syntactic validation) — **resolved.** Newline-injection check added; allowlist trade-off named explicitly; Error Handling row split into newline rejection vs. otherwise-malformed.
- Round-1 suggestion #3 (`list_files` text format includes URL inline) — **resolved.** URL is now column 4 of the listing; design note rewrites the trade-off in terms of the actual codebase precedent.
- Round-1 suggestion #4 (Component 6 "what is NOT changing" prose) — **resolved.** The `edit_file` non-change note is removed.
- Round-1 suggestion #5 (cross-reference reminder for `excluded_tools`) — **resolved.** Cross-reference added to Component 8.
- Round-1 nit #1 (Owner field vs. template) — flagged only, no action requested in Round 1; still applies but harmless.
- Round-1 nit #2 (indent unit explicit) — **resolved.** "Two spaces per depth level" stated in Component 2 and in the Configuration / Usage Examples block.
- Round-1 nit #3 (manifest defaulting comment) — **resolved.** Comment about `default_factory` re-added to the third manifest example.
- Round-1 nit #4 (split migration bullets) — **resolved.** Module rename, config-field rename, and tool-prefix rename are now three separate bullets, each with a back-reference to *Summary of Changes*.

### Changes since Round 2

- Round-2 blocking #1 (Component 2 step 3 inverts SDK contract) — **resolved.** "strips the leading `files/` segment" removed; Step 3 now says `folder_url` is passed unchanged to `metadata.get("files", folder_url)` and explains *why* (`metadata.get` joins its argument onto `/v1/metadata/`, so the `files/` segment must be present).
- Round-2 suggestion #1 (name SDK exceptions, not raw HTTP codes) — **resolved.** Component 5 algorithm, Component 7 algorithm, Error Handling table, UC-5, and Tests section now reference `ResourceNotFoundError` (HTTP 404) and `EtagMismatchError` (HTTP 412) throughout.
- Round-2 nit #1 (trim Migration parenthetical) — **resolved.** "(read/search/list still work because they accept arbitrary URLs and never resolve appdata)" → "(read/search/list are unaffected)".
- Stale Summary of Changes row for `_delete_file_tool.py` — **fixed.** Row previously said "`..` defense check added"; corrected to "no client-side validation — appdata isolation is the safety boundary" (the check was removed in Round 1).

---

## Review Notes — Round 3

- **Reviewer:** Andrii
- **Date:** 2026-05-07

### Verdict
Two issues to resolve. But before please answer the questions.

### Blocking issues

1. Remove any mention of large response offload feature.
2. Component-1: use aidial_client has my_appdata_home. explore ability to use it instead of working with raw data

### Suggestions

### Nits

### Questions

1. AC-2: For each level we need to make a separate call to core, right?
2. AC-3 and AC-4: what is the difference? them both use custom content_type

---

## Review Notes — Round 4

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-07

### Verdict

`Blocking issues must be addressed`. Round 3 raises two blocking issues from the author plus two questions that, once answered, reveal an additional design gap. The answers to the questions are straightforward; the two blocking issues require targeted edits to the doc body.

**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-07). Awaiting Round 5 review.**

### Answers to Round-3 questions

**Q1 (UC-2): Does `list_files` at depth N require a separate Core call per level?**

Yes. Per Component 2 Algorithm step 3, `DialFileService.list_folder` calls `dial_client.metadata.get("files", folder_url)` for each subfolder it visits. A depth-3 listing over a tree with W subfolders per level costs O(1 + W + W²) metadata calls. This is the correct behavior and is called out in the depth-bound design note ("Depth bound exists … safe in the worst case"). No doc change needed; the doc already implies this, but the author may want to add one sentence to the Component 2 design notes explicitly naming the call-per-folder cost for future readers.

**Q2 (UC-3 vs UC-4): What is the difference?**

UC-3 ("Agent writes into a nested path") demonstrates the `path` nesting capability — writing `reports/2026-Q1/summary.md` with the *default* `text/plain` content type. UC-4 ("Agent writes a non-default content type") uses a *flat* path (`data/orders.csv`) but passes an explicit `content_type="text/csv"`. The two use cases are meant to be orthogonal: one showcases nesting, the other showcases content-type selection. However, as written they are easy to confuse because UC-3 uses `.md` (implying Markdown, not `text/plain`) and neither use case description calls out explicitly what the *other* parameter is doing. The doc should either (a) state the default `content_type` explicitly in UC-3's Behavior line, or (b) rename UC-3 to "Agent writes into a nested path with default content type" to make the contrast crisp.

### Blocking issues

1. **[Resolved]** **[Header / Component 8 / Error Handling / Tests — remove all `large_tool_responses` mentions from the doc body.]**
   The author's Round-3 blocking issue #1 is to remove any mention of the large-response offload feature. Four locations in the doc body still reference it:
   - **Header** (line 6): `- **Dependencies:** [large_tool_responses](large_tool_responses.local.md) (forward dependency — …)` — remove the entire `Dependencies` line or replace with `None`.
   - **Component 8** (last bullet, line 265): "Does **not** depend on or import `tool_call_result_offload`. The offload module's `excluded_tools` will reference the read tools' names as strings once that design ships. **Cross-reference reminder:** …" — remove the entire bullet.
   - **Error Handling table** (last row, line 361): `| LLM requests an oversized slice | Intended to bypass \`LargeResponseProcessor\` … |` — remove this row.
   - **Tests** (last bullet, line 594): `- Integration: offload end-to-end coverage (read-back path) is deferred pending the \`large_tool_responses\` design.` — remove this bullet.

   The historical review notes (Rounds 1–3) reference the offload feature in the tracking of resolved items; those are the read-only history and do not need to change.
   **Suggestion:** After removing the four locations above, re-read Component 8 to confirm no orphaned sentences remain.

2. **[Resolved]** **[Component 1 — evaluate replacing `dial_client.bucket.get_raw()` with `dial_client.my_appdata_home()`.]**
   The author's Round-3 blocking issue #2 asks whether `aidial_client`'s `my_appdata_home()` helper can replace the manual `bucket.get_raw()` + `.appdata` extraction in `_resolve_appdata_url`. The SDK does expose this: `AsyncDialClient.my_appdata_home()` returns `Optional[PurePosixPath]` where the value is `PurePosixPath(appdata.raw)` (i.e. `{user_bucket}/appdata/{app_name}` as a path). Prepending `"files/"` to that path gives the same URL prefix the design currently builds via `f"files/{appdata}/{path}"`. The SDK also caches the bucket response internally (`_my_appdata` field), so switching avoids a raw HTTP call on every `_resolve_appdata_url` invocation in the same request.

   The doc currently says (Component 1, step 3): "Resolves the bucket via `dial_client.bucket.get_raw()`. Uses `bucket_resp.appdata` if present; if `None`, raises `InvalidToolCallParameterException`…". This must be updated to reflect the chosen approach. The author should decide:

   - **Option A (use `my_appdata_home`):** Replace step 3 with: "Calls `await dial_client.my_appdata_home()`. If it returns `None`, raises `InvalidToolCallParameterException(…)`. Otherwise, constructs `f"files/{home}/{path}"` where `home = str(appdata_home)`." This is the cleaner API and avoids reaching into the raw bucket response.
   - **Option B (keep `get_raw`):** Explicitly acknowledge in the doc that `my_appdata_home()` exists and explain why the raw path is preferred (e.g., to avoid the `PurePosixPath` intermediate, or because the codebase currently uses `get_raw` everywhere). As-is, the doc silently ignores a cleaner SDK API the author has now pointed out.

   The design doc must resolve this: either adopt `my_appdata_home` and update Component 1's step 3, or state the trade-off and rationale for staying with `get_raw`.
   **Suggestion:** Adopt Option A. `my_appdata_home()` is the high-level API DIAL intended for exactly this pattern; using it removes the `BucketResponse` knowledge from application code and makes the `None`-means-no-appdata branch obvious. Update Component 1 step 3, the `_resolve_appdata_url` pseudocode, and the `_WriteFileTool` design note in Migration / Breaking changes (which currently cites `bucket_resp.appdata`) accordingly.

### Suggestions

1. **[Resolved]** **[UC-3 / UC-4 — clarify what each use case is isolating.]**
   Per the Q2 answer above: UC-3's Behavior line should state the default content type explicitly (`content_type` defaults to `text/plain`), and UC-4 should note the path is intentionally flat to isolate the content-type feature. A one-sentence tweak to each use case is sufficient.

2. **[Resolved]** **[Component 2 design notes — name the per-folder call cost.]**
   Add one sentence to the "Depth bound exists" design note: "Each subfolder at each depth level requires one metadata call to Core; a depth-D listing over a tree with W subfolders per level costs O(W^D) calls in the worst case — the `max_depth <= 10` bound limits this." This directly answers Q1 for future readers and justifies the bound.

### Nits

1. **[Acknowledged, no action]** **[Round-3 review block — status annotation belongs in the reviewer's round, not as a forward-declaration.]**
   Round 3 ends with "**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-07). Awaiting Round 3 review.**" (under the Round-2 Verdict). This is a status annotation the author added after their revision, but it is embedded inside the Round-2 block rather than in the Round-3 block where the author's verdict lives. It also says "Awaiting Round 3 review" but Round 3 has already landed. This is minor history noise; no action needed beyond noting that future self-annotation should go into the author's own round block, not retroactively into the previous reviewer's block.

### Changes since previous round

- Round-3 blocking #1 (remove large_tool_responses mentions) — **still open.** Four locations in the doc body continue to reference the offload feature (see Round-4 blocking #1 above for the exact lines).
- Round-3 blocking #2 (evaluate `my_appdata_home`) — **still open.** Component 1 step 3 still uses `dial_client.bucket.get_raw()`. The author's question has been answered (see Round-4 answer to Q2 and blocking #2); the doc must be updated to reflect the chosen approach.
- Round-3 Q1 (separate call per level) — **answered.** Yes; one Core metadata call per visited folder. Optional: add a sentence to Component 2 design notes.
- Round-3 Q2 (UC-3 vs UC-4 difference) — **answered.** UC-3 isolates nested paths; UC-4 isolates content-type selection. The two should be made easier to distinguish (see suggestion #1).

### Changes since Round 4

- Round-4 blocking #1 (remove all `large_tool_responses` mentions) — **resolved.** Removed: header `Dependencies` line, Component 8 offload bullet, Error Handling "oversized slice" row, Tests integration-offload bullet. The word "offloaded" in the Problem Statement's discovery use case (`"an offloaded tool response"`) is retained — it describes a file type an agent might want to discover, not a dependency on the offload feature.
- Round-4 blocking #2 (replace `bucket.get_raw()` with `my_appdata_home()`) — **resolved.** Component 1 step 3 now calls `await dial_client.my_appdata_home()`, with an explanation of the caching behavior. `f"files/{home}/{path}"` replaces `f"files/{appdata}/{path}"`. Error Handling row and Migration bullet updated to use `my_appdata_home()` terminology.
- Round-4 suggestion #1 (UC-3/UC-4 distinction) — **resolved.** UC-3 renamed to "Agent writes into a nested path (default content type)"; trigger shows no explicit `content_type`; Behavior notes the `"text/plain"` default. UC-4 renamed to "Agent writes a non-default content type (flat path)"; trigger uses a flat path; Behavior explains the path is intentionally flat to isolate the feature.
- Round-4 suggestion #2 (per-folder call cost) — **resolved.** "Depth bound exists" note now explicitly names the O(W^D) cost and states the `max_depth` bound as the mitigation.
- Round-4 nit #1 (status annotation placement) — acknowledged, no action.
