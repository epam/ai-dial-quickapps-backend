# Design: DIAL Files Tools — Workspace-Wide Search

- **Status:** Implemented
- **Approved:** 2026-06-03 · **Re-approved:** 2026-06-08 (post-implementation revisions below reviewed against the merged code)
- **Owner:** Andrii Novikov
- **Dependencies:**
  - [DIAL Files Tools](./dial_files_tools.md) — extends the existing toolkit (`_DialFileTool`, `search_in_file`, `list_files`).
- **Tracking:** [#342](https://github.com/epam/ai-dial-quickapps-backend/issues/342)
- **Post-approval revisions** (2026-06-08, from [PR #352](https://github.com/epam/ai-dial-quickapps-backend/pull/352) review):
  - Glob translation delegates to the stdlib `glob.translate` (Python 3.13) instead of a hand-rolled translator.
  - The `count` output mode was dropped; folder `search` returns only `content` or `files_with_matches`.
  - The folder-scan file cap moved from a hardcoded `_MAX_FILES_SCANNED` constant to a configurable `DialFilesConfig.max_files_scanned` (default 50).
  - The DI-free helpers — path math (`is_root_reference`, `relative_to`) and the listing renderer (`render_listing`, `format_size`) — live in a new `_utils.py` rather than on the tool base class (the listing renderer moved out of `_list_files_tool.py`).
  - The shared folder-resolution + not-found handling is consolidated into one base helper, `_list_folder_entries`, with a shared `_resolve_max_depth`; `list`, `find`, and folder-mode `search` all use them.

## Problem Statement

The DIAL files toolkit lets an agent read, write, and organize files, but **search only works on a single file the agent already knows the path of** (`search_in_file(path, pattern, ...)`). Two everyday capabilities are missing:

- **Cross-file content search** (`grep -r`). To find which file contains a string, the agent must `list_files` the tree, then `search_in_file` each candidate one by one. For anything but a tiny folder this is impractical: the agent burns iterations walking and reading, and usually gives up.
- **Filename / glob discovery** (`find -name`). There is no way to locate files *by name or extension* (`**/*.csv`, `report-*.md`) without recursively listing every folder and eyeballing the result. `list_files` shows what's in a folder; it cannot answer "where are all the JSON files under my home".

Both gaps push work the tools should do back onto the LLM, where it is slow, lossy, and iteration-bounded. This design closes them with the smallest possible surface change: **generalize the existing `search` tool to whole folders, and add one filename tool (`find`)** — mirroring Claude Code's Grep/Glob split.

## Design Goals

- Let the agent search **file content across an entire folder subtree** in one call, not file-by-file.
- Let the agent locate files **by name/path glob** without downloading any bytes.
- Keep the existing single-file `search` behavior **byte-for-byte unchanged** so existing apps and tool-call contracts are unaffected; folder mode is purely additive.
- Make folder content search **cost-bounded and predictable**: it must not be able to trigger an unbounded download storm on a large or deep workspace.
- Reuse the existing `_DialFileTool` base, path conventions, `list_folder` recursion, and listing renderer — no new infrastructure.
- Stay preview-gated and per-app-configurable, exactly like the other file tools.

---

## Use Cases

### UC-1: Agent greps for a string across its workspace

**Trigger:** `search(path="reports/", pattern="ERROR", context_lines=2)` — note the trailing `/` marks folder mode.\
**Behavior:** The tool lists the subtree under `reports/` (depth-bounded), downloads each UTF-8-decodable file (skipping binaries), substring-matches each, and stops after the file cap. Matches are grouped per file.\
**Outcome:** The LLM sees, in one result, every matching file with its `lineno:line` snippets and ±2 lines of context — without ever listing or reading files itself.

### UC-2: Agent searches a single file (unchanged)

**Trigger:** `search(path="reports/summary.md", pattern="ERROR", context_lines=2, case_insensitive=True)` — no trailing `/`.\
**Behavior / Outcome:** Identical to today's `search_in_file`: download one file, substring match, merged context windows, `lineno:line` output. No behavior change.

### UC-3: Agent scans broadly, then drills in (output modes)

**Trigger:** `search(path="", pattern="api_key", output_mode="files_with_matches")` then `search(path="config/db.env", pattern="api_key", context_lines=3)`.\
**Behavior:** The first call returns only the **paths** of files containing the string (cheap, scannable). The agent then re-runs `search` in `content` mode on the one file it cares about.\
**Outcome:** The agent triages a broad hit set without paying for full content, then pulls context for the single relevant file.

### UC-4: Agent narrows a folder search with a name pre-filter

**Trigger:** `search(path="data/", pattern="2026-Q1", name_filter="**/*.csv")`.\
**Behavior:** Before downloading anything, the candidate set is filtered to files whose relative path matches the `**/*.csv` glob; only those are downloaded and scanned.\
**Outcome:** A `.json`/`.png`-heavy folder costs only as many downloads as there are CSVs, and the file cap is far less likely to truncate.

### UC-5: Agent locates files by extension (filename discovery)

**Trigger:** `find(pattern="**/*.csv")` (defaults to the agent's home root).\
**Behavior:** The tool walks the tree via `list_folder` (metadata only — no downloads) and returns every entry whose relative path matches `**/*.csv`.\
**Outcome:** The agent gets a flat list of matching paths (with sizes) it can feed directly into `read_file_lines` / `search` / `edit_file`. Zero bytes transferred.

### UC-6: Agent finds files by name prefix in a subfolder

**Trigger:** `find(path="reports/", pattern="report-*.md", max_depth=2)`.\
**Behavior:** Glob is matched against the relative path under the search root; recursion is bounded to depth 2.\
**Outcome:** Only matching files within two levels of `reports/` are listed.

### UC-7: Folder content search hits the file cap

**Trigger:** `search(path="huge-dump/", pattern="x")` over a subtree with thousands of text files.\
**Behavior:** The tool scans files until the configured file cap (`DialFilesConfig.max_files_scanned`, default 50) is reached, then stops and appends a truncation notice.\
**Outcome:** The result is bounded and the notice tells the LLM to narrow via `name_filter`, a deeper subfolder, or a smaller `max_depth`. No download storm.

### UC-8: Agent searches a folder without the trailing slash

**Trigger:** `search(path="reports", pattern="ERROR")` — no trailing `/`, but `reports` is a folder.\
**Behavior:** File mode is selected (no trailing `/`); the file download fails because the URL is a folder, surfaced by `_download_text` as the standard not-found error.\
**Outcome:** `InvalidToolCallParameterException("path", "file not found: reports")`. The tool description instructs the LLM to end folder paths with `/`, so it self-corrects by retrying with `reports/`.

---

## Proposed Design

Two tools change/appear. Both subclass the existing `_DialFileTool` (Component 1 of [DIAL Files Tools](./dial_files_tools.md)) and reuse `_resolve_appdata_url`, `_to_display_path`, `_download_text`, and `DialFileService.list_folder`.

### Component 1: `search` (generalized — content search over a file *or* folder)

**What:** Generalize the existing `search_in_file` so `path` may address either a single file (today's behavior) or a folder subtree (new: recursive substring content search). Folder vs file is selected by the **trailing-slash / root-reference convention** already used by `list_files`.

**Owner:** `src/quickapp/dial_files_tooling/_search_in_file_tool.py` (`_SearchInFileTool`, generalized in place; short name stays `search`).

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | File or folder. Relative under the agent's home dir, or absolute `files/...`. **Folder mode** when the path ends with `/` **or** is a root-of-home reference (`""`, `.`, `./`, `/`); otherwise single-file mode. |
| `pattern` | string | yes | — | Substring to search for. *(unchanged — substring, not regex)* |
| `case_insensitive` | boolean | no | `false` | Compare lower-cased. *(unchanged)* |
| `context_lines` | integer | no | `0` | Lines of context around each match. *(unchanged; applies in `content` mode)* |
| `output_mode` | string | no | `"content"` | Folder mode only. Either `content` or `files_with_matches`. |
| `name_filter` | string | no | — | Folder mode only. Glob (`**`, `*`, `?`) matched against each candidate's relative path; non-matching files are excluded **before** download. |
| `max_depth` | integer | no | `10` | Folder mode only. Recursion depth: `1` = immediate children only; `2` = children and their children; etc. Must be in `[1, 10]` (same semantics as `list_files`). |

**File-vs-folder selection:** `_is_folder_reference(path) := is_root_reference(path) or path.endswith("/")`. A bare `path=""` therefore searches the whole home (UC-3); a trailing slash searches a subfolder; anything else is a single file.

**Semantics:**

- **File mode:** Resolve URL → `_download_text` → substring match → merged ±`context_lines` windows → `lineno:line` blocks separated by `--`, wrapped in a fenced code block (see "Output rendering" below). The folder-only params (`output_mode`, `name_filter`, `max_depth`) are **silently ignored** in file mode (their schema descriptions already mark them "folder mode only"). Not-found is surfaced by `_download_text` as `InvalidToolCallParameterException("path", "file not found: {display}")`; the trailing-slash guidance for folder search lives in the tool **description**, not a bespoke runtime message.
- **Folder mode:**
  1. Resolve and list the subtree via the shared base helper `entries = _list_folder_entries(path, max_depth)` (it calls `_resolve_folder_url` — root references → home dir, trailing slash otherwise — then `list_folder`). `max_depth` is parsed and range-checked by the shared `_resolve_max_depth(value, default=10)`.
  2. `_list_folder_entries` applies the shared not-found policy: a missing **root reference** → empty list (→ `"No matches found."`); a missing **non-root** folder → `InvalidToolCallParameterException("path", "folder not found: {display}")`; a non-folder target → `"not a folder: {display}"`; permission errors → `"access denied"`. Keep only file entries.
  3. If `name_filter` is set, drop entries whose path **relative to the search root** (`relative_to(entry.url, folder_url)`) does not match the glob (compiled once via the shared `_glob_to_regex` helper — Component 3). This happens before any download.
  4. Cap the candidate set to the first `DialFilesConfig.max_files_scanned` entries (`candidates[:cap]`); if the unbounded set was larger, record that truncation occurred. Download and scan the capped set **concurrently** (`asyncio.gather`) via a folder-scan-only helper `_read_text_for_scan(url) -> str | None` (new, on `_DialFileTool`) that calls `DialFileService.download_file`, decodes the bytes as UTF-8, and returns the text — or returns **`None` to skip** the file if the decode fails (`UnicodeDecodeError`, binary) or the file exceeds the per-file size limit (`download_file` itself raises `ValueError`). Both exceptions are caught in the same `try` (`except (ValueError, UnicodeDecodeError): return None`). Genuine errors (not-found, access-denied) propagate. This deliberately bypasses `_download_text` — whose single-file contract (wrapping those same failures into `InvalidToolCallParameterException`) is intentionally left **unchanged** for file mode — so folder mode can skip cleanly instead of aborting. Substring-match the decoded text of the surviving (non-`None`) files exactly as file mode does, preserving candidate order in the output.
  5. Emit output per `output_mode` (below). Paths are rendered with `_to_display_path` — relative for entries under home, and absolute `files/...` for entries outside it (only possible when an absolute folder `path` was searched), matching `list_files`.

**Folder-mode output:**

- `content` (default): ripgrep-style. For each matching file, a path header line, then the file's `lineno:line` match blocks (same merged-context formatting as file mode), e.g.

  ```
  reports/a.md
  12:  ERROR: disk full
  13:  retrying...
  --
  41:  ERROR: timeout

  logs/run.txt
  3:ERROR boot
  ```
- `files_with_matches`: one matching relative path per line, nothing else.
- No matches → `"No matches found."` (both modes).
- If truncated, append a final line (in **both** output modes): ``"-- search truncated after <cap> files scanned; narrow with name_filter, a subfolder, or a smaller max_depth --"`` — `<cap>` is `DialFilesConfig.max_files_scanned`, which equals the number of download attempts (including skipped binary/oversized files) when truncation fires.

**Output rendering:** Tool results are rendered as markdown, which collapses single newlines into spaces — left raw, a multi-line file listing or `lineno:line` block would render as one run-on line. So the match-bearing output (file mode, and both folder modes) is wrapped in a fenced code block via the shared `code_block` helper in `_utils.py`, the same convention `render_listing` already uses for `list`/`find`. The bare `"No matches found."` is left unfenced (matching `render_listing`'s unfenced `"(empty folder)"`), and the truncation notice is appended **after** the fenced block as a normal line.

**Cost bounds (folder mode):**

- **Text-only:** `_read_text_for_scan` skips files that fail UTF-8 decode (`UnicodeDecodeError`, binary) or exceed the per-file size limit (`download_file` raises `ValueError`); substring search cannot use them anyway. Each skip still **counts toward `max_files_scanned`** (a download was attempted). *(A pre-download extension allowlist is deferred — see Out of Scope.)*
- **File cap:** `DialFilesConfig.max_files_scanned` (default 50) download attempts per call, then truncate-and-notify. This is the hard upper bound on egress, and is per-app configurable.
- **Depth + pre-filter:** `max_depth` bounds the `list_folder` walk; `name_filter` shrinks the candidate set before any download.

**Change vs current codebase:** `_SearchInFileTool._run_in_stage_async` gains a folder branch; the existing file branch is factored into helpers (`_matching_line_indices` + `_format_matches`) reused by both. Folder listing goes through the shared base helper `_list_folder_entries`; depth is parsed by `_resolve_max_depth`; path math uses `relative_to` / `is_root_reference` from `_utils` (Component 3). New base-class helper `_read_text_for_scan`; the file cap is read from `DialFilesConfig.max_files_scanned` (Component 5).

---

### Component 2: `find` (filename / glob discovery — metadata only)

**What:** A new tool that locates files by name or path glob, walking the folder tree via metadata only. The filename analogue of `search`; mirrors Claude Code's Glob.

**Owner:** `src/quickapp/dial_files_tooling/_find_files_tool.py` (`_FindFilesTool`); short name `find`; wire name `internal_file_find`, built inline as `f"{TOOL_NAME_PREFIX}find"` in `_tool_configs.py` like every other file tool (file-tool names are not stored in `common/tool_names.py`).

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `pattern` | string | yes | — | Glob (`**`, `*`, `?`) matched against each entry's relative path, e.g. `**/*.py`, `report-*.csv`, `data/**/*.json`. |
| `path` | string | no | `""` (home root) | Folder to search under. Relative under the agent's home dir, or absolute `files/...`. |
| `max_depth` | integer | no | `10` | Recursion depth: `1` = immediate children only; `2` = children and their children; etc. Must be in `[1, 10]` (same semantics as `list_files`). |

**Semantics:**

1. Parse and range-check `max_depth` via the shared `_resolve_max_depth(value, default=10)` → `InvalidToolCallParameterException("max_depth", "must be in [1, 10]")` if outside `[1, 10]`.
2. List the subtree via the shared base helper `entries = _list_folder_entries(path, max_depth)` — metadata only, **no file downloads**. It resolves the folder URL (`_resolve_folder_url`) and applies the shared not-found policy: root reference → empty result; non-root folder → `"folder not found: {display}"`; non-folder target → `"not a folder: {display}"`; permission errors → `"access denied"`.
3. For each entry, match its path **relative to the search root** (`relative_to(entry.url, folder_url)`) against `pattern` via `_glob_to_regex`. Match files and folders both; folder paths keep their trailing `/`. (Matching is relative to the search root so e.g. `find(path="reports/", pattern="report-*.md")` works — see UC-6.)
4. Render the matches with the shared listing renderer (`NAME` + `SIZE`), labelling each row with `_to_display_path` (relative for entries under home, absolute `files/...` otherwise); matched folders render with size `-` and a trailing `/`, like `list_files`. No matches → `"No files found."`.

**Glob semantics** (shared helper, Component 3):
- `*` matches any run of characters **except** `/` (within one path segment).
- `?` matches a single character except `/`.
- `**` matches across `/` (any number of segments, including zero), so `**/*.csv` matches `a.csv` and `x/y/a.csv`.
- Matching is against the relative path (case-sensitive, consistent with DIAL paths).

**Change vs current codebase:** new file/class, new config (name built inline in `_tool_configs.py`), new DI binding (Components 4–5).

---

### Component 3: Shared helpers

`list`, `find`, and folder-mode `search` reuse three pieces of shared infrastructure so behavior stays identical across the file tools and nothing is duplicated.

**DI-free helpers (`_utils.py`).** A single module (`src/quickapp/dial_files_tooling/_utils.py`) for the helpers that need no `self`/DI: path math — `is_root_reference(path)` (recognizes `""`/`.`/`./`/`/`) and `relative_to(url, folder_url)` (path of `url` relative to the search root, used for glob matching) — and the listing renderer `render_listing` / `format_size`, which renders `find`'s results exactly like `list_files` (`NAME` + `SIZE`). The renderer moved here out of `_list_files_tool.py`; `_list_files_tool` and `_find_files_tool` both import it. The module also holds `code_block(text)`, which wraps text in a fenced block so newlines/alignment survive markdown rendering; `render_listing` and folder/file `search` both use it.

**Folder resolution & listing (base class).** `_resolve_folder_url` (maps a root reference to the home dir, otherwise appends a trailing `/` before `_resolve_appdata_url`), `_list_folder_entries(path, max_depth)` (resolve + `list_folder` + the shared not-found policy: missing root → `[]`, missing non-root → `"folder not found"`, non-folder → `"not a folder"`, 403 → `"access denied"`), and `_resolve_max_depth(value, default)` (parse + range-check `[1, _MAX_DEPTH]`) all live on `_DialFileTool` (they need `self`/DI). `_MAX_DEPTH = 10` is a module constant there. `list`, `find`, and folder-mode `search` all go through these, so their folder/not-found behavior is identical by construction.

**Glob (`_glob_to_regex`).** A single function compiling a glob into a `re.Pattern`, used by both `find` (its `pattern`) and `search` (its `name_filter`). It delegates to the stdlib `glob.translate` (Python 3.13) with `recursive=True` (so `**` spans path segments), `include_hidden=True` (dotfiles match like any name), and `seps="/"` (DIAL paths always use `/`):

- `**/x` matches `x`, `a/x`, `a/b/x` but **not** `foox`; `data/**/*.json` matches `data/a.json` and `data/x/y/a.json`.
- `*` → any run within a single segment (does not cross `/`); `?` → a single non-`/` character.
- `**` is recursive only as a whole path segment (`/**/`); a within-segment `foo**` behaves like `foo*` and does **not** cross `/` (this is the one behavioral difference from the originally-approved hand-rolled translator).

Used with `fullmatch` (anchored, case-sensitive, consistent with DIAL paths). Empty/invalid patterns surface as `InvalidToolCallParameterException("pattern", ...)`. Owner: `src/quickapp/dial_files_tooling/_glob.py` (new module). One implementation guarantees `find` and `search`'s `name_filter` accept exactly the same syntax — the LLM learns one glob dialect for both.

---

### Component 4: Tool configs and names

**What:** A config for `find` and a generalized config/description for `search`.

- **`search` config** (`SEARCH_IN_FILE_TOOL_CONFIG`, name `f"{TOOL_NAME_PREFIX}search"`): description updated to state that `path` may be a file or a `folder/`, plus the new `output_mode`, `name_filter`, `max_depth` parameters (all optional, folder-mode only). The function description gains explicit trailing-slash guidance: *"Search a single file or a whole folder tree. For a folder, end the path with `/` to search recursively (e.g. `reports/`); omit the trailing slash to search one file (e.g. `reports/summary.md`)."* The three folder-only params are each marked *"folder mode only"* in their schema descriptions so the constraint is visible to the model. Existing params unchanged.
- **`find` config** (`FIND_FILES_TOOL_CONFIG`, name `f"{TOOL_NAME_PREFIX}find"`): new `OpenAiToolConfig` + `ToolDisplayConfig`. Stage title `Find files`. Added to `ALL_FILE_TOOL_CONFIGS`. The name is built inline like the other file tools — no constant in `common/tool_names.py` (which holds no file-tool names).

**Owner:** `src/quickapp/dial_files_tooling/_tool_configs.py`.

---

### Component 5: DI wiring and per-app config

**What:** Register `_FindFilesTool` alongside the existing file tools and add `find` to the configurable tool set.

- `dial_files_tooling_module.py`: bind `_FindFilesTool` in `request_scope`; add a `find_builder: AssistedBuilder[_FindFilesTool]` and the `(find_builder, FIND_FILES_TOOL_CONFIG)` entry to the `_provide_dial_files_tools` multiprovider. `_is_enabled` strips `TOOL_NAME_PREFIX` (`removeprefix`) and checks the short name against `enabled_tools`, so `find` is gated automatically once it is in the literal.
- `config/dial_files.py`: add the short name `"find"` to the `DialFilesToolName` literal (which holds short names: `"list"`, `"read_lines"`, `"search"`, …) so apps can include/exclude it; and add a `max_files_scanned: int = Field(default=50, ge=1)` field that folder-mode `search` reads for its per-call file cap.

**Owner:** `src/quickapp/dial_files_tooling/dial_files_tooling_module.py`, `src/quickapp/config/dial_files.py`.

---

## Out of Scope

- **Regex content search.** `search` stays substring + `case_insensitive`, consistent with today. Regex is deferred (would change the existing file-mode contract and needs a backtracking/timeout guard).
- **Total-byte cap on folder search.** The file cap + text-only skip bound worst-case egress; a cumulative-bytes ceiling is deferred until profiling shows a few huge text files are a problem.
- **Pre-download extension allowlist.** Binary files are skipped *after* a (cached) download attempt fails to decode. A name/extension allowlist that avoids the download entirely is a future optimization; `name_filter` already gives the agent manual control.
- **Auto-detect file vs folder.** We use the trailing-slash / root-reference convention (consistent with `list_files`) rather than probing whether a path is a folder. The tool description guides the LLM to end folder paths with `/`. A "probe then fall back" auto-detect is deferred — it adds a round-trip and magic for little gain.
- **Pagination / result caps on `find`.** `find` returns all matches (metadata only, cheap). The `list_folder` walk is worst-case `O(W^D)` metadata calls (`W` subfolders per level, `D` depth); `max_depth ∈ [1, 10]` is the primary bound. A result-count cap or pagination is deferred until folder sizes warrant it, mirroring `list_files`; if profiling shows metadata cost dominates, a stricter default depth can be added later.
- **Sorting by mtime / size.** `find` returns tree-walk order. Ranking is deferred.

---

## Migration

### Breaking changes

None. `search` (`internal_file_search`) keeps its existing required params and single-file behavior byte-for-byte; the new params are optional and only affect folder mode (selected by a trailing `/` or a root-of-home reference — inputs that previously addressed a non-existent file and failed to download, so no previously-valid call changes meaning).

### Non-breaking changes

- `find` (`internal_file_find`) is a new tool, off unless `dial_files` is enabled and `find` is in `enabled_tools` (or `enabled_tools == "all"`).
- `DialFilesToolName` gains the short name `"find"`. Existing manifests that list tools explicitly are unaffected; they simply don't include `find` until updated.
- `DialFilesConfig` gains an optional `max_files_scanned` field (default 50); existing manifests are unaffected, since the default preserves prior behavior.
- Run `make dump_app_schema` after the `DialFilesConfig` changes (the `"find"` literal and the `max_files_scanned` field).

## Summary of Changes

All items below are prescriptive — the implementation lands after approval. (Per the [design lifecycle](./README.md), *Approved* means reviewed and ready to implement, not yet implemented; *Implemented* is set once the code merges.)

### New files

| File | Purpose |
|------|---------|
| `dial_files_tooling/_find_files_tool.py` | `_FindFilesTool` — glob filename discovery via `list_folder` (metadata only). |
| `dial_files_tooling/_glob.py` | `_glob_to_regex` — shared `**`/`*`/`?` matcher (wraps stdlib `glob.translate`) for `find` and `search`'s `name_filter`. |
| `dial_files_tooling/_utils.py` | DI-free helpers shared across the file tools: path math (`is_root_reference` / `relative_to`), the listing renderer (`render_listing` / `format_size`, moved out of `_list_files_tool.py`), and `code_block` (fenced-block wrapper so output survives markdown rendering). |

### Modified files

| File | Change |
|------|--------|
| `dial_files_tooling/_base_file_tool.py` | Add `_resolve_folder_url` + `_list_folder_entries` (resolve + list + shared not-found policy) + `_resolve_max_depth` and the `_MAX_DEPTH` constant for reuse by `list_files`, `find`, and folder-mode `search`; add `_read_text_for_scan` (folder-scan download returning `None` on binary/oversize). `_download_text` is unchanged. |
| `dial_files_tooling/_search_in_file_tool.py` | Add folder-mode branch (recursive content search) with `output_mode` (`content` / `files_with_matches`), `name_filter`, `max_depth`; factor the existing file logic into reused helpers (`_matching_line_indices`, `_format_matches`); use `_list_folder_entries`; read the file cap from `DialFilesConfig.max_files_scanned`; download/scan folder candidates concurrently (`asyncio.gather`); skip non-UTF-8/oversized files; ignore folder-only params in file mode; wrap match output in a fenced `code_block`. File-mode match semantics unchanged. |
| `dial_files_tooling/_list_files_tool.py` | Use the base-class `_list_folder_entries` / `_resolve_max_depth` and the `render_listing` helper in `_utils.py` instead of local definitions. |
| `dial_files_tooling/_tool_configs.py` | Update `SEARCH_IN_FILE_TOOL_CONFIG` description/params; add `FIND_FILES_TOOL_CONFIG`; add it to `ALL_FILE_TOOL_CONFIGS`. |
| `dial_files_tooling/dial_files_tooling_module.py` | Bind `_FindFilesTool`; add it (with a `find_builder`) to the `_provide_dial_files_tools` multiprovider. |
| `config/dial_files.py` | Add the short name `"find"` to `DialFilesToolName`; add the `max_files_scanned` field. |

### Tools exposed to the LLM

- `internal_file_search(path, pattern, context_lines=0, case_insensitive=False, output_mode="content", name_filter=None, max_depth=10)` — `path` is a file **or** `folder/`.
- `internal_file_find(pattern, path="", max_depth=10)` *(new)*.

### Tests

- Unit: `src/tests/unit_tests/dial_files_tooling/`:
  - `search` file mode: regression — output identical to current `search_in_file` (single file, context windows, `--` separators, `case_insensitive`).
  - `search` folder mode: `path=""` searches the whole home (root reference → folder mode); matches across multiple text files grouped by path (`content`); `files_with_matches` returns paths only; `count` is rejected (mode dropped); non-UTF-8 files skipped; `name_filter` excludes non-matching candidates before download; `max_depth` bounds the walk; file-cap truncation appends the notice (cap driven by `max_files_scanned`); folder path without trailing `/` → `_download_text` "file not found" (file mode); non-root folder not-found → "folder not found: {display}"; non-folder target → "not a folder: {display}"; root reference with nothing written → "No matches found."
  - `find`: `**/*.ext` matches at any depth incl. root; `*` does not cross `/`; `?` single char; default `path=""` searches home root; subfolder `path`; `max_depth` cap and out-of-range error; root reference with nothing written → "No files found."; empty match set → "No files found."; matched folders render with size `-`; output uses the shared listing renderer.
  - `search` file mode also: a folder-only `output_mode` / `name_filter` / `max_depth` is ignored (no error) in file mode; a binary file and an oversized file in a folder are skipped (not aborting the search).
  - `search` output rendering: match output (file mode and both folder modes) is wrapped in a fenced `code_block`; `"No matches found."` is left unfenced.
  - `_glob_to_regex`: `**/x` matches `x`, `a/x`, `a/b/x` but **not** `foox`; `foo**` behaves like `foo*` (does **not** cross `/`); `*` does not cross `/`; `?` is one non-`/` char; literal escaping (`file.txt` matches only `file.txt`); case-sensitive; empty/invalid pattern → `InvalidToolCallParameterException("pattern", ...)`.
  - `DialFilesConfig`: `max_files_scanned` defaults to 50 and rejects values `< 1`.
