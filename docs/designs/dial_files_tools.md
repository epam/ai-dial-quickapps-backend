# Design: DIAL Files Tools

- **Status:** Implemented
- **Approved:** 2026-05-11
- **Owner:** Andrii Novikov

## Problem Statement

QuickApps agents need DIAL file storage as a real working surface — a place to read, write, and organize files across a conversation. Two capabilities are required:

- **Discovery.** Without an `ls` primitive, agents can read/edit files only when they already know the URL. Workflows that need to find an existing artifact (a previously written report, a user-uploaded folder) are impossible: the agent can write a file, lose track of the URL, and have no way to recover it.
- **A rich write surface.** Agents need to organize their working surface into folders and write files of various text types (`text/plain`, `text/markdown`, `text/csv`, `application/json`) so downstream consumers (renderers, parsers) handle them correctly.

This design provides a toolkit covering both: agents get a discovery primitive, can organize files into nested directories, can pick the content type, and can explicitly opt into overwriting an existing file.

## Design Goals

- Expose a small, orthogonal set of **DIAL files tools** to the LLM: list a folder, read a slice, search for a substring, edit by string replacement, write a new (or overwrite an existing) text file, delete a file.
- Treat appdata isolation as the safety boundary. With appdata always populated in our deployments, additional subdirectory layering is unnecessary and obscures the more powerful surface.
- Allow nested paths and caller-chosen content types so agents can produce structured outputs (folders of CSVs, a report set, a JSON manifest plus its assets).
- Default to safe behavior (`overwrite=False`) but make the destructive path explicit and reachable.
- Be preview-gated. No footprint when the feature flag is off.
- Path-traversal-restrict every appdata-anchored operation. The agent cannot escape its appdata namespace via constructed `..` paths.

---

## Use Cases

### UC-1: Agent lists the immediate contents of a folder under its home

**Trigger:** The LLM calls `list_files(path="reports/", max_depth=1)`. The relative form resolves under the agent's home dir (`agent_home_dir`, default `files/{appdata}/`).\
**Behavior:** The tool calls `DialFileService.list_folder(folder_url, max_depth=1)`, which wraps `dial_client.metadata.get("files", folder_url)` and returns only the immediate children. The tool formats the response as a compact text listing.\
**Outcome:** The LLM sees one entry per child (file or folder) with size and path. Folder entries end with `/`; entries under the agent's home dir are emitted as relative paths; entries outside it are emitted as absolute `files/...` URLs (see *Path conventions*).

### UC-2: Agent lists a folder recursively, depth-bounded

**Trigger:** `list_files(path="reports/", max_depth=3)`.\
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

### UC-6: Agent reads a line range from a file in its home dir

**Trigger:** `read_file_lines(path="reports/summary.md", start_line=0, end_line=50)`.\
**Behavior:** The relative `path` resolves under the agent's home dir. The tool downloads the file via `DialFileService` (cached per request), splits on `\n`, and slices `[start_line, end_line)`.\
**Outcome:** Lines `[start_line, end_line)` are returned.

### UC-6b: Agent reads a non-home file (user upload or shared artifact)

**Trigger:** `read_file_lines(path="files/{other_bucket}/uploads/notes.txt", start_line=0, end_line=200)`.\
**Behavior:** The `path` starts with `files/` and is treated as an absolute DIAL URL — `_resolve_appdata_url` returns it unchanged. Used for files the agent does not own (user-uploaded attachments, shared admin artifacts).\
**Outcome:** Same as UC-6; demonstrates *when* the absolute form is the right choice.

### UC-7: Agent searches for a substring

**Trigger:** `search_in_file(path="reports/summary.md", pattern="ERROR", context_lines=2, case_insensitive=True)`.\
**Behavior:** Downloads the file (cached), finds every line containing `pattern` (lower-cased if `case_insensitive`), expands each match by ±`context_lines`, merges overlapping windows, and returns the lines with 1-indexed line numbers. Non-adjacent windows are separated by `--`. `path` accepts both forms (relative under home dir, or absolute `files/...`).\
**Outcome:** The LLM gets a focused, grep-style snippet with enough surrounding context to act on it.

### UC-8: Agent edits an existing file

**Trigger:** `edit_file(path="reports/summary.md", old_string="foo", new_string="bar")`.\
**Behavior:** Unique-match string replacement with ETag-guarded upload and post-edit cache invalidation. `path` is relative-only (same rule as `write_file`).\
**Outcome:** The file at the same URL contains the edit; subsequent same-turn reads see it.

### UC-9: Agent deletes a file under its home dir

**Trigger:** `delete_file(path="reports/old.md")`.\
**Behavior:** The relative `path` resolves under the agent's home dir; the tool calls `dial_client.files.delete(resolved_url)`. Absolute `files/...` URLs are rejected (same rule as `write_file` / `edit_file`).\
**Outcome:** The file is removed. The success message echoes the relative path the agent passed in.

### UC-10: Agent provides an invalid path

**Trigger:** `write_file(path="../escape.md", ...)` or `write_file(path="/absolute.md", ...)` or `write_file(path="foo//bar", ...)`.\
**Behavior:** The path validator raises `InvalidToolCallParameterException("path", ...)` before any IO.\
**Outcome:** The LLM gets a precise, actionable error and self-corrects.

### UC-11: Repeated reads of the same file in one request

**Trigger:** Multiple `read_file_lines` / `search_in_file` calls against the same `path`.\
**Behavior / Outcome:** `DialFileService` caches the download per request (keyed by URL via `StateHolder`, with a configurable per-file size limit from `FileLoadingSizeLimitResolver`), so subsequent calls hit the cache.

### UC-12: Agent copies a user-uploaded file into its workspace

**Trigger:** `copy_file(source="files/{user_bucket}/uploads/data.csv", destination="inputs/data.csv")`.
**Behavior:** `source` is an absolute DIAL URL (non-home file the agent doesn't own); `destination` is a relative path resolved under `agent_home_dir`. The tool calls `DialFileService.copy(source_url, dest_url, overwrite=False)`, which POSTs to `/v1/ops/resource/copy`. No bytes are downloaded — the copy happens server-side.\
**Outcome:** The file lands at `inputs/data.csv` in the agent's home dir. The agent can then `read_file_lines` / `search_in_file` / `edit_file` it using its relative path.

### UC-13: Agent renames / moves a file within its workspace

**Trigger:** `move_file(source="drafts/report-v1.md", destination="final/report.md")`.\
**Behavior:** Both `source` and `destination` are relative paths resolved under `agent_home_dir`. The tool calls `DialFileService.move(source_url, dest_url, overwrite=False)`, which POSTs to `/v1/ops/resource/move`. The original file is removed at the source URL by DIAL Core.\
**Outcome:** The file now exists only at `final/report.md`; the source URL is gone. Useful for promoting a draft to a final location without a duplicate-then-delete loop.

---

## Proposed Design

### Component 1: `_DialFileTool` base class

**What:** A thin internal base class that holds the common dependencies (`DialFileService`, the `_dial_client` for bucket resolution, stage-wrapper plumbing) and extends `StagedBaseTool`. Concrete tools implement `_run_in_stage_async`.

**Owner:** `src/quickapp/dial_files_tooling/_base_file_tool.py`

**Semantics:**

- Provides `self._dial_file_service` to subclasses (download + upload + cache primitives).
- Receives `DialFilesConfig` (in particular `agent_home_dir`) by injection so `_resolve_appdata_url` can read the template at request time.
- Provides an `async _resolve_appdata_url(path: str) -> str` helper that branches on input shape:
  1. Validates `path` is a non-empty string.
  2. **Absolute branch.** If `path` starts with `files/`, treat it as a fully-qualified DIAL URL and return it unchanged after a minimal sanity check (no embedded `\n` / `\r`). Path-traversal validation is intentionally not applied — an absolute URL containing `..` is the caller's responsibility, and DIAL Core rejects malformed URLs server-side.
  3. **Relative branch.** Apply the path-traversal validator to `path`: reject any leading `/`, any literal `../` substring, any segment equal to `..`, any empty segment (e.g. `foo//bar`), and trailing whitespace. All failures raise `InvalidToolCallParameterException("path", "...")` with a precise message.
  4. Resolve `agent_home_dir` (config-validated to start with `files/` and end with `/`):
     - If the template contains `{appdata}`: call `await dial_client.my_appdata_home()`. If it returns `None`, raise `InvalidToolCallParameterException("path", "appdata namespace is not available; agent_home_dir uses {appdata} but no appdata was found")`. Substitute the returned path string. `my_appdata_home()` caches the bucket response internally, so repeated calls within a request do not incur extra HTTP round-trips.
     - If the template contains no `{appdata}`: use as-is; no SDK call is needed (read/search/list tools therefore work even when appdata is unavailable, provided the operator pointed `agent_home_dir` at a non-appdata bucket).
  5. Returns `f"{resolved_home}{path}"`. `agent_home_dir` always ends with `/`, so the joined URL is well-formed. **Trailing slash on `path` is preserved as-is**: a trailing `/` on the input means a folder URL (used by `list_files`); no trailing `/` means a file URL (used by `write_file`). The helper does not add or strip slashes — the caller controls the shape.
- Provides an inverse helper `async _to_display_path(url: str) -> str` used by tool result messages: if `url` is prefixed by the resolved `agent_home_dir`, return the trailing relative portion; otherwise return `url` unchanged. It is `async` because home-dir resolution may need `my_appdata_home()` on first call (subsequent calls return from cache). Used by `write_file` / `delete_file` success lines and `list_files` row formatting to keep returned paths in the form the agent uses to address them.

`AttachmentService` is **not** a base-class dependency — `write_file` constructs its `Attachment` directly from the URL returned by `DialFileService.write_file`.

#### Path conventions

Path handling follows a single rule: **read-only tools accept both forms; mutating tools are relative-only.**

- **Relative paths** address the agent's home directory (`agent_home_dir`, default `files/{appdata}/`). Form: `reports/summary.md`, `data/orders.csv`, `reports/` (folder).
- **Absolute paths** start with `files/` and address anywhere the caller has access — user uploads, shared admin artifacts, cross-bucket reads. Form: `files/{some_bucket}/uploads/notes.txt`.
- **Read-only tools** (`list_files`, `read_file_lines`, `search_in_file`) accept either form. The agent can inspect files it doesn't own without writing or deleting them.
- **Mutating tools** (`write_file`, `edit_file`, `delete_file`) accept **relative paths only**. The agent authors and modifies only inside its own home; cross-namespace mutations are deferred until a use case appears (see *Out of Scope*). Absolute `files/...` URLs passed to these tools are rejected with `InvalidToolCallParameterException` before any IO.
- **Tool outputs** echo the namespace of the target: entries under the resolved `agent_home_dir` are emitted as **relative** paths; entries outside it are emitted as **absolute** `files/...` URLs. This keeps the agent thinking in its own home namespace and surfaces the absolute form only when the file genuinely lives elsewhere.
- The default `agent_home_dir = "files/{appdata}/"` means the relative namespace is appdata; operators can repoint it via config (see *Component 10*).

---

### Component 2: `list_files`

**What:** Internal tool that lists the entries under a folder in DIAL storage, with depth-bounded recursion.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | Relative path under the agent's home dir, or absolute DIAL URL starting with `files/`. Folder paths end with `/`. |
| `max_depth` | integer | no | `1` | Recursion depth. `1` = immediate children only. Must be `>= 1` and `<= 10`. |

**Algorithm:**

1. Validate `max_depth` in `[1, 10]` — else raise `InvalidToolCallParameterException("max_depth", "...")`.
2. Ensure `path` ends with `/` (DIAL Core requires the trailing slash for folder listing — append one if missing). Resolve via `_resolve_appdata_url(path)` — the helper dispatches absolute vs relative as described in *Path conventions*.
3. Call `DialFileService.list_folder(folder_url, max_depth)`. The service calls `dial_client.metadata.get("files", folder_url)` directly — `metadata.get` joins its second argument onto `/v1/metadata/`, so the input must already include the `files/` segment; the `files/{bucket}/{relative}/` URL is passed through unchanged. (The `e2e_runner.py` helper bypasses the SDK and hits `{api_url}metadata/{folder}/` directly via `httpx`; we use the SDK path here for consistency with every other DIAL call in the codebase.)
4. Format the response as a compact text listing, one entry per line: size (bytes, or `-` for folders), then the display path (run through `_to_display_path`). Home-dir entries appear relative; out-of-home entries appear as absolute `files/...` URLs (see *Path conventions*). Folder display paths end with `/`. No indentation — depth is already encoded in the path:
   ```
   -  reports/
   1234  reports/summary.md
   56789  reports/data.csv
   -  reports/images/
   2048  reports/images/logo.png
   ```
   When the target is outside the agent's home dir, the path column holds the absolute URL (e.g. `files/{other_bucket}/uploads/notes.txt`).
   - Folders at the depth bound are listed with no expansion (so the LLM knows they exist and can drill down explicitly with another `list_files` call).
5. Return `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_list_files_tool.py`

**Design notes:**

- **Why text output over JSON.** Tabular text is cheaper in tokens and easier for the LLM to scan. The path column doubles as the argument to pass directly to other file tools, so no URL reconstruction step is needed.
- **Depth bound exists.** Without it, an LLM could trigger an unbounded walk on a deep user-uploaded folder. Each subfolder at each depth level requires one metadata call to Core; a depth-D listing over a tree with W subfolders per level costs O(W^D) calls in the worst case — the `max_depth <= 10` bound limits this. `max_depth <= 10` is generous in practice and safe in the worst case.
- **Pagination is out of scope.** When folder sizes warrant it, this tool can grow `next_token` semantics without breaking the contract (additive optional param + sentinel in the listing).
- **Reuse.** `DialFileService.list_folder` mirrors the recursion shape used in `src/tests/integration_tests/test_runner/e2e_runner.py`. That helper hits the metadata endpoint via raw `httpx`; the service uses the SDK's `dial_client.metadata.get("files", ...)` instead so the call participates in the same auth/header plumbing as every other DIAL call in the codebase. The recursion shape (depth-bounded BFS over `items`) is the part that's reused.

---

### Component 3: `read_file_lines`

**What:** Read a line range from a UTF-8 text file.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Relative path under the agent's home dir, or absolute DIAL URL starting with `files/`. |
| `start_line` | integer | yes | First line (0-indexed, inclusive). |
| `end_line` | integer | yes | First line to exclude (0-indexed, like a Python slice end). |

**Algorithm:**

1. Validate `start_line >= 0` and `end_line >= start_line` — else raise `InvalidToolCallParameterException`.
2. Resolve `url = await _resolve_appdata_url(path)`.
3. Decode the file via the base-class helper `text, _ = await self._download_text(url, display_path=path)` (wraps `DialFileService.download_file(url) -> tuple[bytes, FileMetadata | None]`, decodes UTF-8, and surfaces DIAL errors as `InvalidToolCallParameterException`). Download is cached per request.
4. Split on `\n` via `splitlines()`.
5. Return `"\n".join(lines[start_line:end_line])` as `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_read_file_lines_tool.py`

---

### Component 4: `search_in_file`

**What:** Substring search with optional case-insensitivity and context lines.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | Relative path under the agent's home dir, or absolute DIAL URL starting with `files/`. |
| `pattern` | string | yes | — | Substring to search for. |
| `context_lines` | integer | no | `0` | Lines of context around each match. |
| `case_insensitive` | boolean | no | `false` | If true, compare lower-cased. |

**Algorithm:**

1. Resolve `url = await _resolve_appdata_url(path)`.
2. Download and decode UTF-8 text (cached per request).
3. Split into lines via `splitlines()`.
4. For each line index, test `pattern in line` (lower-casing both if `case_insensitive`).
5. If no matches → return `ToolCallResult(content="No matches found.", content_type="text/plain")`.
6. Build the union of `[i - context_lines, i + context_lines]` windows around each match (clamped to file bounds), deduplicate, sort.
7. Emit each included line as `"{i+1}:{line}"` (1-indexed). Insert a `--` separator between non-adjacent windows.
8. Return joined lines as `ToolCallResult(content=..., content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_search_in_file_tool.py`

**Design notes:**
- Substring only. Regex is out of scope (see *Out of Scope*).
- Output line numbers are **1-indexed**. `read_file_lines` inputs are **0-indexed** to match Python slice semantics — this asymmetry is intentional and documented in each tool's description.

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

1. **Reject the absolute form.** If `path` starts with `files/`, raise `InvalidToolCallParameterException("path", "write_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL")`. All mutating tools share this restriction (see *Path conventions* and the design note below).
2. Resolve `url = await _resolve_appdata_url(path)`. (Path-traversal validation + `agent_home_dir` resolution happen here; failures raise before any IO.)
3. Call `DialFileService.write_file(url=url, content=content, content_type=content_type, overwrite=overwrite)`. The service encapsulates the conditional-header branching: with `overwrite=False` it sends `If-None-Match: *`; with `overwrite=True` it fetches the current ETag (falling through to create on `ResourceNotFoundError`) and uploads with `If-Match: <etag>`. The cache is invalidated on success. On `EtagMismatchError` (HTTP 412) the tool surfaces a precise message: when `overwrite=False` → `InvalidToolCallParameterException("path", "file already exists: {display_path}; pass overwrite=True to replace")`; when `overwrite=True` → `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`.
4. Build an `Attachment` pointing at `url` (so the DIAL UI shows the file; attachment URLs are always absolute — the UI needs the resolved form).
5. Return `ToolCallResult(content=f"File written: {_to_display_path(url)}", content_type="text/plain", attachments=[attachment])`. Since `write_file` only accepts relative paths, the displayed form is always the relative path the agent passed in.

**Owner:** `src/quickapp/dial_files_tooling/_write_file_tool.py`

**Design notes:**

- **Relative-only `path`.** All three mutating tools (`write_file`, `edit_file`, `delete_file`) accept only relative paths under `agent_home_dir`. Read-only tools (`list_files`, `read_file_lines`, `search_in_file`) accept either form. The agent authors and mutates files only in its own home; cross-namespace mutations are out of scope until a use case appears (see *Out of Scope*). An absolute `files/...` URL passed to a mutating tool is caught at Algorithm step 1 and rejected before any IO.
- **Overwrite is opt-in.** Default safety net is `If-None-Match: *`. The `overwrite=True` path is the explicit, ETag-guarded escape hatch — no silent clobber.
- **Why one tool, not two.** A separate `overwrite_file` tool was considered. Folding the toggle into a parameter keeps the surface small; the LLM sees one tool with a clearly named optional flag.
- **`content_type` is caller-controlled.** Sniffing was rejected: the agent already knows what it is producing, and sniffing risks misclassification (e.g., a JSON file beginning with `<` due to embedded HTML). Default is `text/plain`. Client-side validation is intentionally minimal — there is no MIME-type allowlist (the set is open-ended) — but the value is rejected if it contains `\n` or `\r` to prevent header-injection-style abuse before the string reaches DIAL's HTTP layer.
- **Path-traversal validation runs first.** No partial work — invalid path → no IO, no cache mutation. Validation errors are precise so the LLM can retry without guessing.
- **`appdata` is required.** The base-class helper raises a descriptive error when the bucket response has no appdata. In our supported deployments this never fires; if it does, the agent gets a clear signal rather than silently writing into the user's personal bucket.
- **`edit_file` still exists.** `write_file(overwrite=True)` is for full rewrites; `edit_file` is for surgical patches with concurrency safety. The two are complementary, not redundant.
- **`get_metadata` does double duty.** In the `overwrite=True` branch the metadata fetch serves two purposes: (a) obtain the ETag for the conditional upload, and (b) detect "no prior file" via the 404 so the call falls through to a clean create. There is no separate existence probe — both signals come from the same call.
- **Alternative considered: try-create-then-retry.** A simpler shape would be: always upload with `If-None-Match: *` first; on 412, fetch the ETag and retry with `If-Match: <etag>`. That removes the metadata round-trip on the common new-file path. Rejected for v1 because the typical `overwrite=True` call is an explicit replacement (the agent expects the file to exist), so the optimistic-create path adds complexity that pays off only for edge cases. Worth revisiting if profiling shows the metadata call dominates write latency.

**`DialFileService.write_file`.** Signature: `async write_file(url, content, *, content_type="text/plain", overwrite=False, if_match=None) -> str`. Encapsulates the `If-Match` / `If-None-Match` branching described above; raises `EtagMismatchError` on conditional failure; invalidates the request-scoped cache for `url` on success. The MIME is propagated to the underlying `dial_client.files.upload(file=(name, bytes, mime))` call.

---

### Component 6: `edit_file`

**What:** Applies a single string-replacement edit to an existing UTF-8 text file, guarded by the file's ETag to prevent lost updates. Accepts **relative paths only** under `agent_home_dir` (absolute `files/...` URLs are rejected — same rule as `write_file`).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Relative path under the agent's home dir. Absolute `files/...` URLs are rejected. |
| `old_string` | string | yes | Exact substring to replace. Must occur **exactly once** in the file. |
| `new_string` | string | yes | Replacement text. May be empty (deletes the `old_string` occurrence). |

**Algorithm:**

1. **Reject the absolute form.** If `path` starts with `files/`, raise `InvalidToolCallParameterException("path", "...")` before any IO.
2. Resolve `url = await _resolve_appdata_url(path)` (relative branch — path-traversal validation + `agent_home_dir` resolution).
3. Obtain the file's text and metadata via the base-class helper `content, metadata = await self._download_text(url, display_path=path)` (which wraps `DialFileService.download_file(url) -> tuple[bytes, FileMetadata | None]` and decodes UTF-8). Read `etag = metadata.etag if metadata else None`.
4. If `old_string == new_string` → raise `InvalidToolCallParameterException("new_string", "new_string must differ from old_string")`.
5. `count = content.count(old_string)`. If `count == 0` → raise `"old_string not found in file"`. If `count > 1` → raise `"old_string found {count} times; provide more surrounding context to disambiguate"`.
6. `new_content = content.replace(old_string, new_string, 1)` (explicit `count=1` for safety even though uniqueness is verified).
7. Re-upload via `DialFileService.write_file(url=url, content=new_content, if_match=etag)`. The service invalidates the cache for `url` on success, so subsequent same-turn `read_file_lines`/`search_in_file` calls see the updated content.
8. On `EtagMismatchError` (HTTP 412) → raise `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`.
9. On success → return `ToolCallResult(content=f"Edited: {_to_display_path(url)}", content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_edit_file_tool.py`

**Design notes:**
- **Unique-match requirement** is the most reliable primitive for LLMs: it forces the model to include enough surrounding context to disambiguate.
- **Why string replacement over line-range replacement.** Line numbers drift after any prior edit in the same conversation; anchoring on substring content keeps edits locally consistent.
- **ETag optimistic concurrency.** `If-Match: <etag>` catches the narrow case where two tool calls modify the same file in parallel.
- **No partial-update primitive is available.** DIAL's file API has no PATCH; the download+upload shape is the only option.
- **No attachment in response.** Returns only a confirmation string; the URL is unchanged, the LLM already has it, and emitting an attachment on every edit would clutter the UI for workflows that make multiple edits to the same file.

---

### Component 7: `delete_file`

**What:** Internal tool that removes a file from DIAL storage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | Relative path under the agent's home dir. **Rejected:** leading `/`, `..` segment, `../` substring, empty segment, trailing whitespace, absolute `files/...` URL. |

**Algorithm:**

1. **Reject the absolute form.** If `path` starts with `files/`, raise `InvalidToolCallParameterException("path", "delete_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL")`.
2. `url = await _resolve_appdata_url(path)` (relative branch — path-traversal validation + `agent_home_dir` resolution).
3. Call `dial_client.files.delete(url)`.
4. On success → `ToolCallResult(content=f"Deleted: {_to_display_path(url)}", content_type="text/plain")` — echoes the relative path the agent passed in.
5. On `ResourceNotFoundError` (HTTP 404) → `InvalidToolCallParameterException("path", "file not found: {path}")` — same shape as `write_file`/`edit_file` errors.
6. Other errors → propagate as tool-call errors.

**Owner:** `src/quickapp/dial_files_tooling/_delete_file_tool.py`

**Design notes:**

- **Appdata isolation is the safety boundary.** An LLM running in app context cannot delete files outside its own appdata namespace, so no additional client-side path-allowlist is needed. A `..`-substring check was considered and rejected: it would have falsely rejected legitimate filenames containing `..` (e.g. `v1.2..3/log.txt`) and only blocked one syntactic form of escape rather than preventing escape at all.
- **No ETag guard.** Delete is unconditional within the appdata scope; the concurrency window for delete is rarely meaningful.
- **No soft delete.** DIAL's `files.delete` is a hard delete. No undo.

---

---

### Component 7.5: `copy_file`

**What:** Internal tool that copies a file from `source` to `destination` via DIAL's `POST /v1/ops/resource/copy` endpoint. The source can live anywhere the agent has read access (its home dir or an absolute `files/...` URL); the destination must be a relative path inside `agent_home_dir`. No bytes are downloaded — the copy is server-side.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `source` | string | yes | — | Relative path under the agent's home dir, or absolute DIAL URL starting with `files/`. The file to copy from. |
| `destination` | string | yes | — | Relative path under the agent's home dir. The new copy's location. Absolute `files/...` URLs are rejected. |
| `overwrite` | boolean | no | `false` | If `false`, fails when destination already exists. If `true`, replaces an existing destination. |

**Algorithm:**

1. **Reject absolute `destination`.** If `destination` starts with `files/`, raise `InvalidToolCallParameterException("destination", "copy_file destination must be a relative path under agent_home_dir; do not pass an absolute files/... URL")`.
2. Resolve `source_url = await _resolve_appdata_url(source)` (absolute pass-through or relative resolution).
3. Resolve `dest_url = await _resolve_appdata_url(destination)` (relative branch — path-traversal validation + `agent_home_dir` resolution).
4. Call `DialFileService.copy(source_url=source_url, destination_url=dest_url, overwrite=overwrite)`.
   - On `ResourceNotFoundError` (HTTP 404) → `InvalidToolCallParameterException("source", f"source not found: {source}")`.
   - On `EtagMismatchError` (HTTP 412) and `overwrite=False` → `InvalidToolCallParameterException("destination", f"destination already exists: {_to_display_path(dest_url)}; pass overwrite=True to replace")`.
   - On `DialException(status_code=403)` → `InvalidToolCallParameterException("source", f"access denied: {source_url}")`.
5. Call `DialFileService.invalidate_cache(dest_url)` so same-turn reads see the new file.
6. Return `ToolCallResult(content=f"Copied to: {_to_display_path(dest_url)}", content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_copy_file_tool.py`

**Design notes:**

- **Source is dual-form; destination is relative-only.** The agent copies *from* anywhere it has read access (including user uploads, shared artifacts), but always copies *into* its own home. This is the primary way for agents to ingest external files into their workspace without downloading bytes.
- **No bytes downloaded.** The copy is server-side: DIAL Core moves the data internally. The tool never touches the file content.
- **`overwrite` mirrors `write_file`.** Default `false` keeps the create-only safety net; `true` replaces the destination unconditionally (no ETag guard — the DIAL Core ops endpoint handles concurrency on its side).

**`DialFileService.copy` method (new):**

```python
async def copy(self, source_url: str, destination_url: str, overwrite: bool) -> None:
    await self._dial_client._http_client.request(
        cast_to=type(None),
        options=FinalRequestOptions(
            method="POST",
            url="/v1/ops/resource/copy",
            json={"sourceUrl": f"/v1/{source_url}", "destinationUrl": f"/v1/{destination_url}", "overwrite": overwrite},
        ),
    )
```

**Private SDK API note:** `_http_client` is a private attribute of `aidial_client`'s `AsyncDIALClient`. It is the right transport — it shares auth headers and base-URL resolution with every other DIAL call in the codebase — but carries a maintenance risk: a future SDK upgrade could rename or remove it. If upstream `aidial_client` adds a public `files.copy` method, switch to it.

---

### Component 7.6: `move_file`

**What:** Internal tool that moves (renames) a file from `source` to `destination` via DIAL's `POST /v1/ops/resource/move` endpoint. Both source and destination must be relative paths inside `agent_home_dir`. The original file is removed by DIAL Core atomically.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `source` | string | yes | — | Relative path under the agent's home dir. The file to move. Absolute `files/...` URLs are rejected. |
| `destination` | string | yes | — | Relative path under the agent's home dir. The new location. Absolute `files/...` URLs are rejected. |
| `overwrite` | boolean | no | `false` | If `false`, fails when destination already exists. If `true`, replaces an existing destination. |

**Algorithm:**

1. **Reject absolute `source` and `destination`.** If either starts with `files/`, raise `InvalidToolCallParameterException` for that parameter ("move_file source/destination must be a relative path under agent_home_dir; do not pass an absolute files/... URL").
2. Resolve `source_url = await _resolve_appdata_url(source)` (relative branch).
3. Resolve `dest_url = await _resolve_appdata_url(destination)` (relative branch).
4. Call `DialFileService.move(source_url=source_url, destination_url=dest_url, overwrite=overwrite)`.
   - On `ResourceNotFoundError` (HTTP 404) → `InvalidToolCallParameterException("source", f"source not found: {source}")`.
   - On `EtagMismatchError` (HTTP 412) and `overwrite=False` → `InvalidToolCallParameterException("destination", f"destination already exists: {_to_display_path(dest_url)}; pass overwrite=True to replace")`.
   - On `DialException(status_code=403)` → `InvalidToolCallParameterException("source", f"access denied: {source_url}")`.
5. Call `DialFileService.invalidate_cache(source_url)` and `DialFileService.invalidate_cache(dest_url)` so same-turn reads see the change.
6. Return `ToolCallResult(content=f"Moved to: {_to_display_path(dest_url)}", content_type="text/plain")`.

**Owner:** `src/quickapp/dial_files_tooling/_move_file_tool.py`

**Design notes:**

- **Both sides are relative-only.** `move_file` is a within-home operation: rename/reorganize the agent's own working surface. Cross-namespace moves are out of scope (see *Out of Scope*).
- **Atomic on the server side.** DIAL Core removes the source and creates the destination in one op; the tool never touches the file content.
- **`overwrite` mirrors `write_file` and `copy_file`.** Default `false`; `true` replaces the destination.

**`DialFileService.move` method (new):**

```python
async def move(self, source_url: str, destination_url: str, overwrite: bool) -> None:
    await self._dial_client._http_client.request(
        cast_to=type(None),
        options=FinalRequestOptions(
            method="POST",
            url="/v1/ops/resource/move",
            json={"sourceUrl": f"/v1/{source_url}", "destinationUrl": f"/v1/{destination_url}", "overwrite": overwrite},
        ),
    )
```

Uses the same private-SDK transport as `DialFileService.copy` (see Component 7.5 design note). Invalidates both source and destination in the download cache after a successful move.

### Component 8: `DialFilesToolingModule` (DI wiring)

**What:** `injector.Module` that:

- Binds `_FileStageWrapper`, `_ListFilesTool`, `_ReadFileLinesTool`, `_SearchInFileTool`, `_WriteFileTool`, `_EditFileTool`, `_DeleteFileTool`, `_CopyFileTool`, `_MoveFileTool` in `request_scope`.
- Contributes all eight tools to the shared `list[StagedBaseTool]` multiprovider via its own `@multiprovider`-decorated provider method (same pattern as `InternalToolModule._provide_internal_tools`).
- Tools are gated per app via `app_config.features.dial_files`: `enabled_tools="all"` returns every tool; a list returns only the matching subset.
- Is **preview-feature-gated** via `@preview_module` — when `ENABLE_PREVIEW_FEATURES=false`, nothing is bound and the tools are invisible to the LLM.

**Owner:** `src/quickapp/dial_files_tooling/dial_files_tooling_module.py`

**Registration:** Added to the module list in `src/quickapp/app_factory.py`.

---

### Component 9: Tool configs and stage display

**What:** `OpenAiToolConfig` definitions with JSON-schema parameters, plus `ToolDisplayConfig` for the DIAL stage UI.

**Highlights:**
- Tool name prefix: `internal_file_`. Names: `internal_file_list`, `internal_file_read_lines`, `internal_file_search`, `internal_file_write`, `internal_file_edit`, `internal_file_delete`, `internal_file_copy`, `internal_file_move`.
- Stage titles: `List files`, `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`, `Copy file`, `Move file`.
- The `path` parameter renders in the stage as `**File:** {basename}` (last path segment of the display path, computed via `_to_display_path`) so the UI stays compact.

**Owner:** `src/quickapp/dial_files_tooling/_tool_configs.py`

---

### Component 10: Per-app config (`features.dial_files`)

**What:** A `DialFilesConfig` field on the existing `Features` container in `src/quickapp/config/application.py`. Lets app authors restrict which file tools are exposed and repoint the agent's home directory.

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
    "internal_file_copy",
    "internal_file_move",
]

class DialFilesConfig(BaseModel):
    enabled_tools: Literal["all"] | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['internal_file_read_lines', 'internal_file_search'])."
        ),
    )
    agent_home_dir: str = Field(
        default="files/{appdata}/",
        description=(
            "Base directory for relative path resolution. Must start with 'files/' and end with '/'. "
            "Supports the {appdata} template variable, resolved at request time via my_appdata_home(). "
            "Examples: 'files/{appdata}/' (default), 'files/shared-bucket/admin/', "
            "'files/{appdata}/workspace/'."
        ),
    )
```

**`agent_home_dir` validation (at config-load time, not request time)** — implemented as a Pydantic field validator on `DialFilesConfig`:

- Must start with `files/` and end with `/`.
- Must not contain `..` segments.
- May contain at most one `{appdata}` placeholder. No other template variables are defined; unknown `{...}` tokens are a validation error so operators catch typos early at startup rather than at first tool call.

A `pydantic.ValidationError` is raised on startup if any of these rules is violated.

**`agent_home_dir` resolution (at request time)** — performed inside `_resolve_appdata_url` as described in *Component 1*. The default `"files/{appdata}/"` resolves via `dial_client.my_appdata_home()` to `files/{home}/`.

**Wiring on `Features`:**

```python
# src/quickapp/config/application.py
class Features(BaseModel):
    timestamp: TimestampConfig | None = PreviewField(...)
    file_loading: FileLoadingConfig = Field(...)
    dial_files: DialFilesConfig | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description="Built-in DIAL files tools (list / read / search / write / edit / delete / copy / move).",
    )
```

**Resolution in `DialFilesToolingModule`:** Reads `app_config.features.dial_files` and matches each tool's name against `DialFilesToolName`, returning the matching subset (or every tool when `enabled_tools == "all"`).

**Design notes:**

- **Default semantics.** `features.dial_files` defaults to `None` — file tools are off unless the app author explicitly opts in. Once enabled, `enabled_tools` defaults to `"all"`.
- **Preview gating.** `dial_files` is a `PreviewField`. When `ENABLE_PREVIEW_FEATURES=false`, `nullify_preview_fields` clears it back to `None` and the module contributes nothing.
- **`agent_home_dir` repointing.** Operators can point the agent's home at a non-appdata bucket (e.g. `"files/org-shared-bucket/reports/"`) or at a subdirectory under appdata (e.g. `"files/{appdata}/workspace/"`). When the template omits `{appdata}`, read/search/list still work even if `my_appdata_home()` would have returned `None` — useful for app-style deployments where appdata isn't provisioned but a shared bucket is.
- **Future knobs.** `DialFilesConfig` is the natural home for additions like `max_file_size_bytes`, allow/deny path prefixes, or a default `content_type` override. (The "per-app subdir under appdata" use case is now covered by `agent_home_dir`.)

**Owner:** `src/quickapp/config/dial_files.py` and a small edit to `src/quickapp/config/application.py`.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Invalid relative `path` (empty, leading `/`, `..` segment, `../` substring, empty segment, trailing whitespace) | `InvalidToolCallParameterException("path", ...)` with the specific rule violated. Applies to the relative branch only — absolute `files/...` URLs bypass this validator (server-side rejection if malformed). |
| Absolute URL passed to mutating tools: `write_file` / `edit_file` / `delete_file` (path), `copy_file` (destination), `move_file` (source or destination) | `InvalidToolCallParameterException("path", "{tool} requires a relative path under agent_home_dir; do not pass an absolute files/... URL")`. |
| Absolute URL contains `\n` / `\r` (any tool) | `InvalidToolCallParameterException("path", "absolute URL must not contain newline characters")`. |
| `agent_home_dir` fails config-load validation (missing `files/` prefix, missing trailing `/`, unknown `{...}` token, `..` segment) | Startup error: `pydantic.ValidationError` raised by the `DialFilesConfig` field validator. The app fails to boot until the operator fixes the manifest. |
| `agent_home_dir` contains `{appdata}` but `my_appdata_home()` returns `None` at request time | `InvalidToolCallParameterException("path", "appdata namespace is not available; agent_home_dir uses {appdata} but no appdata was found")`. Tools that pass an absolute URL (and therefore skip the relative branch) are unaffected. |
| `start_line < 0` or `end_line < start_line` (`read_file_lines`) | `InvalidToolCallParameterException` → surfaced to LLM. |
| `write_file(overwrite=False)` target already exists (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("path", "file already exists: {url}; pass overwrite=True to replace")`. |
| `write_file(overwrite=True)` concurrent modification (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`. |
| `write_file` `content_type` contains `\n` or `\r` | `InvalidToolCallParameterException("content_type", "must not contain newline characters")` — client-side, before any IO. |
| `write_file` otherwise-invalid `content_type` (e.g. malformed `type/subtype`) | Passed through to DIAL; surface DIAL's response if any. No client-side allowlist (the set of valid MIME types is open-ended). |
| `edit_file` `old_string` not found / matches multiple places / equals `new_string` | `InvalidToolCallParameterException` with a precise message: "not found", "found N times; provide more surrounding context to disambiguate", or "new_string must differ from old_string". |
| `edit_file` conditional upload fails (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`. |
| `list_files` target is not a folder | `InvalidToolCallParameterException("path", "not a folder: {url}")` if DIAL response shape indicates a file. |
| `list_files` target not found (`ResourceNotFoundError`, HTTP 404) | `InvalidToolCallParameterException("path", "folder not found: {url}")`. |
| `list_files` `max_depth < 1` or `max_depth > 10` | `InvalidToolCallParameterException("max_depth", "must be in [1, 10]")`. |
| `delete_file` target not found (`ResourceNotFoundError`, HTTP 404) | `InvalidToolCallParameterException("path", "file not found: {path}")`. |
| `copy_file` / `move_file` source not found (`ResourceNotFoundError`, HTTP 404) | `InvalidToolCallParameterException("source", "source not found: {source}")`. |
| `copy_file` / `move_file` destination already exists with `overwrite=False` (`EtagMismatchError`, HTTP 412) | `InvalidToolCallParameterException("destination", "destination already exists: {url}; pass overwrite=True to replace")`. |
| `path` missing or DIAL GET fails | Error propagates from `DialFileService`; the tool returns an error result. |
| File exceeds 10 MB download limit | `InvalidToolCallParameterException("path", "file is too large to read (limit: 10 MB)")`. |
| File is not valid UTF-8 (read/search/edit) | `UnicodeDecodeError` propagates; LLM sees the error. Binary files are out of scope. |
| DIAL responds HTTP 403 Forbidden (any tool) | `InvalidToolCallParameterException("path", "access denied: {url}")`. Surfaces to the LLM as a tool-call error so it can pick a different path rather than retrying blindly. The resolved URL is included so the operator can see exactly what was attempted. **Implementation note:** the SDK (`aidial_client`) has no typed `PermissionDeniedError` subclass — 403 surfaces as the base `DialException` with `status_code == 403`. Catch `DialException` in `_DialFileTool` and branch on `e.status_code == 403` so every tool benefits without per-tool duplication. Reference: `aidial_client/_exception.py`. |

---

## Out of Scope

- **Recursive folder move/copy.** Out of scope — agents loop a `list_files` result if they need to move/copy a tree. Mirrors the existing "Recursive delete" non-scope.
- **Cross-namespace moves.** `move_file` is relative-only on both sides (within `agent_home_dir` only). Moving a file from an external bucket into the agent's home requires `copy_file` (copy + optional delete). Cross-namespace move is deferred until a use case appears.
- **Move/copy via official SDK.** Currently implemented via the private `_http_client` transport (see Component 7.5/7.6 design notes). Pending upstream addition of `files.move` / `files.copy` on `aidial_client`.
- **Destination folder auto-creation for move/copy.** Whether `/v1/ops/resource/move|copy` auto-creates intermediate folders (as `files.upload` does) is unverified for v1. Assume it mirrors upload behavior; add an explicit note if testing shows otherwise.
- **Conditional / soft delete.** `delete_file` remains unconditional within appdata; ETag-guarded delete and trash/undo semantics are deferred.
- **Multi-edit in one call.** `edit_file` replaces a single unique `old_string` per invocation. Batching is deferred.
- **Binary / non-UTF-8 files.** Read/search/edit assume UTF-8 text. `write_file` accepts any `content_type` but content is still UTF-8-encoded text. Binary upload is not supported.
- **Regex search.** `search_in_file` ships with substring + `case_insensitive` only.
- **Character/byte offset reading.** Rejected: line-based addressing is more reliable for LLMs.
- **`upload_file` (fetch from external/DIAL URL).** Considered for this revision and deferred. The existing `AttachmentService` covers the internal upload path for tool-emitted attachments; a dedicated LLM-facing upload tool is not needed yet.
- **Pagination on `list_files`.** Deferred until folder sizes warrant it. Additive optional param + sentinel in the listing when introduced.
- **Recursive delete.** Out of scope — agents loop over a `list_files` result to delete trees explicitly. Reduces blast radius.
- **MIME sniffing for `write_file`.** Caller-provided only. Sniffing risks misclassification.
- **Cross-namespace mutations.** All three mutating tools (`write_file`, `edit_file`, `delete_file`) are relative-only and target the agent's home dir. Mutating files in a bucket the agent doesn't own is deferred until a use case appears. (Operators that need agents to author into a shared namespace can repoint `agent_home_dir` itself.)
- **Per-app fixed subdirectories.** Covered by `agent_home_dir` — set `"files/{appdata}/workspace/"` (or any other prefix) to pin the agent to a subdirectory under appdata.
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
    "path":      {"type": "string",  "description": "Relative folder path under the agent's home dir (e.g. 'reports/'), or absolute DIAL folder URL starting with 'files/' (e.g. 'files/{bucket}/uploads/'). Folder paths end with '/'."},
    "max_depth": {"type": "integer", "description": "Recursion depth. 1 = immediate children only. Range: [1, 10]. Default: 1."}
  },
  "required": ["path"]
}

// read_file_lines
{
  "name": "internal_file_read_lines",
  "description": "Read a range of lines from a file stored in DIAL. Use start_line and end_line (0-indexed, end exclusive).",
  "parameters": {
    "path":       {"type": "string",  "description": "Relative path under the agent's home dir (e.g. 'reports/summary.md'), or absolute DIAL file URL starting with 'files/' (for shared or user-uploaded files)."},
    "start_line": {"type": "integer", "description": "First line to include (0-indexed)."},
    "end_line":   {"type": "integer", "description": "First line to exclude (0-indexed). Like Python slice end."}
  },
  "required": ["path", "start_line", "end_line"]
}

// search_in_file
{
  "name": "internal_file_search",
  "description": "Search for a substring in a file stored in DIAL. Returns matching lines with optional surrounding context.",
  "parameters": {
    "path":             {"type": "string",  "description": "Relative path under the agent's home dir, or absolute DIAL file URL starting with 'files/'."},
    "pattern":          {"type": "string",  "description": "Substring to search for."},
    "context_lines":    {"type": "integer", "description": "Lines of context around each match. Default: 0."},
    "case_insensitive": {"type": "boolean", "description": "If true, search is case-insensitive. Default: false."}
  },
  "required": ["path", "pattern"]
}

// write_file
{
  "name": "internal_file_write",
  "description": "Create or overwrite a UTF-8 text file under the agent's home dir. Relative path only (absolute files/... URLs are rejected). Nested paths allowed; '..' rejected. Default content_type is text/plain. overwrite=False fails on collision; overwrite=True replaces with ETag guard.",
  "parameters": {
    "path":         {"type": "string",  "description": "Relative path under the agent's home dir. Forward slashes for nesting. Rejected: leading '/', '..' segments, '../' substring, empty segments, absolute 'files/...' URLs."},
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
    "path":       {"type": "string", "description": "Relative path under the agent's home dir (e.g. 'reports/summary.md'). Absolute files/... URLs are rejected."},
    "old_string": {"type": "string", "description": "Exact substring to replace. Must occur exactly once. Include surrounding context to disambiguate."},
    "new_string": {"type": "string", "description": "Replacement text. May be empty to delete the match."}
  },
  "required": ["path", "old_string", "new_string"]
}

// delete_file
{
  "name": "internal_file_delete",
  "description": "Delete a file from DIAL storage. Hard delete; no undo.",
  "parameters": {
    "path": {"type": "string", "description": "Relative path under the agent's home dir (e.g. 'reports/old.md'). Absolute files/... URLs are rejected."}
  },
  "required": ["path"]
}

// copy_file
{
  "name": "internal_file_copy",
  "description": "Copy a file server-side in DIAL storage. Source can be relative (agent's home dir) or absolute files/... URL. Destination must be relative. No bytes downloaded.",
  "parameters": {
    "source":      {"type": "string",  "description": "Relative path under the agent's home dir, or absolute DIAL file URL starting with 'files/'. The file to copy."},
    "destination": {"type": "string",  "description": "Relative path under the agent's home dir. Absolute files/... URLs are rejected."},
    "overwrite":   {"type": "boolean", "description": "If true, replace an existing destination. Default: false."}
  },
  "required": ["source", "destination"]
}

// move_file
{
  "name": "internal_file_move",
  "description": "Move (rename) a file within the agent's home dir in DIAL storage. Both source and destination must be relative paths. The original file is removed by DIAL Core.",
  "parameters": {
    "source":      {"type": "string",  "description": "Relative path under the agent's home dir. Absolute files/... URLs are rejected."},
    "destination": {"type": "string",  "description": "Relative path under the agent's home dir. Absolute files/... URLs are rejected."},
    "overwrite":   {"type": "boolean", "description": "If true, replace an existing destination. Default: false."}
  },
  "required": ["source", "destination"]
}
```

### `list_files` output format

Listing a folder under the agent's home dir (`list_files(path="reports/", max_depth=3)`) — path column emits relative paths:

```
-  reports/
1234  reports/summary.md
56789  reports/data.csv
-  reports/images/
2048  reports/images/logo.png
```

Listing a non-home folder (`list_files(path="files/{other_bucket}/uploads/", max_depth=1)`) — path column emits absolute URLs:

```
4096  files/{other_bucket}/uploads/notes.txt
8192  files/{other_bucket}/uploads/resume.pdf
```

Columns: size (bytes, or `-` for folders), display path (relative under home dir, absolute otherwise; no indentation — depth is encoded in the path; folder paths end with `/`).

### `write_file` on success

`write_file` is relative-only; the success line always echoes the relative path:

```
File written: reports/2026-Q1/summary.md
```

### `write_file` on collision (overwrite=False)

```
InvalidToolCallParameterException: file already exists: reports/summary.md; pass overwrite=True to replace
```

### `write_file` on path traversal

```
InvalidToolCallParameterException: path must not contain '..'
```

### `write_file` on absolute URL (rejected)

```
InvalidToolCallParameterException: write_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL
```

### `delete_file` on success (home-dir target)

```
Deleted: reports/old.md
```

### `delete_file` on absolute URL (rejected)

```
InvalidToolCallParameterException: delete_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL
```

### `copy_file` on success

```
Copied to: inputs/data.csv
```

### `copy_file` on absolute destination (rejected)

```
InvalidToolCallParameterException: copy_file destination must be a relative path under agent_home_dir; do not pass an absolute files/... URL
```

### `move_file` on success

```
Moved to: final/report.md
```

### Per-app manifest

```jsonc
// All eight tools enabled (default)
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

// All eight tools enabled explicitly (including copy and move)
{
  "features": {
    "dial_files": {
      "enabled_tools": [
        "internal_file_list",
        "internal_file_read_lines",
        "internal_file_search",
        "internal_file_write",
        "internal_file_edit",
        "internal_file_delete",
        "internal_file_copy",
        "internal_file_move"
      ]
    }
  }
}

// Agent writes to a shared org bucket instead of per-request appdata
{
  "features": {
    "dial_files": {
      "agent_home_dir": "files/org-shared-bucket/reports/"
    }
  }
}

// Agent isolated to its own workspace subdir under appdata
{
  "features": {
    "dial_files": {
      "agent_home_dir": "files/{appdata}/workspace/"
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

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `dial_files_tooling/_base_file_tool.py` | `_DialFileTool` base class with `DialFileService` wiring; provides `_resolve_appdata_url(path)` with path-traversal validation. |
| `dial_files_tooling/_list_files_tool.py` | `list_files` implementation. |
| `dial_files_tooling/_read_file_lines_tool.py` | `read_file_lines` implementation. |
| `dial_files_tooling/_search_in_file_tool.py` | `search_in_file` implementation. |
| `dial_files_tooling/_write_file_tool.py` | `write_file` implementation: nested `path`, `content_type`, `overwrite`. |
| `dial_files_tooling/_edit_file_tool.py` | `edit_file` implementation. |
| `dial_files_tooling/_delete_file_tool.py` | `delete_file` implementation — no client-side path validation; appdata isolation is the safety boundary. |
| `dial_files_tooling/_copy_file_tool.py` | `copy_file` implementation — server-side copy via `/v1/ops/resource/copy`. |
| `dial_files_tooling/_move_file_tool.py` | `move_file` implementation — server-side move via `/v1/ops/resource/move`. |
| `dial_files_tooling/_stage_wrapper.py` | Stage wrapper for the DIAL UI display. |
| `dial_files_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all eight tools. |
| `dial_files_tooling/dial_files_tooling_module.py` | Preview-gated DI module; contributes tools; reads `app_config.features.dial_files`. |
| `config/dial_files.py` | `DialFilesConfig` model — `enabled_tools: Literal["all"] \| list[DialFilesToolName]`. |

### Modified files

| File | Change |
|------|--------|
| `dial_core_services/dial_file_service.py` | Add `list_folder(folder_url, max_depth=1)` (wraps `dial_client.metadata.get("files", folder_url)` with depth-bounded recursion). Add `write_file(url, content, *, content_type="text/plain", overwrite=False, if_match=None) -> str` (encapsulates `If-Match` / `If-None-Match` branching; invalidates cache on success). Add `invalidate_cache(url)`. Add `copy` and `move` methods (via private `_http_client` transport). The existing `download_file(url)` already returns `tuple[bytes, FileMetadata | None]`, so `edit_file` can recover the ETag via the metadata side of that tuple — no new method needed. |
| `dial_core_services/attachment_service.py` | No changes. |
| `app_factory.py` | Register `DialFilesToolingModule`. |
| `config/application.py` | Add `dial_files: DialFilesConfig \| None` as a `PreviewField` on `Features`. |

### New tools exposed to the LLM

- `internal_file_list(path, max_depth=1)`
- `internal_file_read_lines(path, start_line, end_line)`
- `internal_file_search(path, pattern, context_lines=0, case_insensitive=False)`
- `internal_file_write(path, content, content_type="text/plain", overwrite=False)`
- `internal_file_edit(path, old_string, new_string)` (relative-only)
- `internal_file_delete(path)` (relative-only)
- `internal_file_copy(source, destination, overwrite=False)`
- `internal_file_move(source, destination, overwrite=False)`

### Tests

- Unit: `src/tests/unit_tests/dial_files_tooling/`:
  - `_resolve_appdata_url`: relative path resolves to `agent_home_dir + path`; absolute `files/...` passes through unchanged; absolute URL with `\n` rejected; path traversal applied to relative branch only; `agent_home_dir` template with `{appdata}` resolved via `my_appdata_home()`; `agent_home_dir` without `{appdata}` does not call `my_appdata_home()` (read/search/list usable when appdata missing); appdata-missing with `{appdata}` template → descriptive error.
  - `DialFilesConfig` field validator: rejects missing `files/` prefix, missing trailing `/`, unknown `{...}` token, `..` segment — all raise `pydantic.ValidationError` at config-load time.
  - `_to_display_path`: home-dir URL → relative; non-home URL → unchanged; edge case `agent_home_dir` itself → empty relative ("").
  - `list_files`: depth-1 listing, depth-N recursion (depth bound respected), folder-not-found (`ResourceNotFoundError`), target-is-not-a-folder, `max_depth` out of range, empty folder, relative `path` input, absolute `path` input, two-column output (size + path) with relative display paths for home-dir entries and absolute for non-home.
  - `write_file`: nested path success, absolute URL rejected ("relative-only" error), path-traversal rejection (`..` segment, `../` substring, leading `/`, empty segment, trailing whitespace), `content_type` propagated to the upload call, `overwrite=False` collision (`EtagMismatchError` → `InvalidToolCallParameterException`), `overwrite=True` happy path, `overwrite=True` falls through to create when no prior file (`ResourceNotFoundError` on metadata), `overwrite=True` concurrent modification (`EtagMismatchError` → error), cache invalidated after overwrite, appdata-missing → descriptive error, success message echoes relative path.
  - `read_file_lines` / `search_in_file`: accept relative `path` (resolves through `agent_home_dir`), accept absolute `files/...` URL (pass-through), parameter rename from `file_url` to `path` reflected end-to-end.
  - `edit_file`: accept relative `path` (resolves through `agent_home_dir`), absolute `files/...` URL rejected with `InvalidToolCallParameterException`, parameter rename from `file_url` to `path` reflected end-to-end.
  - `delete_file`: success on relative path under home dir (success line shows relative form), absolute `files/...` URL rejected with `InvalidToolCallParameterException`, `ResourceNotFoundError` (404) → `InvalidToolCallParameterException("path", ...)`.
  - `DialFileService.write_file`: `content_type` defaults to `"text/plain"`, custom content type forwarded to `dial_client.files.upload`; `overwrite=False` sends `If-None-Match: *`; `overwrite=True` falls through to create on `ResourceNotFoundError` and otherwise uploads with `If-Match: <etag>`; cache invalidated on success.
  - `DialFileService.list_folder`: flat folder, recursion respects `max_depth`, depth-bound folders listed but not expanded.
  - `copy_file`: happy path (relative source), happy path (absolute source), collision with `overwrite=False` (EtagMismatchError → InvalidToolCallParameterException), overwrite with `overwrite=True`, source-missing 404 → InvalidToolCallParameterException("source", ...), absolute destination rejected, 403 → InvalidToolCallParameterException. Verify destination cache invalidated after success.
  - `move_file`: happy path (relative→relative rename), collision with `overwrite=False`, overwrite with `overwrite=True`, source-missing 404, absolute source rejected, absolute destination rejected, 403 → InvalidToolCallParameterException. Verify source AND destination cache invalidated after success.
  - `DialFileService.copy` / `DialFileService.move`: assert `/v1/` prepend on both sourceUrl and destinationUrl; assert `overwrite` flag forwarded to body.
