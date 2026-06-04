# Design: DIAL Files Tools — Workspace-Wide Search

- **Status:** Draft
- **Owner:** Andrii Novikov
- **Dependencies:**
  - [DIAL Files Tools](./dial_files_tools.md) — extends the existing toolkit (`_DialFileTool`, `search_in_file`, `list_files`).
- **Tracking:** [#342](https://github.com/epam/ai-dial-quickapps-backend/issues/342)

## Problem Statement

The DIAL files toolkit lets an agent read, write, and organize files, but **search only works on a single file the agent already knows the path of** (`search_in_file(path, pattern, ...)`). Two everyday capabilities are missing:

- **Cross-file content search** (`grep -r`). To find which file contains a string, the agent must `list_files` the tree, then `search_in_file` each candidate one by one. For anything but a tiny folder this is impractical: the agent burns iterations walking and reading, and usually gives up.
- **Filename / glob discovery** (`find -name`). There is no way to locate files *by name or extension* (`**/*.csv`, `report-*.md`) without recursively listing every folder and eyeballing the result. `list_files` shows what's in a folder; it cannot answer "where are all the JSON files under my home".

Both gaps push work the tools should do back onto the LLM, where it is slow, lossy, and iteration-bounded. This design closes them with the smallest possible surface change: **generalize the existing `search` tool to whole folders, and add one filename tool (`find`)** — mirroring Claude Code's Grep/Glob split.

## Design Goals

- Let the agent search **file content across an entire folder subtree** in one call, not file-by-file.
- Let the agent locate files **by name/path glob** without downloading any bytes.
- Keep the existing single-file `search` behavior **byte-for-byte unchanged** (it is a registered offload read-back tool — see *Offload compatibility*).
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
**Behavior:** The tool scans files until `_MAX_FILES_SCANNED` (≈200) is reached, then stops and appends a truncation notice.\
**Outcome:** The result is bounded and the notice tells the LLM to narrow via `name_filter`, a deeper subfolder, or a smaller `max_depth`. No download storm.

### UC-8: Agent searches a folder without the trailing slash

**Trigger:** `search(path="reports", pattern="ERROR")` — no trailing `/`, but `reports` is a folder.\
**Behavior:** File mode is selected (no trailing `/`); the file download fails because the URL is a folder, surfaced by `_download_text` as the standard not-found error.\
**Outcome:** `InvalidToolCallParameterException("path", "file not found: reports")`. The tool description instructs the LLM to end folder paths with `/`, so it self-corrects by retrying with `reports/`.

---

## Proposed Design

Two tools change/appear. Both subclass the existing `_DialFileTool` (Component 1 of [DIAL Files Tools](./dial_files_tools.md)) and reuse `_resolve_appdata_url`, `_to_display_path`, `_download_text`, and `DialFileService.list_folder`.

### Component 1: `search` (generalized — content search over a file *or* folder)

**What:** Generalize the existing `search_in_file` so `path` may address either a single file (today's behavior) or a folder subtree (new: recursive substring content search). Folder vs file is selected by the **trailing-slash convention** already used by `list_files`.

**Owner:** `src/quickapp/dial_files_tooling/_search_in_file_tool.py` (`_SearchInFileTool`, generalized in place; short name stays `search`).

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `path` | string | yes | — | File or folder. Relative under the agent's home dir, or absolute `files/...`. **Folder mode** when the path ends with `/` **or** is a root-of-home reference (`""`, `.`, `./`, `/`); otherwise single-file mode. |
| `pattern` | string | yes | — | Substring to search for. *(unchanged — substring, not regex)* |
| `case_insensitive` | boolean | no | `false` | Compare lower-cased. *(unchanged)* |
| `context_lines` | integer | no | `0` | Lines of context around each match. *(unchanged; applies in `content` mode)* |
| `output_mode` | string | no | `"content"` | Folder mode only. One of `content`, `files_with_matches`, `count`. |
| `name_filter` | string | no | — | Folder mode only. Glob (`**`, `*`, `?`) matched against each candidate's relative path; non-matching files are excluded **before** download. |
| `max_depth` | integer | no | `10` | Folder mode only. Recursion depth bound, `[1, 10]`. |

**File-vs-folder selection:** `_is_folder_reference(path) := _is_root_reference(path) or path.endswith("/")`. A bare `path=""` therefore searches the whole home (UC-3); a trailing slash searches a subfolder; anything else is a single file.

**Semantics:**

- **File mode:** Resolve URL → `_download_text` → substring match → merged ±`context_lines` windows → `lineno:line` blocks separated by `--`. `output_mode`, `name_filter`, `max_depth` are ignored (a non-default value for them in file mode is silently irrelevant, not an error). Not-found is surfaced by `_download_text` as `InvalidToolCallParameterException("path", "file not found: {display}")`; the trailing-slash guidance for folder search lives in the tool **description**, not a bespoke runtime message.
- **Folder mode:**
  1. Resolve the folder URL via `_resolve_folder_url(path)` (handles root references → home dir, and ensures a trailing slash otherwise).
  2. `entries = list_folder(folder_url, max_depth=max_depth)`; keep only file entries. A `ResourceNotFoundError` on a **root reference** → empty result (`"No matches found."`); on a **non-root** folder → `InvalidToolCallParameterException("path", "folder not found: {display}")`.
  3. If `name_filter` is set, drop entries whose **relative display path** does not match the glob (via the shared `_glob_to_regex` helper — Component 3). This happens before any download.
  4. Iterate the remaining candidates. For each, download via `_download_text`; **skip files that are not UTF-8-decodable** (binary). Substring-match the decoded text exactly as file mode does.
  5. Stop after `_MAX_FILES_SCANNED` files have been downloaded; record that truncation occurred.
  6. Emit output per `output_mode` (below). All output paths are relative display paths via `_to_display_path`.

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
- `count`: `relative/path: <n>` per file, where `<n>` is the number of matching lines.
- No matches → `"No matches found."` (all modes).
- If truncated, append a final line: ``"-- search truncated after N files; narrow with name_filter, a subfolder, or a smaller max_depth --"``.

**Cost bounds (folder mode):**

- **Text-only:** non-UTF-8 files are skipped after the (cached) download attempt; substring search cannot use binary anyway. *(A pre-download extension allowlist is deferred — see Out of Scope.)*
- **File cap:** `_MAX_FILES_SCANNED` (≈200) downloads per call, then truncate-and-notify. This is the hard upper bound on egress.
- **Depth + pre-filter:** `max_depth` bounds the `list_folder` walk; `name_filter` shrinks the candidate set before any download.

**Change vs current codebase:** `_SearchInFileTool._run_in_stage_async` gains a folder branch; the existing file branch is factored into a helper (`_search_single_file(text) -> matches`) reused by both. Folder resolution reuses the shared `_resolve_folder_url` / `_is_root_reference` helpers and the `_MAX_DEPTH` bound (Component 3). New constant `_MAX_FILES_SCANNED`.

---

### Component 2: `find` (filename / glob discovery — metadata only)

**What:** A new tool that locates files by name or path glob, walking the folder tree via metadata only. The filename analogue of `search`; mirrors Claude Code's Glob.

**Owner:** `src/quickapp/dial_files_tooling/_find_files_tool.py` (`_FindFilesTool`); short name `find`; full name `internal_file_find`.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `pattern` | string | yes | — | Glob (`**`, `*`, `?`) matched against each entry's relative path, e.g. `**/*.py`, `report-*.csv`, `data/**/*.json`. |
| `path` | string | no | `""` (home root) | Folder to search under. Relative under the agent's home dir, or absolute `files/...`. |
| `max_depth` | integer | no | `10` | Recursion depth bound, `[1, 10]`. |

**Semantics:**

1. Validate `max_depth` in `[1, 10]` → else `InvalidToolCallParameterException("max_depth", "must be in [1, 10]")`.
2. Resolve the folder URL via `_resolve_folder_url(path)` (root references → home dir; ensures a trailing `/` otherwise).
3. `entries = list_folder(folder_url, max_depth=max_depth)` — metadata only, **no file downloads**. A `ResourceNotFoundError` on a root reference → empty result; on a non-root folder → `InvalidToolCallParameterException("path", "folder not found: {display}")`.
4. For each entry, compute its relative display path (`_to_display_path`) and match it against `pattern` via `_glob_to_regex`. Match files and folders both; folder display paths keep their trailing `/`.
5. Render the matches with the shared listing renderer (`NAME` + `SIZE`). No matches → `"No files found."`.

**Glob semantics** (shared helper, Component 3):
- `*` matches any run of characters **except** `/` (within one path segment).
- `?` matches a single character except `/`.
- `**` matches across `/` (any number of segments, including zero), so `**/*.csv` matches `a.csv` and `x/y/a.csv`.
- Matching is against the relative path (case-sensitive, consistent with DIAL paths).

**Change vs current codebase:** new file/class, new tool name constant, new config, new DI binding (Components 4–5).

---

### Component 3: Shared helpers

`find` and folder-mode `search` reuse three pieces of shared infrastructure so behavior stays identical across the file tools and nothing is duplicated.

**Folder resolution (`_resolve_folder_url`, `_is_root_reference`, `_MAX_DEPTH`).** These currently live on `_ListFilesTool` and are needed verbatim by `find` and folder-mode `search`: `_is_root_reference` recognizes `""`/`.`/`./`/`/`; `_resolve_folder_url` maps a root reference to the home dir and otherwise appends a trailing `/` before `_resolve_appdata_url`; `_MAX_DEPTH = 10` bounds recursion. This design **promotes them to the `_DialFileTool` base class** so all three tools share one implementation.

**Listing renderer (`_render_listing`, `_format_size`).** `find` renders results exactly like `list_files` (`NAME` + `SIZE`). These tool-private helpers in `_list_files_tool.py` move to a shared module (`_listing.py`) imported by `_list_files_tool` and `_find_files_tool`.

**Glob (`_glob_to_regex`).** A single function translating a glob (`**`/`*`/`?`, with the segment semantics above) into a compiled `re.Pattern`, used by both `find` (its `pattern`) and `search` (its `name_filter`). `fnmatch.translate` does not distinguish `**` from `*`, so we translate manually: escape the literal text, then emit `[^/]*` for `*`, `[^/]` for `?`, and `.*` for `**` (collapsing an optional adjacent `/` so `**/x` matches `x`). Anchored full-match (`re.fullmatch`). Invalid patterns surface as `InvalidToolCallParameterException("pattern", ...)`. Owner: `src/quickapp/dial_files_tooling/_glob.py` (new module). One implementation guarantees `find` and `search`'s `name_filter` accept exactly the same syntax — the LLM learns one glob dialect for both.

---

### Component 4: Tool configs and names

**What:** A config for `find` and a generalized config/description for `search`.

- **`search` config** (`SEARCH_IN_FILE_TOOL_CONFIG`, name `internal_file_search`): description updated to state that `path` may be a file or a `folder/`, plus the new `output_mode`, `name_filter`, `max_depth` parameters (all optional, folder-mode only). Existing params unchanged.
- **`find` config** (`FIND_FILES_TOOL_CONFIG`, name `internal_file_find`): new `OpenAiToolConfig` + `ToolDisplayConfig`. Stage title `Find files`. Added to `ALL_FILE_TOOL_CONFIGS`.
- **Name constant:** add `INTERNAL_FILE_FIND_TOOL_NAME = f"{INTERNAL_FILE_TOOL_NAME_PREFIX}find"` to `src/quickapp/common/tool_names.py`.

**Owner:** `src/quickapp/dial_files_tooling/_tool_configs.py`, `src/quickapp/common/tool_names.py`.

---

### Component 5: DI wiring and per-app config

**What:** Register `_FindFilesTool` alongside the existing file tools and add `find` to the configurable tool set.

- `dial_files_tooling_module.py`: bind `_FindFilesTool` in `request_scope`; add a `find_builder: AssistedBuilder[_FindFilesTool]` and the `(find_builder, FIND_FILES_TOOL_CONFIG)` entry to the `_provide_dial_files_tools` multiprovider. `_is_enabled` already keys off the short name, so `find` is gated by `enabled_tools` automatically.
- `config/dial_files.py`: add `"internal_file_find"` to the `DialFilesToolName` literal so apps can include/exclude it.

**Owner:** `src/quickapp/dial_files_tooling/dial_files_tooling_module.py`, `src/quickapp/config/dial_files.py`.

---

### Component 6: Offload compatibility

**What:** Confirm the offload read-back contract is preserved.

- `_REQUIRED_READ_BACK_TOOLS = frozenset({"read_lines", "search"})` stays unchanged. The offload notice points the LLM at `search` to read back offloaded content; that read-back is always a **single-file** call (the offloaded result was written to one file), which is exactly the unchanged file-mode path. Generalizing `search` to also accept folders is a strict superset — it does not weaken the read-back guarantee.
- `find` is metadata-only and is **not** a read-back tool; it is not added to `_REQUIRED_READ_BACK_TOOLS`.

---

## Out of Scope

- **Regex content search.** `search` stays substring + `case_insensitive`, consistent with today. Regex is deferred (would change the existing file-mode contract and needs a backtracking/timeout guard).
- **Total-byte cap on folder search.** The file cap + text-only skip bound worst-case egress; a cumulative-bytes ceiling is deferred until profiling shows a few huge text files are a problem.
- **Pre-download extension allowlist.** Binary files are skipped *after* a (cached) download attempt fails to decode. A name/extension allowlist that avoids the download entirely is a future optimization; `name_filter` already gives the agent manual control.
- **Auto-detect file vs folder.** We use the trailing-slash / root-reference convention (consistent with `list_files`) rather than probing whether a path is a folder. The tool description guides the LLM to end folder paths with `/`. A "probe then fall back" auto-detect is deferred — it adds a round-trip and magic for little gain.
- **Pagination / result caps on `find`.** `find` returns all matches (metadata only, cheap). A result-count cap or pagination is deferred until folder sizes warrant it, mirroring `list_files`.
- **Sorting by mtime / size.** `find` returns tree-walk order. Ranking is deferred.

---

## Migration

### Breaking changes

None. `search` (`internal_file_search`) keeps its existing required params and single-file behavior byte-for-byte; the new params are optional and only affect folder mode (selected by a trailing `/` or a root-of-home reference — inputs that previously addressed a non-existent file and failed to download, so no previously-valid call changes meaning).

### Non-breaking changes

- `find` (`internal_file_find`) is a new tool, off unless `dial_files` is enabled and `find` is in `enabled_tools` (or `enabled_tools == "all"`).
- `DialFilesToolName` gains `"internal_file_find"`. Existing manifests that list tools explicitly are unaffected; they simply don't include `find` until updated.
- Run `make dump_app_schema` after the `DialFilesConfig` literal change.

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `dial_files_tooling/_find_files_tool.py` | `_FindFilesTool` — glob filename discovery via `list_folder` (metadata only). |
| `dial_files_tooling/_glob.py` | `_glob_to_regex` — shared `**`/`*`/`?` translator for `find` and `search`'s `name_filter`. |
| `dial_files_tooling/_listing.py` | Extracted `_render_listing` / `_format_size` shared by `list_files` and `find`. |

### Modified files

| File | Change |
|------|--------|
| `dial_files_tooling/_base_file_tool.py` | Promote `_resolve_folder_url`, `_is_root_reference`, and `_MAX_DEPTH` from `_ListFilesTool` to the base class for reuse by `list_files`, `find`, and folder-mode `search`. |
| `dial_files_tooling/_search_in_file_tool.py` | Add folder-mode branch (recursive content search) with `output_mode`, `name_filter`, `max_depth`; factor the existing file logic into a reused helper; reuse `_resolve_folder_url`; add `_MAX_FILES_SCANNED`; skip non-UTF-8 files. File mode unchanged. |
| `dial_files_tooling/_list_files_tool.py` | Use the promoted base-class folder helpers and the extracted listing module instead of local definitions. |
| `dial_files_tooling/_tool_configs.py` | Update `SEARCH_IN_FILE_TOOL_CONFIG` description/params; add `FIND_FILES_TOOL_CONFIG`; add it to `ALL_FILE_TOOL_CONFIGS`. |
| `dial_files_tooling/dial_files_tooling_module.py` | Bind `_FindFilesTool`; add it to the `_provide_dial_files_tools` multiprovider. |
| `common/tool_names.py` | Add `INTERNAL_FILE_FIND_TOOL_NAME`. |
| `config/dial_files.py` | Add `"internal_file_find"` to `DialFilesToolName`. |

### Tools exposed to the LLM

- `internal_file_search(path, pattern, context_lines=0, case_insensitive=False, output_mode="content", name_filter=None, max_depth=10)` — `path` is a file **or** `folder/`.
- `internal_file_find(pattern, path="", max_depth=10)` *(new)*.

### Tests

- Unit: `src/tests/unit_tests/dial_files_tooling/`:
  - `search` file mode: regression — output identical to current `search_in_file` (single file, context windows, `--` separators, `case_insensitive`).
  - `search` folder mode: `path=""` searches the whole home (root reference → folder mode); matches across multiple text files grouped by path (`content`); `files_with_matches` returns paths only; `count` returns per-file tallies; non-UTF-8 files skipped; `name_filter` excludes non-matching candidates before download; `max_depth` bounds the walk; file-cap truncation appends the notice; folder path without trailing `/` → `_download_text` "file not found" (file mode); non-root folder not-found → "folder not found: {display}"; root reference with nothing written → "No matches found."
  - `find`: `**/*.ext` matches at any depth incl. root; `*` does not cross `/`; `?` single char; default `path=""` searches home root; subfolder `path`; `max_depth` cap and out-of-range error; root reference with nothing written → empty result; empty match set → "No files found."; output uses the shared listing renderer.
  - `_glob_to_regex`: `*`/`?`/`**` segment semantics; literal escaping; invalid pattern → `InvalidToolCallParameterException("pattern", ...)`.
  - Offload: `_missing_read_back_tools` / `ResolvedOffloadConfig` unaffected — `search` still satisfies the read-back requirement; `find` is not required.
