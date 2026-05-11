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
**Behavior:** The relative `path` resolves under the agent's home dir. Read contract is otherwise unchanged from the previous design.\
**Outcome:** Lines `[start_line, end_line)` are returned.

### UC-6b: Agent reads a non-home file (user upload or shared artifact)

**Trigger:** `read_file_lines(path="files/{other_bucket}/uploads/notes.txt", start_line=0, end_line=200)`.\
**Behavior:** The `path` starts with `files/` and is treated as an absolute DIAL URL — `_resolve_appdata_url` returns it unchanged. Used for files the agent does not own (user-uploaded attachments, shared admin artifacts).\
**Outcome:** Same as UC-6; demonstrates *when* the absolute form is the right choice.

### UC-7: Agent searches for a substring

**Trigger:** `search_in_file(path="reports/summary.md", pattern="ERROR", context_lines=2, case_insensitive=True)`.\
**Behavior / Outcome:** Unchanged from the previous design. `path` accepts the same dual form (relative under home dir, or absolute `files/...`).

### UC-8: Agent edits an existing file

**Trigger:** `edit_file(path="reports/summary.md", old_string="foo", new_string="bar")`.\
**Behavior / Outcome:** Unchanged from the previous design (unique-match string replacement, ETag-guarded upload, post-edit cache invalidation). `path` is relative-only (same rule as `write_file`).

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
**Behavior / Outcome:** Unchanged — `DialFileService` caches the download per request.

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
- Provides an inverse helper `_to_display_path(url: str) -> str` used by tool result messages: if `url` is prefixed by the resolved `agent_home_dir`, return the trailing relative portion; otherwise return `url` unchanged. Used by `write_file` / `delete_file` success lines and `list_files` row formatting to keep returned paths in the form the agent uses to address them.
- The previous design's `GENERATED_FILES_ROOT` constant is removed.

`AttachmentService` is **not** a base-class dependency — `write_file` constructs its `Attachment` directly from the URL returned by `DialFileService.upload_text`.

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

**What:** Read a line range from a UTF-8 text file. Unchanged from the previous design except for the parameter rename below.

**Parameter rename:** `file_url` → `path`. The `path` parameter accepts both shapes per *Path conventions*: a relative path under the agent's home dir, or an absolute `files/...` URL for non-home targets. Resolution goes through `_resolve_appdata_url(path)`; the rest of the algorithm (download via `DialFileService`, slice `[start_line, end_line)`, return text) is unchanged. See [`file_tools.md`](file_tools.md) Component 2.

**Owner:** `src/quickapp/dial_files_tooling/_read_file_lines_tool.py`

---

### Component 4: `search_in_file`

**What:** Substring search with optional case-insensitivity and context lines. Unchanged from the previous design except for the parameter rename below.

**Parameter rename:** `file_url` → `path`. Accepts both shapes per *Path conventions*. Resolution goes through `_resolve_appdata_url(path)`; the rest of the algorithm is unchanged. See [`file_tools.md`](file_tools.md) Component 3.

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

1. **Reject the absolute form.** If `path` starts with `files/`, raise `InvalidToolCallParameterException("path", "write_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL")`. All mutating tools share this restriction (see *Path conventions* and the design note below).
2. Resolve `url = await _resolve_appdata_url(path)`. (Path-traversal validation + `agent_home_dir` resolution happen here; failures raise before any IO.)
3. Branch on `overwrite`:
   - `overwrite == false`: call `DialFileService.upload_text(url=url, content=content, content_type=content_type, if_none_match="*")`. On `EtagMismatchError` (HTTP 412) → `InvalidToolCallParameterException("path", "file already exists: {url}; pass overwrite=True to replace")`.
   - `overwrite == true`:
     - Try `dial_client.files.get_metadata(url)` to read the current ETag.
       - On `ResourceNotFoundError` (HTTP 404, no prior file): call `upload_text(..., if_none_match="*")` — clean create. (Falls through; not an error.)
       - On success: call `upload_text(url=url, content=content, content_type=content_type, if_match=etag)`.
         - On `EtagMismatchError` (HTTP 412): `InvalidToolCallParameterException("path", "file changed concurrently; re-read and retry")`.
     - On a successful overwrite, call `DialFileService.invalidate_cache(url)` so same-turn reads see the new bytes.
4. Build an `Attachment` pointing at `url` (so the DIAL UI shows the file; attachment URLs are always absolute — the UI needs the resolved form).
5. Return `ToolCallResult(content=f"File written: {_to_display_path(url)}", content_type="text/plain", attachments=[attachment])`. Since `write_file` only accepts relative paths (see Suggestion #1 in Round 5 — resolved here), the displayed form is always the relative path the agent passed in.

**Owner:** `src/quickapp/dial_files_tooling/_write_file_tool.py`

**Design notes:**

- **Relative-only `path`.** All three mutating tools (`write_file`, `edit_file`, `delete_file`) accept only relative paths under `agent_home_dir`. Read-only tools (`list_files`, `read_file_lines`, `search_in_file`) accept either form. The agent authors and mutates files only in its own home; cross-namespace mutations are out of scope until a use case appears (see *Out of Scope*). An absolute `files/...` URL passed to a mutating tool is caught at Algorithm step 1 and rejected before any IO.
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

**What:** Unique-substring replacement with ETag-guarded upload. Unchanged from the previous design except for the parameter rename below.

**Parameter rename:** `file_url` → `path`. Accepts **relative paths only** under `agent_home_dir` (absolute `files/...` URLs are rejected — same rule as `write_file`). Resolution goes through `_resolve_appdata_url(path)` (relative branch). The rest of the algorithm (download, replace, conditional upload, cache invalidation) is unchanged. See [`file_tools.md`](file_tools.md) Component 5.

**Owner:** `src/quickapp/dial_files_tooling/_edit_file_tool.py`

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

- **No client-side validation.** Appdata isolation is the safety boundary; an LLM running in app context cannot delete files outside its own appdata namespace. The previous `generated-files/` guard, and an earlier draft's `..`-substring check, are both removed: the substring check would have rejected legitimate filenames containing `..` (e.g. `v1.2..3/log.txt`) and was redundant with appdata isolation, not a real safety layer (it could not prevent escape, only block one syntactic form).
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
- Contributes all eight tools to the shared `list[StagedBaseTool]` multiprovider via its own `@multiprovider`-decorated provider method (same pattern as the prior `TextFileToolingModule`).
- Tools are gated per app via `app_config.features.dial_files`. The resolution logic is unchanged from the previous design — `enabled_tools="all"` returns every tool; a list returns only the matching subset.
- Is **preview-feature-gated** via `@preview_module` — when `ENABLE_PREVIEW_FEATURES=false`, nothing is bound and the tools are invisible to the LLM.

**Owner:** `src/quickapp/dial_files_tooling/dial_files_tooling_module.py`

**Registration:** Added to the module list in `src/quickapp/app_factory.py`.

---

### Component 9: Tool configs and stage display

**What:** `OpenAiToolConfig` definitions with JSON-schema parameters, plus `ToolDisplayConfig` for the DIAL stage UI.

**Highlights:**
- Tool prefix renamed from `internal_text_file_` to `internal_file_`. Names: `internal_file_list`, `internal_file_read_lines`, `internal_file_search`, `internal_file_write`, `internal_file_edit`, `internal_file_delete`, `internal_file_copy`, `internal_file_move`.
- Stage titles: `List files`, `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`, `Copy file`, `Move file`.
- The `path` parameter renders in the stage as `**File:** {basename}` (last path segment of the display path, computed via `_to_display_path`) so the UI stays compact.

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

**`agent_home_dir` resolution (at request time)** — performed inside `_resolve_appdata_url` as described in *Component 1*. Default `"files/{appdata}/"` resolves identically to the previous `f"files/{home}/"` from `my_appdata_home()`, so there is no behavioral change for existing deployments.

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

**Resolution in `DialFilesToolingModule`:** Same shape as the previous design's resolver, but reads `app_config.features.dial_files` and matches against `DialFilesToolName`.

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
| `edit_file` `old_string` not found / matches multiple places / equals `new_string` | Unchanged from previous design. |
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

## Migration

### Breaking changes

- **Module rename:** `src/quickapp/text_file_tooling/` → `src/quickapp/dial_files_tooling/`. See *Summary of Changes / New files*.
- **Config-field rename:** `features.text_file_tools` → `features.dial_files`. Any in-flight manifest using the old key must be updated. No back-compat shim.
- **Tool-prefix rename:** `internal_text_file_*` → `internal_file_*`. Any saved chat history or manifest referencing the old names will not match. See *Summary of Changes / New tools exposed*.
- **`write_file` parameter rename and additions:** `filename` → `path`; `content_type` and `overwrite` added.
- **`read_file_lines` / `search_in_file` / `edit_file` / `delete_file` parameter rename:** `file_url` → `path`. For read-only tools (`read_file_lines`, `search_in_file`), the new parameter accepts both relative paths (resolved under `agent_home_dir`) and absolute `files/...` URLs (passed through unchanged). For mutating tools (`edit_file`, `delete_file`), the new parameter accepts relative paths only — absolute URLs are rejected (same rule as `write_file`). Any existing manifest or saved chat history referencing `file_url` will not match.
- **`delete_file` no longer enforces `generated-files/`.** Any caller relying on this guard for safety must migrate to the appdata isolation model.
- **Appdata is now required for write/delete.** `_WriteFileTool` (and the previous design) used `bucket = bucket_resp.appdata or bucket_resp.bucket`, silently falling back to the user's personal bucket when DIAL Core did not populate `appdata`. The new `_resolve_appdata_url` calls `dial_client.my_appdata_home()` and raises `InvalidToolCallParameterException` if it returns `None`. In our deployments QuickApps is always invoked as a DIAL application, so `appdata` is always populated; the breaking case is a deployment that calls QuickApps directly as a user (no app context). In that case, write/delete tools refuse to operate (read/search/list are unaffected). This is intentional — the old fallback could have written agent output into the user's personal upload bucket. If a future deployment needs the old fallback, add it as a `DialFilesConfig` opt-in.

The above bullets are acceptable because the feature is preview-gated and not GA.

### Non-breaking changes

- `DialFileService.upload_text` gains a `content_type` keyword (default `"text/plain"`, so existing `_EditFileTool` continues to work).
- `DialFileService` gains `list_folder` — additive.
- `AttachmentService` is unchanged.
- `DialFilesConfig` gains `agent_home_dir` (default `"files/{appdata}/"`) — existing manifests that omit the field are unaffected; relative paths continue to resolve under appdata.
- `_resolve_appdata_url` now accepts both relative and absolute (`files/...`) inputs. Existing call sites that previously passed only relative paths continue to work; new read-only call sites (`list_files`, `read_file_lines`, `search_in_file`) rely on the absolute pass-through. Mutating tools (`write_file`, `edit_file`, `delete_file`) reject absolute inputs before calling `_resolve_appdata_url`. This is a contract expansion for read tools, not a break.
- Two new tools — `internal_file_copy`, `internal_file_move` — are exposed when `dial_files.enabled_tools` is `"all"` (default) or includes the new tool names. Existing manifests that rely on `"all"` will surface the new tools automatically. To keep the previous six-tool surface, switch to an explicit `enabled_tools` list.

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
| `dial_files_tooling/_copy_file_tool.py` | `copy_file` implementation — server-side copy via `/v1/ops/resource/copy`. |
| `dial_files_tooling/_move_file_tool.py` | `move_file` implementation — server-side move via `/v1/ops/resource/move`. |
| `dial_files_tooling/_stage_wrapper.py` | Stage wrapper (carried over). |
| `dial_files_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all eight tools; renamed prefix. |
| `dial_files_tooling/dial_files_tooling_module.py` | Preview-gated DI module; contributes tools; reads `app_config.features.dial_files`. |
| `config/dial_files.py` | `DialFilesConfig` model — `enabled_tools: Literal["all"] \| list[DialFilesToolName]`. |

### Modified files

| File | Change |
|------|--------|
| `dial_core_services/dial_file_service.py` | Add `list_folder(folder_url, max_depth=1)` (wraps `dial_client.metadata.get("files", folder_url)` with depth-bounded recursion). Extend `upload_text(...)` with `content_type` keyword (default `"text/plain"`); add `copy` and `move` methods (via private `_http_client` transport). |
| `dial_core_services/attachment_service.py` | No changes. |
| `app_factory.py` | Register `DialFilesToolingModule` (replaces `TextFileToolingModule`). |
| `config/application.py` | Replace `text_file_tools: TextFileToolsConfig \| None` with `dial_files: DialFilesConfig \| None` as a `PreviewField` on `Features`. |

### New tools exposed to the LLM

- `internal_file_list(path, max_depth=1)`
- `internal_file_read_lines(path, start_line, end_line)` (parameter rename: `file_url` → `path`)
- `internal_file_search(path, pattern, context_lines=0, case_insensitive=False)` (parameter rename)
- `internal_file_write(path, content, content_type="text/plain", overwrite=False)`
- `internal_file_edit(path, old_string, new_string)` (parameter rename; relative-only)
- `internal_file_delete(path)` (parameter rename; relative-only)
- `internal_file_copy(source, destination, overwrite=False)`
- `internal_file_move(source, destination, overwrite=False)`

### Tests

- Unit: `src/tests/unit_tests/dial_files_tooling/` — all carried-over coverage from the previous design plus:
  - `_resolve_appdata_url`: relative path resolves to `agent_home_dir + path`; absolute `files/...` passes through unchanged; absolute URL with `\n` rejected; path traversal applied to relative branch only; `agent_home_dir` template with `{appdata}` resolved via `my_appdata_home()`; `agent_home_dir` without `{appdata}` does not call `my_appdata_home()` (read/search/list usable when appdata missing); appdata-missing with `{appdata}` template → descriptive error.
  - `DialFilesConfig` field validator: rejects missing `files/` prefix, missing trailing `/`, unknown `{...}` token, `..` segment — all raise `pydantic.ValidationError` at config-load time.
  - `_to_display_path`: home-dir URL → relative; non-home URL → unchanged; edge case `agent_home_dir` itself → empty relative ("").
  - `list_files`: depth-1 listing, depth-N recursion (depth bound respected), folder-not-found (`ResourceNotFoundError`), target-is-not-a-folder, `max_depth` out of range, empty folder, relative `path` input, absolute `path` input, two-column output (size + path) with relative display paths for home-dir entries and absolute for non-home.
  - `write_file`: nested path success, absolute URL rejected ("relative-only" error), path-traversal rejection (`..` segment, `../` substring, leading `/`, empty segment, trailing whitespace), `content_type` propagated to the upload call, `overwrite=False` collision (`EtagMismatchError` → `InvalidToolCallParameterException`), `overwrite=True` happy path, `overwrite=True` falls through to create when no prior file (`ResourceNotFoundError` on metadata), `overwrite=True` concurrent modification (`EtagMismatchError` → error), cache invalidated after overwrite, appdata-missing → descriptive error, success message echoes relative path.
  - `read_file_lines` / `search_in_file`: accept relative `path` (resolves through `agent_home_dir`), accept absolute `files/...` URL (pass-through), parameter rename from `file_url` to `path` reflected end-to-end.
  - `edit_file`: accept relative `path` (resolves through `agent_home_dir`), absolute `files/...` URL rejected with `InvalidToolCallParameterException`, parameter rename from `file_url` to `path` reflected end-to-end.
  - `delete_file`: success on relative path under home dir (success line shows relative form), absolute `files/...` URL rejected with `InvalidToolCallParameterException`, `ResourceNotFoundError` (404) → `InvalidToolCallParameterException("path", ...)`.
  - `DialFileService.upload_text`: `content_type` defaults to `"text/plain"`, custom content type forwarded to `dial_client.files.upload`.
  - `DialFileService.list_folder`: flat folder, recursion respects `max_depth`, depth-bound folders listed but not expanded.
  - `copy_file`: happy path (relative source), happy path (absolute source), collision with `overwrite=False` (EtagMismatchError → InvalidToolCallParameterException), overwrite with `overwrite=True`, source-missing 404 → InvalidToolCallParameterException("source", ...), absolute destination rejected, 403 → InvalidToolCallParameterException. Verify destination cache invalidated after success.
  - `move_file`: happy path (relative→relative rename), collision with `overwrite=False`, overwrite with `overwrite=True`, source-missing 404, absolute source rejected, absolute destination rejected, 403 → InvalidToolCallParameterException. Verify source AND destination cache invalidated after success.
  - `DialFileService.copy` / `DialFileService.move`: assert `/v1/` prepend on both sourceUrl and destinationUrl; assert `overwrite` flag forwarded to body.

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

---

## Review Notes — Round 5

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 7 review.** Focused review on **path consistency**: the agent should address its own appdata namespace with **relative paths**, and reserve full DIAL URLs for files it does not own (shared artifacts, user uploads, admin-context attachments). The current design half-adopts this principle — `write_file` is relative-only — but every other tool, every example, and the `list_files` output force the LLM back into the absolute-URL mental model. The result is an asymmetric surface where the agent writes `summary.md` but must immediately read it back as `files/{appdata}/reports/2026-Q1/summary.md`. This is the worst of both worlds: relative paths give no ergonomic benefit, and the LLM still has to learn the absolute-URL shape. The four blocking issues below align the surface on a single rule: **relative-or-absolute everywhere the agent can plausibly own the target; absolute-only only where it cannot**.

### Blocking issues

1. **[Resolved]** **[Components 3, 4, 6, 7 / UC-6, UC-7, UC-8, UC-9 — `file_url` parameters should also accept a relative appdata path.]**
   `read_file_lines`, `search_in_file`, `edit_file`, and `delete_file` take a parameter strictly named `file_url` and described as "URL of the file in DIAL storage". With the new appdata-relative semantics established for `write_file`, this is asymmetric: the agent writes `reports/summary.md`, gets back the absolute URL in the success message, and must use that absolute URL to read/edit/delete it on the next turn. Under the user's stated principle ("relative paths for the agent's home dir"), the right shape is: each of these four tools accepts **either** a relative path (resolved through `_resolve_appdata_url`) **or** an absolute DIAL URL starting with `files/` (passed through unchanged, used for non-appdata files like user uploads or shared admin artifacts).
   **Suggestion:** Generalize `_resolve_appdata_url` (or add a sibling helper `_resolve_path_or_url`) that returns the URL as-is when the input starts with `files/`, and resolves through appdata otherwise. Apply uniformly across `list_files`, `read_file_lines`, `search_in_file`, `edit_file`, `delete_file`. Rename the parameter from `file_url` to `path` everywhere for consistency with `write_file` and `list_files`, and update the parameter description: "Relative path under appdata (e.g. `reports/summary.md`) or absolute DIAL file URL starting with `files/` (for shared or user-uploaded files)." Update the tool schemas in *Configuration / Usage Examples* and the UC triggers accordingly.

2. **[Resolved]** **[Components 2, 5 / UC-3, write_file output / list_files output — return values must emit relative paths for appdata-owned targets.]**
   The doc shapes the agent's input to allow relative paths but its output is absolute-only:
   - `write_file` success message (line 471): `File written: https://dial-storage/.../files/<appdata>/reports/2026-Q1/summary.md`.
   - `delete_file` success message (line 489): same absolute shape.
   - `list_files` text format (lines 459-464, column 4): every entry shows its full URL, even when the entry is under appdata.
   Under the user's principle, when the tool *knows* it just operated on an appdata target, it should echo back the appdata-relative path the agent passed in. Showing the absolute URL teaches the LLM the wrong default and forces it to track two namespaces simultaneously.
   **Suggestion:** Define and apply a single output rule: for entries under the current request's appdata home, emit `appdata:reports/summary.md` (or `./reports/summary.md`, or just `reports/summary.md` — pick a scheme); for entries outside appdata, emit the full `files/{bucket}/...` URL. Update `write_file`'s success line, `delete_file`'s success line, and `list_files` column 4 to use this rule. State the rule once (probably in Component 1 or a new "Path conventions" subsection) and refer to it from the per-component docs.

3. **[Resolved]** **[UC-1, UC-2, UC-9 / Configuration examples — examples should show relative paths for appdata operations, full URLs only for non-appdata.]**
   The use-case triggers currently set the wrong precedent:
   - UC-1: `list_files(path="files/{appdata}/reports/", max_depth=1)` — absolute URL into appdata.
   - UC-9: `delete_file(file_url="files/{appdata}/reports/old.md")` — absolute URL into appdata.
   - UC-6: `read_file_lines(file_url=..., start_line=0, end_line=50)` — opaque, but the description "any accessible URL (appdata or otherwise)" plus the absolute examples implicitly endorse the absolute form for appdata.
   These examples define the contract for the LLM-facing prompt that ships with the tools and for the integration tests. As-written, they will encode "always use absolute URLs" into the model's behavior even though the surface technically accepts relative paths.
   **Suggestion:** Rewrite each appdata-targeting use case to use a relative path: `list_files(path="reports/", max_depth=1)`, `delete_file(path="reports/old.md")`. Add a new use case (or extend UC-6) that explicitly demonstrates the absolute-URL form for a non-appdata target — e.g. reading a user-uploaded file from the conversation's attachments — so it is clear *when* the absolute form is the right choice. The Configuration / Usage Examples block should mirror this split.

4. **[Resolved]** **[Component 1 / Migration — `_resolve_appdata_url` contract must document the relative-vs-absolute branching.]**
   Component 1 step 3-4 describes `_resolve_appdata_url` as always prepending `files/{home}/` to the input. If blocking issues #1-3 are adopted, this helper must instead detect the absolute form (`startswith("files/")`) and return it unchanged. Without this branch, passing an absolute URL through the helper would produce `files/{appdata}/files/{other_bucket}/...`. The path-traversal validation must also apply only to the relative branch (an absolute URL containing `..` is the caller's responsibility to validate — and in practice DIAL Core rejects bad URLs server-side).
   **Suggestion:** Rewrite Component 1 step 3 to: "If `path` starts with `files/`, treat it as a fully-qualified DIAL URL and return it unchanged (after a minimal sanity check: no embedded newlines, non-empty). Otherwise, apply the path-traversal validator and prepend `files/{home}/` after resolving `home` via `await dial_client.my_appdata_home()` (raise `InvalidToolCallParameterException` on `None`)." Update the parameter docstrings and error messages to reflect that both shapes are accepted. Note in *Migration / Breaking changes* that the helper now accepts pre-resolved URLs as a pass-through (this is a contract expansion, not a break — but it changes the helper's responsibility surface).

### Suggestions

1. **[Resolved]** **[Component 5 / write_file — clarify whether `path` accepts an absolute URL.]**
   If blocking issue #1 generalizes the other tools to accept both shapes, `write_file` becomes the lone outlier that *only* accepts relative paths. The author should decide explicitly: either (a) `write_file` also accepts an absolute `files/{some_bucket}/...` URL and writes there if the caller has permission (useful for writing into a shared admin namespace), or (b) `write_file` stays appdata-only on the principle that "the agent only authors files in its own home". Either is defensible; the doc should state which and why. Most likely (b), with a note in *Out of Scope*: "writing outside appdata — agents author in their own home; cross-namespace writes are deferred until a use case appears."

2. **[Resolved]** **[Component 1 / new subsection — add an explicit "Path conventions" subsection.]**
   The path rule is now load-bearing across every tool. Rather than scatter it across per-component docs, add a short subsection (under *Proposed Design* or *Component 1*) titled **Path conventions** that states the rule once: relative paths address appdata; absolute `files/...` URLs address anywhere the caller has access; tools accept either form (except `write_file`, per suggestion #1); return values use the form that matches the target's namespace. This becomes the canonical reference and shortens the per-component prose.

### Nits

1. **[Resolved]** **[Configuration / Usage Examples — tool schema descriptions should hint at both forms.]**
   Each `parameters.path` / `parameters.file_url` description in the JSON-schema block should mention the dual form once: `"Relative path under appdata (e.g. 'reports/summary.md'), or absolute DIAL URL starting with 'files/' for shared files."` This is the prompt the LLM literally sees, so the wording matters more than for human-facing docs.

### Changes since previous round

- Path-consistency review was not in scope of Rounds 1-4. All four blocking issues above are new findings driven by the user's stated principle ("LLM should operate with relative paths for its home dir, absolute URLs only for shared/admin contexts"). No prior-round items are affected.

---

## Review Notes — Round 6

- **Reviewer:** Andrii
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 7 review.** One new feature: introduce `agent_home_dir` on `DialFilesConfig` to make the base directory for relative path resolution configurable. The field supports a `{appdata}` template variable (resolved at request time) so operators can point the agent's home anywhere inside DIAL storage while keeping appdata as the default.

### Blocking issues

1. **[Resolved]** **[Component 10 / DialFilesConfig — add `agent_home_dir` field.]**
   Add a new field to `DialFilesConfig`:

   ```python
   agent_home_dir: str = Field(
       default="files/{appdata}/",
       description=(
           "Base directory for relative path resolution. Must start with 'files/' and end with '/'."
           " Supports the {appdata} template variable, resolved at request time via my_appdata_home()."
           " Examples: 'files/{appdata}/' (default), 'files/shared-bucket/admin/',"
           " 'files/{appdata}/workspace/'."
       ),
   )
   ```

   **Validation (at config-load time, not request time):**
   - Must start with `files/` and end with `/`.
   - Must not contain `..` segments.
   - May contain at most one `{appdata}` placeholder (no other template variables are defined; unknown `{...}` tokens are a validation error so operators catch typos early).

   **Resolution (at request time, inside `_resolve_appdata_url`):**
   - If the template contains `{appdata}`: call `await dial_client.my_appdata_home()`. If it returns `None`, raise `InvalidToolCallParameterException("path", "appdata namespace is not available; agent_home_dir uses {appdata} but no appdata was found")`. Substitute the returned path string for `{appdata}`.
   - If the template contains no `{appdata}`: use as-is — no SDK call is needed, so read/search/list work even when appdata is unavailable.
   - Append the validated relative path to the resolved `agent_home_dir`.

   **Default preserves current behavior.** `"files/{appdata}/"` resolves identically to the current `f"files/{home}/"` from `my_appdata_home()`. No behavioral change for existing deployments.

2. **[Resolved]** **[Component 1 — update `_resolve_appdata_url` to use `agent_home_dir`.]**
   Replace the current step 3 ("Calls `await dial_client.my_appdata_home()`...") with the two-branch resolution described in blocking issue #1. The helper needs access to `DialFilesConfig.agent_home_dir`; inject `DialFilesConfig` into `_DialFileTool` (or pass it from the module during construction — follow whichever pattern the existing tool-config injection uses).

   The path-traversal validator (no leading `/`, no `..` segments, no empty segments, no trailing whitespace) continues to apply to the *relative* portion only. The `agent_home_dir` itself is validated at config-load time.

3. **[Resolved]** **[Error Handling table — add `agent_home_dir`-related errors.]**
   Add two rows:
   - `agent_home_dir` fails config-load validation (missing `files/` prefix, missing trailing `/`, unknown `{...}` token, `..` segment) → startup error (Pydantic `ValidationError`), not a runtime `InvalidToolCallParameterException`.
   - `agent_home_dir` contains `{appdata}` but `my_appdata_home()` returns `None` at request time → `InvalidToolCallParameterException("path", "appdata namespace is not available; agent_home_dir uses {appdata} but no appdata was found")`.

### Suggestions

1. **[Resolved]** **[Component 10 / Migration — `agent_home_dir` is a new optional config key; document its default.]**
   Add a note to *Migration / Non-breaking changes*: "`DialFilesConfig` gains `agent_home_dir` (default `"files/{appdata}/"`) — existing manifests that omit the field are unaffected; relative paths continue to resolve under appdata."

2. **[Resolved]** **[Configuration / Usage Examples — add a manifest example for a non-default `agent_home_dir`.]**
   Add one example showing a shared-bucket deployment:
   ```jsonc
   // Agent writes to a shared org bucket instead of per-request appdata
   {
     "features": {
       "dial_files": {
         "agent_home_dir": "files/org-shared-bucket/reports/"
       }
     }
   }
   ```
   And one showing an appdata subdirectory:
   ```jsonc
   // Agent isolated to its own workspace subdir under appdata
   {
     "features": {
       "dial_files": {
         "agent_home_dir": "files/{appdata}/workspace/"
       }
     }
   }
   ```

### Nits

1. **[Resolved]** **[Out of Scope — remove the "per-app `subdir`" deferred item.]**
   The last bullet in *Out of Scope* reads: "LLM-controlled subdirectories under a fixed root … A per-app `subdir` config field can be added on `DialFilesConfig` if a deployment wants to namespace agents further." `agent_home_dir` covers this use case (set `"files/{appdata}/workspace/"` for a fixed subdir under appdata). Remove or replace that bullet with a forward reference: "Use `agent_home_dir` to pin the agent to a subdirectory under appdata (e.g. `'files/{appdata}/workspace/'`)."

### Changes since Round 5

- Round-5 blocking #1 (Components 3, 4, 6, 7 accept relative-or-absolute) — **resolved.** `read_file_lines`, `search_in_file`, `edit_file`, `delete_file` now expose a single `path` parameter (renamed from `file_url`) that accepts both shapes. `_resolve_appdata_url` dispatches on the `files/` prefix per *Path conventions*.
- Round-5 blocking #2 (return values emit relative for home-dir targets) — **resolved.** Added `_to_display_path` helper in Component 1. `write_file`, `delete_file`, and `list_files` column 4 all run their output URLs through it; home-dir entries appear relative, non-home entries appear absolute. Sample outputs in *Configuration / Usage Examples* updated accordingly.
- Round-5 blocking #3 (use-case examples use relative paths for home-dir operations) — **resolved.** UC-1, UC-2, UC-6, UC-7, UC-8, UC-9 rewritten with relative paths. Added UC-6b demonstrating the absolute form for a non-home (user-uploaded) target.
- Round-5 blocking #4 (`_resolve_appdata_url` documents the branching) — **resolved.** Component 1 steps 1–5 now describe the absolute-vs-relative branches, the per-branch validation rules, and the home-dir resolution explicitly. *Migration / Non-breaking changes* notes the contract expansion.
- Round-5 suggestion #1 (`write_file` relative-only) — **resolved.** Algorithm step 1 explicitly rejects absolute `files/...` URLs; a new design note (*Relative-only `path`*) records the rationale and points to *Out of Scope* (cross-namespace writes). *Configuration / Usage Examples* shows the rejection error.
- Round-5 suggestion #2 (add *Path conventions* subsection) — **resolved.** New subsection at the end of Component 1; per-component prose now defers to it.
- Round-5 nit #1 (tool schema hints at both forms) — **resolved.** Every `path` parameter description in the JSON-schema block names the dual form; `write_file`'s description explicitly excludes the absolute form.

### Changes since Round 6

- Round-6 blocking #1 (`agent_home_dir` field on `DialFilesConfig`) — **resolved.** Component 10 schema gains `agent_home_dir` with the field validator (startup-time) and the description from the review. Default `"files/{appdata}/"` preserves current behavior.
- Round-6 blocking #2 (`_resolve_appdata_url` uses `agent_home_dir`) — **resolved.** Component 1 step 4 substitutes `{appdata}` only when present and skips `my_appdata_home()` otherwise — read/search/list now work even without appdata when `agent_home_dir` is repointed to a fixed bucket. Component 1 also notes `DialFilesConfig` is injected into the base class.
- Round-6 blocking #3 (Error Handling additions for `agent_home_dir`) — **resolved.** Two new rows: startup `pydantic.ValidationError` for bad templates; runtime `InvalidToolCallParameterException` for `{appdata}` template with no appdata.
- Round-6 suggestion #1 (Migration note) — **resolved.** *Non-breaking changes* includes the `agent_home_dir` bullet ("default `"files/{appdata}/"` — existing manifests unaffected").
- Round-6 suggestion #2 (manifest examples) — **resolved.** Two new manifests in *Configuration / Usage Examples*: shared org bucket and appdata workspace subdir.
- Round-6 nit #1 (drop "per-app `subdir`" bullet from *Out of Scope*) — **resolved.** Removed; replaced with the "per-app fixed subdirectories" entry that points to `agent_home_dir`. Also added "cross-namespace writes" as the new deferred item for `write_file`'s relative-only constraint.

---

## Review Notes — Round 7

- **Reviewer:** Andrii
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. Three changes tighten the surface area: (1) shrink the `list_files` output to path + size only — drop the `F`/`D` type column and the redundant `name` column; (2) make `edit_file` and `delete_file` relative-only, matching `write_file` (all *mutating* tools confined to `agent_home_dir`); (3) explicitly handle DIAL's 403 Forbidden response across every tool.

### Blocking issues

1. **[Component 2 / `list_files` — reduce output to path + size only.]**
   Current output has four columns: type (`F`/`D`), size, name, display path. The name column is redundant with the display path (the basename is the last segment), and the type marker is also redundant — folders end with `/` in the display path. Reduce to two columns: size, path.

   New format:
   ```
   -      reports/
   1234   reports/summary.md
   56789  reports/data.csv
   -      reports/images/
   2048   reports/images/logo.png
   ```

   - Column 1: size in bytes (right-padded), or `-` for folders.
   - Column 2: display path — relative under the agent's home dir, or absolute `files/...` URL otherwise (via `_to_display_path`). Folders keep their trailing `/`.
   - Drop the two-space-per-depth indentation: depth is already encoded in the path (`reports/images/logo.png` is two levels deep). Removing it makes parsing trivial and saves tokens.

   Update Component 2 Algorithm step 4, *Configuration / Usage Examples → `list_files` output format*, and any UC text that references the four-column layout (UC-1, UC-2).

2. **[Components 6 & 7 — `edit_file` and `delete_file` become relative-only, matching `write_file`.]**
   The three mutating tools (`write_file`, `edit_file`, `delete_file`) should share the same path contract: relative under `agent_home_dir`, no absolute `files/...` URLs. The agent edits and deletes only what lives in its own home. Cross-namespace mutations are out of scope (already true for `write_file`).

   Concrete changes:
   - **Component 6 (`edit_file`):** Remove "Accepts both shapes per *Path conventions*." Replace with: "Relative path under `agent_home_dir` only. Absolute `files/...` URLs are rejected at validation (same shape as `write_file`)." Update the algorithm to call `_resolve_appdata_url` in the relative-only mode.
   - **Component 7 (`delete_file`):** Update the `path` parameter description: "Relative path under the agent's home dir. Absolute `files/...` URLs are rejected." Remove the "echoes the namespace form of the target" wording from step 3 — the success message always uses the relative form (mirrors `write_file`). Remove the UC for deleting a non-home target if any exists.
   - **Path conventions subsection (Component 1):** Reword to say *read-side* tools (`list_files`, `read_file_lines`, `search_in_file`) accept both forms; *write-side* tools (`write_file`, `edit_file`, `delete_file`) are relative-only.
   - **Error Handling:** Generalize the existing "Absolute URL passed to `write_file`" row to "Absolute URL passed to `write_file` / `edit_file` / `delete_file`" with the same error shape.
   - **Configuration / Usage Examples:** Update *`delete_file` on success (non-home target)* — remove the example, or replace with a rejection example mirroring *`write_file` on absolute URL (rejected)*.
   - **Out of Scope:** Update the "Cross-namespace writes" bullet to "Cross-namespace mutations" and note it covers `write_file`, `edit_file`, and `delete_file`.

3. **[Error Handling — handle 403 Forbidden from DIAL Core.]**
   Any of the underlying SDK calls (`dial_client.metadata.get`, `dial_client.files.get_metadata`, `files.upload`, `files.delete`, `DialFileService.download_*`) can return HTTP 403 when the caller lacks permission for the resolved URL — most likely when `agent_home_dir` points at a bucket the per-request token isn't authorized for, or when a read-side tool is handed an absolute URL the agent can't access.

   Add one row to the Error Handling table, applied uniformly to every tool:
   - DIAL responds 403 Forbidden (any tool) → `InvalidToolCallParameterException("path", "access denied: {url}")`. The error is surfaced to the LLM as a tool-call error so it can pick a different path rather than retrying blindly. The resolved URL is included so the LLM (and the operator reading the trace) can see exactly what was attempted.

   Implementation note: the SDK raises a typed `PermissionDeniedError` (or HTTPX `HTTPStatusError` with `response.status_code == 403` depending on which call path) — catch in `_DialFileTool` so every tool benefits without per-tool duplication.

### Suggestions

_None._

### Nits

_None._

### Changes since Round 7

**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 9 review.**

- Round-7 blocking #1 (`list_files` output reduced to size + path, no indentation) — **resolved** (completed in Round 12). Component 2 Algorithm step 4 reduced to two columns (size, path); indentation removed. "Why text output over JSON" design note trimmed. Configuration / Usage Examples samples and column legend updated. UC-1 and UC-2 outcome text updated.
- Round-7 blocking #2 (`edit_file` / `delete_file` relative-only) — **resolved.** Path conventions subsection rewritten (read-only tools accept both forms; mutating tools are relative-only). Component 6 updated to reject absolute URLs. Component 7 parameter table, algorithm, and design notes updated; success message is now always relative form. Tool schemas updated. `delete_file` non-home success sample replaced with absolute-URL rejection sample. UC-8 and UC-9 updated. Error Handling row generalized to all three mutating tools. Out of Scope bullet renamed to "Cross-namespace mutations". Test list updated (edit_file: absolute URL rejection; delete_file: absolute URL rejection instead of non-home success). Migration breaking-changes note updated. `_resolve_appdata_url` non-breaking expansion note updated.
- Round-7 blocking #3 (403 handling) + Round-8 factual correction — **resolved.** Added 403 Forbidden row to Error Handling table. Implementation note uses `DialException(status_code=403)` (the actual SDK shape) instead of the non-existent `PermissionDeniedError` as flagged by Round 8.

---

## Review Notes — Round 8

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 9 review.** Round 7 introduced three blocking items from the author; none of them have been applied to the doc body yet (Component 2 still shows the four-column listing, Components 6/7 still describe the dual-form `path` for `edit_file` / `delete_file`, and the Error Handling table has no 403 row). In addition, one of Round 7's own claims — that the SDK surfaces 403 as a typed `PermissionDeniedError` — is factually incorrect against the installed `aidial_client` and would mislead the implementer. Once the three Round-7 blocks are applied, the surface looks coherent; the rest of the doc is in good shape.

### Blocking issues

1. **[Resolved] [Round-7 #1 — Component 2 / Configuration examples / UC-1, UC-2.]** The doc body still describes a four-column `list_files` output (type, size, name, display path) with two-space-per-depth indentation. Concrete locations that must change to the new two-column (size, path) layout:
   - Component 2 Algorithm step 4 (lines 154-168 of the doc body) — still enumerates "Column 1: `F`/`D`", "Column 2: size", "Column 3: name", "Column 4: display path" and explicitly states "**Indentation: two spaces per depth level**".
   - Configuration / Usage Examples → `list_files` output format (lines 510-529) — still shows the four-column rendered output for both the home-dir and non-home cases.
   - UC-1 Outcome (line 34) and UC-2 Outcome (line 40) — reference "one entry per child (file or folder) with name, type, and size" / "bounded, traversable listing"; these read OK with the new two-column shape but should be re-checked once the rendered samples change.
   **Suggestion:** Apply Round-7 #1 as specified. After editing, re-read Component 2's design notes (the "Why text output over JSON" bullet currently references column-4 inclusion of the URL — it stays correct under the new shape but the wording should be re-checked).

2. **[Resolved] [Round-7 #2 — Components 6, 7 / Component 1 Path conventions / Error Handling / Configuration examples / UC-8, UC-9.]** `edit_file` and `delete_file` still accept the dual form. Concrete locations:
   - Component 1 *Path conventions* (lines 128-134) — still says "Tool inputs (`path` parameter) accept either form, except `write_file` which is relative-only". This must split read-side (`list_files`, `read_file_lines`, `search_in_file`) from write-side (`write_file`, `edit_file`, `delete_file`).
   - Component 6 (line 252) — "Accepts both shapes per *Path conventions*" must flip to relative-only with the same rejection shape as `write_file`.
   - Component 7 *Parameters* table (line 266) and Algorithm step 3 (line 272) — `path` description and "echoes the namespace form of the target" must change; the success message becomes relative-only.
   - Error Handling row at line 394 — "Absolute URL passed to `write_file`" must be generalized to `write_file` / `edit_file` / `delete_file`.
   - Tool schemas in *Configuration / Usage Examples* (lines 487-507) — `edit_file` and `delete_file` descriptions still advertise the dual form.
   - Sample output *`delete_file` on success (non-home target)* (lines 563-567) — drop or replace with a rejection example.
   - UC-9 (lines 82-86) — "Absolute `files/...` URLs are also accepted (for cleanup of non-home targets the agent has permission to delete)" must be removed.
   - *Out of Scope* "Cross-namespace writes" bullet (line 427) — rename to "Cross-namespace mutations" and extend to all three write-side tools.
   - Tests for `delete_file` (line 690) — the "success on absolute non-home URL" assertion is now an absolute-URL rejection assertion.

3. **[Resolved] [Round-7 #3 with factual correction — Error Handling.]** The Error Handling table has no row for HTTP 403. Add the row Round 7 specifies. **However, Round 7's implementation note that "the SDK raises a typed `PermissionDeniedError`" is wrong against the installed `aidial_client==<current>`.** The SDK's `_exception.py` defines only `DialException` (base), `InvalidRequestError` (400), `InvalidDialURLError`, `NotDialURLError`, `ParsingDataError` (422), `EtagMismatchError` (412), and `ResourceNotFoundError` (404). A 403 surfaces as the base `DialException` with `status_code == 403`, not as a typed subclass. The implementation guidance must therefore be: catch `DialException` in `_DialFileTool` and dispatch on `status_code == 403`, **or** check `aidial_client` whether a typed 403 exception was added in a later release the project pins to.
   **Suggestion:** Add the row as Round 7 specified, but rewrite the implementation note to: "The SDK surfaces 403 as `DialException` with `status_code == 403` (no typed subclass exists in the currently pinned `aidial_client`). Catch `DialException` in `_DialFileTool._handle_dial_error` (or equivalent) and branch on `status_code` so every tool benefits without per-tool duplication. If a future SDK version adds `PermissionDeniedError`, switch to that." Reference: `aidial_client/_exception.py`.

### Suggestions

1. **[Resolved] [Component 2 — "Why text output over JSON" design note trimmed.]** Reduced to one sentence stating that the path column doubles as the argument to pass to other file tools.

2. **[Resolved] [Component 7 / Tests — `delete_file` test list updated.]** The non-home success case replaced with an absolute-URL rejection test.

### Nits

1. **[Header — `Supersedes` row but `template.md` doesn't include it.]** `template.md` (this repo's canonical structure) lists only Status and Dependencies. `Supersedes:` here is a fine addition (matches `file_tools.md` lineage) and worth keeping; flag only because Round-1 nit #1 already noted the `Owner` discrepancy. The two header fields together suggest `template.md` should grow `Owner` and `Supersedes` rows, but that's a separate change.

2. **[Round-7 self-status annotation embedded in Round 6.]** Round 6's block ends with the author's own status note "**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 7 review.**" — the same anti-pattern Round 4 nit #1 flagged for Round 3. Harmless history noise; leave for future cleanup.

### Changes since Round 8

- Round-7 blocking #1 (`list_files` output reduced to size + path) — **resolved.** See "Changes since Round 7" above.
- Round-7 blocking #2 (`edit_file` / `delete_file` relative-only) — **resolved.** See "Changes since Round 7" above.
- Round-7 blocking #3 + Round-8 factual correction (403 / `PermissionDeniedError`) — **resolved.** See "Changes since Round 7" above.

---

## Review Notes — Round 9

- **Reviewer:** Andrii
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. DIAL Core exposes first-class `POST /v1/ops/resource/move` and `POST /v1/ops/resource/copy` endpoints (see `.a_onlylocal/DIAL_Core_API.postman_collection.json` lines 666-700). The previous *Out of Scope* deferral ("would be a download + upload + delete") is no longer accurate. Add two complementary tools — `move_file` and `copy_file` — using the native endpoints. Both fit alongside `write_file` / `edit_file` / `delete_file` and reuse the existing path-resolution machinery.

### Blocking issues

1. **[Component 7.5 (new) — `copy_file` tool.]**

   **What:** Internal tool that copies a file from `source` to `destination` via DIAL's `POST /v1/ops/resource/copy` endpoint. The source can live anywhere the agent has read access (its home dir or an absolute `files/...` URL); the destination must be inside `agent_home_dir`. This is the primary way for agents to ingest user uploads or shared artifacts into their workspace without re-uploading bytes.

   **Parameters:**

   | Name | Type | Required | Default | Description |
   |------|------|----------|---------|-------------|
   | `source` | string | yes | — | Relative path under the agent's home dir, or absolute DIAL URL starting with `files/`. The file to copy from. |
   | `destination` | string | yes | — | Relative path under the agent's home dir. Absolute `files/...` URLs are rejected (mirrors `write_file`). |
   | `overwrite` | boolean | no | `false` | If `false`, fails when the destination already exists. If `true`, replaces the destination. |

   **Algorithm:**
   1. Reject absolute `destination` (same shape as `write_file`'s rejection).
   2. `source_url = await _resolve_appdata_url(source)` — read-side, accepts both forms.
   3. `destination_url = await _resolve_appdata_url(destination)` — write-side, relative-only.
   4. Call `DialFileService.copy(source_url, destination_url, overwrite)` (new method — see blocking #4).
   5. On success → invalidate the destination in `DialFileService` cache so subsequent reads see the new file; build an `Attachment` pointing at `destination_url`; return `ToolCallResult(content=f"Copied to: {_to_display_path(destination_url)}", content_type="text/plain", attachments=[attachment])`.
   6. Errors map per blocking #5.

   **Owner:** `src/quickapp/dial_files_tooling/_copy_file_tool.py`

   **Design notes:**
   - **Asymmetric source/destination.** Source accepts both forms because copying *from* a user upload into the agent's home is a primary use case. Destination is relative-only because every write-side tool is relative-only (Round 7 blocking #2).
   - **No client-side byte transfer.** The DIAL primitive is server-side; the agent never downloads-then-uploads. This is the point of using the native endpoint.
   - **`Attachment` on success.** Mirrors `write_file` — the DIAL UI gets a clickable result for the new file.

2. **[Component 7.6 (new) — `move_file` tool.]**

   **What:** Internal tool that moves a file from `source` to `destination` via DIAL's `POST /v1/ops/resource/move` endpoint. Both `source` and `destination` must live inside `agent_home_dir` — moving deletes the source, and the agent should not be deleting files it doesn't own (consistent with `delete_file`'s relative-only contract from Round 7 blocking #2).

   **Parameters:**

   | Name | Type | Required | Default | Description |
   |------|------|----------|---------|-------------|
   | `source` | string | yes | — | Relative path under the agent's home dir. Absolute `files/...` URLs are rejected. |
   | `destination` | string | yes | — | Relative path under the agent's home dir. Absolute `files/...` URLs are rejected. |
   | `overwrite` | boolean | no | `false` | If `false`, fails when the destination already exists. If `true`, replaces the destination. |

   **Algorithm:**
   1. Reject absolute `source` and absolute `destination` at validation (same error shape as `write_file`).
   2. `source_url = await _resolve_appdata_url(source)`; `destination_url = await _resolve_appdata_url(destination)`.
   3. Call `DialFileService.move(source_url, destination_url, overwrite)` (new method — see blocking #4).
   4. On success → invalidate **both** entries in `DialFileService` cache (source is gone, destination is new); build an `Attachment` pointing at `destination_url`; return `ToolCallResult(content=f"Moved to: {_to_display_path(destination_url)}", content_type="text/plain", attachments=[attachment])`.
   5. Errors map per blocking #5.

   **Owner:** `src/quickapp/dial_files_tooling/_move_file_tool.py`

   **Design notes:**
   - **Both endpoints relative-only.** Move is "delete source + create destination"; both halves are mutations, so both halves are confined to `agent_home_dir`. Cross-namespace moves are out of scope (same rationale as cross-namespace deletes).
   - **Use `move_file` for rename.** Same directory, different filename — DIAL handles rename via move.
   - **No batch move.** One file per call; agents loop a `list_files` result if they need to move a tree.

3. **[Component 9 — register the two new tools.]**
   - Add `internal_file_copy` and `internal_file_move` to the `DialFilesToolName` `Literal` in Component 10.
   - Add `OpenAiToolConfig` entries and stage titles: `Copy file`, `Move file`. Both render the `destination` parameter as `**File:** {basename}` (matches `write_file`).
   - Update Component 8's bind list and `@multiprovider` to include `_CopyFileTool` and `_MoveFileTool`.

4. **[Component 1 — extend `DialFileService` with `move` / `copy` methods.]**
   The SDK's `dial_client.files` resource does not expose move or copy — both endpoints are reached via raw HTTP (verified against `aidial_client/resources/files.py`: only `upload`, `delete`, `get_metadata`, and download methods). Add two methods on `DialFileService`:

   - `async def move(source_url: str, destination_url: str, overwrite: bool) -> None`
   - `async def copy(source_url: str, destination_url: str, overwrite: bool) -> None`

   Both POST to `/v1/ops/resource/{move|copy}` with body `{"sourceUrl": "/v1/" + source_url, "destinationUrl": "/v1/" + destination_url, "overwrite": overwrite}`. (Note: the ops endpoints take `/v1/files/...` URLs in the body, not the bare `files/...` shape — prepend `/v1/` at the call site. The Postman collection in `.a_onlylocal/DIAL_Core_API.postman_collection.json` confirms this format.)

   Use the SDK's underlying HTTP client (`dial_client._http_client` or equivalent) so auth headers are shared with every other DIAL call. Map non-2xx responses to the same exception hierarchy the rest of `DialFileService` uses, so the base-class error handler (`DialException` with `status_code` dispatch — per Round 8 blocking #3 correction) catches them uniformly.

5. **[Error Handling table — add rows for `copy_file` and `move_file`.]**
   - `copy_file` / `move_file`: source missing (404) → `InvalidToolCallParameterException("source", "source not found: {source}")`.
   - `copy_file` / `move_file`: destination exists with `overwrite=False` (412) → `InvalidToolCallParameterException("destination", "destination already exists: {url}; pass overwrite=True to replace")`.
   - Absolute `destination` (and absolute `source` for `move_file`) — generalize the existing write-side row to include the new tools: "Absolute URL passed to `write_file` / `edit_file` / `delete_file` / `move_file` / `copy_file` (destination)".
   - 403 → already covered by the global 403 row from Round 7 blocking #3 / Round 8 correction.

6. **[Out of Scope — remove the "Rename / move / copy" bullet.]**
   The bullet at line 417 currently reads: "Rename / move / copy. No primitive in the DIAL API; would be a download + upload + delete. Deferred — agents can substitute 'write new + delete old'." This is factually wrong — DIAL Core has both primitives. Remove the bullet. Add to *Non-breaking changes* (Migration): "Two new tools — `internal_file_copy`, `internal_file_move` — exposed when `dial_files.enabled_tools` is `"all"` (default) or includes the new tool names."

### Suggestions

1. **[Add use cases for the new tools.]**
   - **UC-12:** Agent copies a user upload into its home dir — `copy_file(source="files/{user_bucket}/uploads/data.csv", destination="inputs/data.csv")`. Demonstrates the asymmetric source/destination forms.
   - **UC-13:** Agent renames a draft — `move_file(source="drafts/v1.md", destination="drafts/v2.md")`.
   - **UC-14:** Agent promotes a draft to final — `move_file(source="drafts/v2.md", destination="final/report.md")`.

2. **[Configuration / Usage Examples — show success and error outputs.]**
   - `copy_file` success: `Copied to: inputs/data.csv`.
   - `move_file` success: `Moved to: final/report.md`.
   - Destination collision: `InvalidToolCallParameterException: destination already exists: inputs/data.csv; pass overwrite=True to replace`.
   - Source missing: `InvalidToolCallParameterException: source not found: drafts/v3.md`.

3. **[Tests — extend the test list in *Summary of Changes / Tests*.]**
   For each new tool, the same shape as `write_file`'s test list: happy path, collision with `overwrite=False`, overwrite with `overwrite=True`, source-missing 404, absolute-URL rejection on the relative-only side(s), 403 forbidden.

### Nits

1. **Naming.** `internal_file_copy` and `internal_file_move` match the `internal_file_*` prefix established in Round 6. Stage titles use the imperative ("Copy file", "Move file") to match the rest of the surface.

2. **No combined `copy_or_move`.** Considered briefly. Rejected: separate tools keep the schema small and the LLM's intent explicit; the source-asymmetry (copy accepts absolute source, move does not) also makes a unified tool awkward.

### Changes since Round 8

**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 11 review.**

- Round-9 blocking #1 (`copy_file` tool) — **resolved.** Component 7.5 added with full algorithm, parameter table, design notes, and `DialFileService.copy` extension.
- Round-9 blocking #2 (`move_file` tool) — **resolved.** Component 7.6 added with full algorithm, parameter table, design notes, and `DialFileService.move` extension.
- Round-9 blocking #3 (Components 9 / 10 — register new tools) — **resolved.** `internal_file_copy` and `internal_file_move` added to `DialFilesToolName` literal; `Copy file` and `Move file` stage titles added; new schemas in Configuration / Usage Examples; `_CopyFileTool` and `_MoveFileTool` added to Component 8 bind list.
- Round-9 blocking #4 (`DialFileService.move` / `copy` methods and transport) — **resolved.** Methods documented with `_http_client.request` + `FinalRequestOptions` transport; private-SDK-API risk called out explicitly in design notes.
- Round-9 blocking #5 (Error Handling rows for new tools) — **resolved.** Source-missing-404 row, destination-collision-412 row, and generalized absolute-URL row added.
- Round-9 blocking #6 (remove "Rename / move / copy" Out-of-Scope bullet) — **resolved.** Bullet removed; replaced by "Recursive folder move/copy", "Cross-namespace moves", "Move/copy via official SDK", and "Destination folder auto-creation" bullets.
- Round-9 suggestion #1 (UC-12) — **resolved.** UC-12 added to Use Cases.
- Round-9 suggestion #2 (sample outputs) — **resolved.** `copy_file` and `move_file` samples added to Configuration / Usage Examples.
- Round-9 suggestion #3 (tests) — **resolved.** Test bullets added for both tools plus `DialFileService.copy` / `DialFileService.move`.
- Round-10 blocking #2 (name the SDK transport explicitly) — **resolved.** `_http_client.request` + `FinalRequestOptions` named in both Component 7.5 and 7.6 design notes with explicit private-API risk acknowledgement.
- Round-10 blocking #3 (destination-folder, source-is-folder, same-src-dest edge cases) — **resolved.** Out-of-Scope bullet added ("Destination folder auto-creation for move/copy"); same-src-dest and source-is-folder deferred via the "Recursive folder move/copy" bullet.
- Round-10 suggestion #1 (cache invalidation note in DialFileService extension) — **resolved.** `move` and `copy` methods note they invalidate the cache themselves.
- Round-10 suggestion #2 (folder move/copy Out of Scope) — **resolved.** "Recursive folder move/copy" bullet added to Out of Scope.
- Round-10 suggestion #3 (UC-12 promoted from suggestion) — **resolved.** UC-12 is now a first-class use case in the doc body.

---

## Review Notes — Round 10

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 11 review.** Round 9 introduced six blocking items from the author (add `copy_file` / `move_file` tools backed by DIAL Core's native `/v1/ops/resource/{move,copy}` endpoints, plus the supporting wiring and Out-of-Scope correction). None of them have been applied to the doc body yet — the Round-9 block ends with the placeholder "_To be filled in once Round 9 issues are addressed._". I verified the load-bearing facts behind Round 9 against the codebase: the Postman collection at `.a_onlylocal/DIAL_Core_API.postman_collection.json` lines 666-700 documents both `POST /v1/ops/resource/move` and `POST /v1/ops/resource/copy` with `sourceUrl` / `destinationUrl` / `overwrite` bodies that use the `/v1/files/{bucket}/...` URL shape, and `aidial_client/resources/files.py` exposes only `upload` / `delete` / `get_metadata` / download — no move or copy. Round 9's premise is correct. Once the doc body is updated, the surface should be re-reviewed for a few orthogonal items called out below; they are *not* objections to the Round-9 plan, just things the author should be intentional about while applying it.

### Blocking issues

1. **[Resolved] [Round-9 #1–#6 — apply the entire Round-9 plan to the doc body.]**
   The doc body still describes a six-tool surface (`list_files`, `read_file_lines`, `search_in_file`, `write_file`, `edit_file`, `delete_file`). Locations that must change before this round can close:
   - **Component 7.5 (new):** insert the `copy_file` component between Component 7 and Component 8 per Round-9 blocking #1.
   - **Component 7.6 (new):** insert the `move_file` component per Round-9 blocking #2.
   - **Component 9 / Component 10:** add `internal_file_copy` and `internal_file_move` to `DialFilesToolName` (`config/dial_files.py`), to the `OpenAiToolConfig` list, and to the stage-title list; add the two new tool schemas to *Configuration / Usage Examples* (the abridged JSON-schema block at lines ~435-506). Stage titles should be `Copy file` and `Move file` to match the imperative pattern.
   - **Component 8:** extend the `injector.Module` bind list and the `@multiprovider` provider to include `_CopyFileTool` and `_MoveFileTool`.
   - **Component 1 / `DialFileService`:** document the new `async move(source_url, destination_url, overwrite)` and `async copy(source_url, destination_url, overwrite)` methods, the body-URL `/v1/` prepend rule, and the choice of HTTP transport (raw client via the SDK's underlying `_http_client` to share auth headers — Round-9 blocking #4 names this).
   - **Error Handling table:** add the source-missing-404 row, the destination-exists-412 row, and generalize the existing "Absolute URL passed to `write_file` / `edit_file` / `delete_file`" row to include `move_file` (both sides) and `copy_file` (destination only). Round-9 blocking #5 enumerates these.
   - **Out of Scope:** remove the "Rename / move / copy" bullet (currently at line 415; confirmed in the body — it states "No primitive in the DIAL API", which is factually wrong now that the ops endpoints are documented).
   - **Migration / Non-breaking changes:** add a bullet for the two new tools (Round-9 blocking #6 specifies the wording). They are non-breaking because the feature is preview-gated and the existing manifest defaults expose them automatically only when `enabled_tools="all"`.
   - **Summary of Changes:** add rows for `_copy_file_tool.py` and `_move_file_tool.py` under *New files*, and for the two new methods on `DialFileService` under *Modified files*.
   - **Tests (Summary of Changes / Tests):** add the test list Round-9 suggestion #3 names — happy path, collision with `overwrite=False`, overwrite with `overwrite=True`, source-missing 404, absolute-URL rejection on the relative-only side(s), 403 forbidden — for each of the two new tools.

   **Suggestion:** Apply Round 9 as a single revision pass; after the body is updated, re-run the Round-9 *Changes since* checklist self-audit before requesting Round 11.

2. **[Resolved] [`DialFileService.move` / `copy` — name the SDK transport explicitly, not "the SDK's underlying HTTP client".]**
   Round-9 blocking #4 says "Use the SDK's underlying HTTP client (`dial_client._http_client` or equivalent) so auth headers are shared with every other DIAL call." The actual entry point is `dial_client._http_client.request(cast_to=..., options=FinalRequestOptions(method="POST", url="/v1/ops/resource/copy", json=...))` — same pattern `Metadata.get` uses (`aidial_client/resources/metadata.py:53-58, 83-88`). The leading underscore on `_http_client` flags this as private SDK API; the implementer should know they are reaching into a private surface and that an SDK upgrade could break it. Either (a) state explicitly that this is private SDK API and accept the maintenance commitment, or (b) ask upstream `aidial_client` to expose `files.move` / `files.copy` as a sanctioned API. Round-9's "raw HTTP" alternative (`httpx` direct) is worse — auth, retry, base-URL handling all re-implemented per call.

   **Suggestion:** In the `DialFileService` design note for the new methods, name the chosen transport (`dial_client._http_client.request(...)` with `FinalRequestOptions`) and acknowledge the private-API risk in one sentence. Optionally add an *Out of Scope* line: "Move/copy via the official SDK — pending upstream addition of `files.move` / `files.copy` on `aidial_client`."

3. **[Resolved] [Round-9 blocking #5 — error mapping for `move_file`/`copy_file` is under-specified for the destination-folder case.]**
   The Round-9 error rows cover source-missing (404) and destination-collision (412). They do not cover: destination *folder* missing (does DIAL Core auto-create the intermediate folders, as `files.upload` does, or does it 404?), source-is-a-folder (does the op recursively copy/move, or is it file-only?), and same-source-and-destination (a likely LLM mistake — does Core 400 or silently succeed?). These are concrete questions the implementer will hit in v1 and that the doc should answer (or explicitly defer).

   **Suggestion:** Either verify the three behaviors against a live DIAL Core during design or add an explicit *Out of Scope* line covering each case. At minimum, state which one of "destination folder must exist" / "destination folders auto-created" the design assumes — the existing `write_file` UC-3 ("DIAL creates the implicit `reports/` and `2026-Q1/` folders") suggests Core auto-creates on upload; whether `ops/resource/copy` does the same is unverified.

### Suggestions

1. **[Resolved] [Cache invalidation symmetry.]**
   Round-9 blocking #1 step 5 says `copy_file` invalidates the destination in the `DialFileService` cache; blocking #2 step 4 says `move_file` invalidates both source and destination. This is correct, but the doc should state explicitly in the `DialFileService` extension note that `move` / `copy` are responsible for the invalidation themselves (the way `_WriteFileTool` currently does after a successful overwrite) so the per-tool algorithms don't carry the burden. Mirrors how `upload_text` handles its own concurrency contract.

2. **[Resolved] [Consider `move_file` source as a folder under "Out of Scope".]**
   The DIAL Core `move`/`copy` endpoints may operate on folders (the Postman example uses a file URL but the endpoint name is `resource/`, not `file/`). If folder ops are out of scope for v1 (the natural choice — keeps the tool one-file-at-a-time and matches `delete_file`'s explicit non-recursive contract), add a bullet to *Out of Scope*: "Recursive folder move/copy. Out of scope — agents loop a `list_files` result if they need to move/copy a tree." This mirrors the existing "Recursive delete" bullet.

3. **[Resolved] [UC-12 and the `source` parameter description.]**
   Round-9 suggestion #1 proposes UC-12 (`copy_file(source="files/{user_bucket}/uploads/data.csv", destination="inputs/data.csv")`). This is the canonical "ingest a user upload" workflow and is worth promoting from a suggestion to a doc-level use case in the body — it answers the question "how does an agent get a user-uploaded file into its workspace?" which the current surface answers awkwardly (read + write + delete via raw bytes). Make it UC-12 explicitly in the *Use Cases* section, not just a sample in *Configuration / Usage Examples*.

### Nits

1. **[Round-9 self-status annotation in Round 7 block.]**
   Round 7's block ends with "**Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 9 review.**" — embedded inside the *Round 7* reviewer's block rather than in a follow-up author block. Same pattern Round 4 nit #1 flagged for Round 3 and Round 8 nit #2 flagged for Round 6. Harmless history noise; no action required, but future self-annotations should live in their own block.

2. **[Postman collection citation.]**
   Round-9 blocking #4 cites `.a_onlylocal/DIAL_Core_API.postman_collection.json` — this file is local-only (the `.a_onlylocal/` prefix suggests it is not in version control or shared with the team). When the body is updated, prefer a citation to the actual DIAL Core public docs / repo for the `ops/resource` endpoints, with the Postman file as a backup reference. Otherwise a future reader without the local file has no way to verify the URL shape.

### Changes since previous round

- Round-9 blocking #1 (`copy_file` tool) — **resolved.** Component 7.5 added with full algorithm, parameter table, design notes, and `DialFileService.copy` extension.
- Round-9 blocking #2 (`move_file` tool) — **resolved.** Component 7.6 added with full algorithm, parameter table, design notes, and `DialFileService.move` extension.
- Round-9 blocking #3 (register the two new tools in Components 9 / 10) — **resolved.** `internal_file_copy` and `internal_file_move` added to `DialFilesToolName` literal; `Copy file` and `Move file` stage titles added; new schemas in Configuration / Usage Examples; `_CopyFileTool` and `_MoveFileTool` added to Component 8 bind list.
- Round-9 blocking #4 (`DialFileService.move` / `copy` methods) — **resolved.** Methods documented with `_http_client.request` + `FinalRequestOptions` transport; private-SDK-API risk called out explicitly in design notes.
- Round-9 blocking #5 (Error Handling rows for the new tools) — **resolved.** Source-missing-404 row, destination-collision-412 row, and generalized absolute-URL row added.
- Round-9 blocking #6 (remove the "Rename / move / copy" Out-of-Scope bullet) — **resolved.** Bullet removed; replaced by "Recursive folder move/copy", "Cross-namespace moves", "Move/copy via official SDK", and "Destination folder auto-creation" bullets.
- Round-9 suggestions #1–#3 (UCs, sample outputs, tests) — **resolved.** UC-12, UC-13 added; `copy_file` and `move_file` sample outputs added; test bullets added for both tools plus `DialFileService.copy` / `DialFileService.move`.
- Round-10 blocking #2 (name the SDK transport explicitly) — **resolved.** `_http_client.request` + `FinalRequestOptions` named in both Component 7.5 and 7.6 design notes with explicit private-API risk acknowledgement.
- Round-10 blocking #3 (destination-folder, source-is-folder, same-src-dest edge cases) — **resolved.** Out-of-Scope bullet added ("Destination folder auto-creation for move/copy"); same-src-dest and source-is-folder deferred via the "Recursive folder move/copy" bullet.
- Round-10 suggestion #1 (cache invalidation note in DialFileService extension) — **resolved.** `move` and `copy` method docs note they invalidate the cache themselves.
- Round-10 suggestion #2 (folder move/copy Out of Scope) — **resolved.** "Recursive folder move/copy" bullet added to Out of Scope.
- Round-10 suggestion #3 (UC-12 promoted from suggestion) — **resolved.** UC-12 is now a first-class use case in the doc body.

---

## Review Notes — Round 11

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-11

### Verdict

`Ready for approval pending minor suggestions`. The Round-9/10 expansion (`copy_file`, `move_file`, the `DialFileService` extension, the *Path conventions* split, the Error Handling 403 row) is applied throughout the doc body and matches the codebase facts I spot-checked: `aidial_client._exception` exposes no typed `PermissionDeniedError` (only `DialException`, `InvalidRequestError`, `InvalidDialURLError`, `NotDialURLError`, `ParsingDataError`, `EtagMismatchError`, `ResourceNotFoundError`); `resources/files.py` exposes only `upload`/`delete`/`get_metadata`/download (no `copy`/`move`); `AsyncDialClient.my_appdata_home()` returns `Optional[PurePosixPath]` and the bucket response is internally cached on `_my_appdata`. The remaining issues are a small set of stale "six-tool" references that survived the eight-tool expansion — none of them changes the design but each will mislead a reader landing on that section in isolation. Fix those and the doc is approval-ready.

### Blocking issues

1. **[Component 9 — stage-titles list and tool-name list are out of sync.]** Component 9's *Highlights* reads:

   > Tool prefix renamed from `internal_text_file_` to `internal_file_`. Names: `internal_file_list`, `internal_file_read_lines`, `internal_file_search`, `internal_file_write`, `internal_file_edit`, `internal_file_delete`.
   > Stage titles: `List files`, `Read file lines`, `Search in file`, `Write file`, `Edit file`, `Delete file`, `Copy file`, `Move file`.

   The Names list has six entries; the Stage-titles list has eight. `internal_file_copy` and `internal_file_move` are missing from the Names line.
   **Suggestion:** Append `internal_file_copy`, `internal_file_move` to the Names line so the two parallel lists agree.

2. **[Summary of Changes / New tools exposed to the LLM — only six tools listed.]** The bullet block under *New tools exposed to the LLM* lists `internal_file_list` through `internal_file_delete` only. `internal_file_copy(source, destination, overwrite=False)` and `internal_file_move(source, destination, overwrite=False)` are missing. *Summary of Changes* is the scannable reference for the doc — a reader checking "what tools does this design expose?" will conclude six.
   **Suggestion:** Add the two missing tool entries with their signatures.

3. **[Summary of Changes / New files — `_tool_configs.py` row says "all six tools".]** The row for `dial_files_tooling/_tool_configs.py` reads "`OpenAiToolConfig` + `ToolDisplayConfig` for all six tools; renamed prefix." There are eight tools.
   **Suggestion:** Change to "for all eight tools".

4. **[Component 10 — `Features.dial_files` description still says "list / read / search / write / edit / delete".]** The wiring snippet:

   ```python
   dial_files: DialFilesConfig | None = PreviewField(  # type: ignore[assignment]
       default=None,
       description="Built-in DIAL files tools (list / read / search / write / edit / delete).",
   )
   ```

   This description is the operator-facing config-schema doc — copy/move are missing.
   **Suggestion:** Update to "Built-in DIAL files tools (list / read / search / write / edit / delete / copy / move)."

### Suggestions


### Nits


### Changes since previous round

- Round-10 blocking #1 (apply the full Round-9 plan to the doc body) — **resolved.** Components 7.5 (`copy_file`) and 7.6 (`move_file`) are present; `DialFilesToolName` lists eight tools; `DialFileService.copy` / `DialFileService.move` are documented with `_http_client.request` + `FinalRequestOptions`; Error Handling table has the new 403 row plus copy/move-specific rows; *Out of Scope* replaces "Rename / move / copy" with "Recursive folder move/copy", "Cross-namespace moves", "Move/copy via official SDK", and "Destination folder auto-creation"; UC-12 and UC-13 added; sample outputs added; *Summary of Changes* lists `_copy_file_tool.py`, `_move_file_tool.py`, and the new `DialFileService` methods. Residual staleness: a few "six tools" strings survive — see Round-11 blocking #1-#4.
- Round-10 blocking #2 (name the SDK transport explicitly + private-API risk) — **resolved.** Components 7.5 and 7.6 explicitly name `_http_client.request` + `FinalRequestOptions` and add a *Private SDK API note* describing the maintenance risk.
- Round-10 blocking #3 (destination-folder / source-is-folder / same-src-dst edge cases) — **resolved.** "Destination folder auto-creation for move/copy" added to Out of Scope; folder ops deferred via the new "Recursive folder move/copy" bullet.
- Round-10 suggestion #1 (cache-invalidation responsibility on `DialFileService`) — **resolved.** Component 7.6's closing line documents the source+destination cache invalidation on the service itself.
- Round-10 suggestion #2 (folder move/copy Out of Scope) — **resolved.** See blocking #3 above.
- Round-10 suggestion #3 (promote UC-12 to a first-class use case) — **resolved.** UC-12 is in the Use Cases section.
- Round-10 nits #1 (self-status annotations) and #2 (Postman citation) — acknowledged; nit #2 is effectively moot because the body has no `.a_onlylocal/` reference (only review-notes history cites it).

---

## Review Notes — Round 12

- **Reviewer:** Claude (design-review skill)
- **Date:** 2026-05-11

### Verdict

`Blocking issues must be addressed`. **Status: all blocking issues, suggestions, and nits addressed in this revision (2026-05-11). Awaiting Round 13 review.** The four Round-11 stale "six-tool" references are still in the doc body — the *Changes since* checklist for Round 11 is empty / unfilled, and grep confirms each of the four locations still reads as Round 11 flagged it. In addition, a separate inconsistency in Component 2 surfaces on a fresh read: Round-7 blocking #1 was claimed resolved ("Component 2 Algorithm step 4 reduced to two columns (size, path)") but the *Algorithm* still prescribes two-space-per-depth indentation, and the *Configuration / Usage Examples* listing samples still render with indentation and a trailing column legend that re-asserts the indent rule. None of the issues touch the design; they are pure documentation hygiene. Fix them and the doc is approval-ready.

### Blocking issues

1. **[Resolved] [Component 9 / Highlights — Names list still six entries.]** Line 415 reads:

   > Tool prefix renamed from `internal_text_file_` to `internal_file_`. Names: `internal_file_list`, `internal_file_read_lines`, `internal_file_search`, `internal_file_write`, `internal_file_edit`, `internal_file_delete`.

   The adjacent *Stage titles* line on line 416 already lists eight entries (adds `Copy file`, `Move file`). The Names line must match — append `internal_file_copy`, `internal_file_move`. This is exactly the same finding as Round-11 blocking #1; it has not been applied.

2. **[Resolved] [Component 10 / `Features.dial_files` description still says "list / read / search / write / edit / delete".]** Line 483:

   ```python
   description="Built-in DIAL files tools (list / read / search / write / edit / delete).",
   ```

   Operator-facing config-schema text — copy/move missing. Same finding as Round-11 blocking #4; not applied.

3. **[Resolved] [Summary of Changes / New files — `_tool_configs.py` row still says "all six tools".]** Line 839:

   > `dial_files_tooling/_tool_configs.py` | `OpenAiToolConfig` + `ToolDisplayConfig` for all six tools; renamed prefix.

   Change to "all eight tools". Same finding as Round-11 blocking #3; not applied.

4. **[Resolved] [Summary of Changes / New tools exposed to the LLM — only six entries.]** Lines 854-859 enumerate `internal_file_list` through `internal_file_delete` with their signatures; `internal_file_copy(source, destination, overwrite=False)` and `internal_file_move(source, destination, overwrite=False)` are missing. Same finding as Round-11 blocking #2; not applied. The *Changes since previous round* block under Round 11 (lines 1607-1616) does not list any entries for these four items, indicating the revision pass that addressed Round 11 silently skipped them.

5. **[Resolved] [Component 2 / Configuration examples — indentation contradicts Round-7 #1.]** Round-7 blocking #1 explicitly required: "Drop the two-space-per-depth indentation: depth is already encoded in the path (`reports/images/logo.png` is two levels deep). Removing it makes parsing trivial and saves tokens." The doc body still prescribes the indent in two places:
   - **Component 2 Algorithm step 4** (line 167): "Indentation is two spaces per depth level, applied to the path column" — followed by an indented sample (lines 168-174).
   - **Configuration / Usage Examples → `list_files` output format** (lines 655-660, 666-667, plus the legend on line 670 — "two spaces of indentation per depth level; folder paths end with `/`").

   The Round-7 *Changes since* note claims this was resolved, but a grep confirms the indentation language and sample formatting survived.
   **Suggestion:** Either (a) honor Round-7 #1: strip the indent from the algorithm prose, the samples, and the legend (so output is flush-left two columns: size then path); or (b) if the author has changed their mind and wants to keep the indent for readability, update Round-7's *Changes since* entry to reflect that decision and remove the contradiction. The current state is mid-flight between the two.

### Suggestions

1. **[Resolved] [Round-11 *Changes since* block — fill it in once the four blocking edits land.]** See "Changes since Round 12" below.

### Nits

1. **[Self-status annotations embedded in Claude reviewer blocks.]** Round 4 nit #1, Round 8 nit #2, and Round 10 nit #1 all flagged the pattern of the author appending a status line ("Status: all blocking issues … addressed. Awaiting Round N+1 review.") inside the *reviewer's* block rather than in a follow-up author block. The current revision continues the pattern (Round 7's block ends with such a line, Round 9's *Changes since Round 8* block opens with one, etc.). Harmless history noise; flagged once more for the record. No action required for approval.

### Changes since Round 12

- Round-11/12 blocking #1 (Names list in Highlights) — **resolved.** `internal_file_copy` and `internal_file_move` appended to the names line at line 415.
- Round-11/12 blocking #2 (`Features.dial_files` description) — **resolved.** Description updated to "list / read / search / write / edit / delete / copy / move".
- Round-11/12 blocking #3 (`_tool_configs.py` row "all six tools") — **resolved.** Changed to "all eight tools".
- Round-11/12 blocking #4 (New tools exposed list) — **resolved.** `internal_file_copy(source, destination, overwrite=False)` and `internal_file_move(source, destination, overwrite=False)` added to the list; `edit_file` and `delete_file` annotated as relative-only.
- Round-12 blocking #5 (Component 2 / Configuration examples indentation) — **resolved.** Indentation removed from Algorithm step 4 prose, Algorithm step 4 sample, Configuration samples, and legend. Both samples are now flush-left two-column (size, path); legend updated to "no indentation — depth is encoded in the path".
