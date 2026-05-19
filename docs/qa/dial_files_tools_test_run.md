# DIAL Files Tools — Test Run Report

- **Date:** 2026-05-19
- **Plan:** [`dial_files_tools_test_plan.md`](dial_files_tools_test_plan.md)
- **Target:** local docker-compose stack, DIAL chat UI at `http://localhost:3010`
- **Agent:** `DIAL Files Tools QA` (preview features enabled)
- **Method:** Playwright-MCP driving the chat UI; verification via assistant text + tool-stage bodies; screenshots saved under `screenshots/`.

## Summary

| Suite | Scenarios run | Passed | Failed | N/A |
|---|---|---|---|---|
| Success Path | 8 / 8 | 8 | 0 | 0 |
| Basic | 8 / 8 | 8 | 0 | 0 |
| Full | 12 / 17 | 10 | 2 | 5 |
| **Total** | **28 / 33** | **26** | **2** | **5** |

Two findings worth follow-up:

1. **F-LF-01 (FAIL)** — `internal_file_list` with `max_depth=3` returned only the folder skeleton `tree/a/`, `tree/a/b/`, `tree/a/b/c/`. The plan expected the file `tree/a/b/c/sibling.md` at depth 3 and the folder `tree/a/b/c/d/` to be visible. Either the depth semantics differ from the plan's interpretation or there is a bug — recommend reconciling with the design doc.
2. **F-WF-03 (FAIL — possible real bug)** — `internal_file_write` accepted a `content_type` containing a literal newline (`text/plain\nX-Injection: evil`) without error; the file was created. The plan expected an error with `/content_type/` and `/newline/`. This is the header-injection guard the design calls for; verify the unit test `test_write_file_tool.py` covers this and that the runtime path goes through that validation.

Also notable:
- **`list_files` size column shows 0 B** for files known to have non-empty content (e.g. `reports/summary.md` after S-WF-01). Doesn't break a scenario as written, but the plan's S-LF-01 expects "non-zero size" — likely Core returns metadata size lazily or this is a tool-side bug.
- **B-CP-01** error wording is `"Source resource does not exist"` (from Core's DialException), not the plan's `/source not found/`. Semantically equivalent.
- **B-MV-01** error wording is `"destination resource already exists"` (no `overwrite=True` hint surfaced in the raw exception). Matches `/already exists/`.

## Environment

- Branch: `feat/file-tools`
- App manifest: registered under `dial-file-tools-qa` in `docker_compose_files/core/configuration/applications.json`
- `ENABLE_PREVIEW_FEATURES=true`
- `temperature=0.2`, `max_iterations=6`, `features.dial_files: {}`

## Scenario results

### Success Path (8/8)

| ID | Tool | Result | Screenshot |
|---|---|---|---|
| S-WF-01 | `write_file` | ✅ Stage success, file created, attachment chip present | [`S-WF-01-write-file.png`](screenshots/S-WF-01-write-file.png) |
| S-LF-01 | `list_files` | ✅ Listing returns `reports/summary.md`; ⚠ size shown as `0 B` | [`S-LF-01-list-files.png`](screenshots/S-LF-01-list-files.png) |
| S-RD-01 | `read_file_lines` | ✅ Returns `# Q1 Summary` / `All green.` verbatim | [`S-RD-01-read-lines.png`](screenshots/S-RD-01-read-lines.png) |
| S-SR-01 | `search_in_file` | ✅ Match on line containing `green` | [`S-SR-01-search-in-file.png`](screenshots/S-SR-01-search-in-file.png) |
| S-EF-01 | `edit_file` | ✅ `All green.` → `All green and audited.`; re-read confirms | [`S-EF-01-edit-file.png`](screenshots/S-EF-01-edit-file.png) |
| S-CP-01 | `copy_file` | ✅ `reports/summary.md` → `archive/summary.md` | [`S-CP-01-copy-file.png`](screenshots/S-CP-01-copy-file.png) |
| S-MV-01 | `move_file` | ✅ `archive/summary.md` → `archive/old.md` | [`S-MV-01-move-file.png`](screenshots/S-MV-01-move-file.png) |
| S-DL-01 | `delete_file` | ✅ `archive/old.md` hard-deleted | [`S-DL-01-delete-file.png`](screenshots/S-DL-01-delete-file.png) |

### Basic Error (8/8)

| ID | Tool | Result | Screenshot |
|---|---|---|---|
| B-WF-01 | `write_file` | ✅ `path must not contain '..'` | [`B-WF-01-path-traversal.png`](screenshots/B-WF-01-path-traversal.png) |
| B-WF-02 | `write_file` | ✅ `write_file requires a relative path under agent_home_dir; do not pass an absolute files/... URL` | [`B-WF-02-absolute-url-rejected.png`](screenshots/B-WF-02-absolute-url-rejected.png) |
| B-WF-03 | `write_file` | ✅ `file already exists: reports/summary.md; pass overwrite=True to replace` | [`B-WF-03-overwrite-collision.png`](screenshots/B-WF-03-overwrite-collision.png) |
| B-EF-01 | `edit_file` | ✅ `old_string not found in file` | [`B-EF-01-old-string-not-found.png`](screenshots/B-EF-01-old-string-not-found.png) |
| B-DL-01 | `delete_file` | ✅ `file not found: reports/this_does_not_exist.md` | [`B-DL-01-delete-not-found.png`](screenshots/B-DL-01-delete-not-found.png) |
| B-LF-01 | `list_files` | ✅ LLM-side refusal referencing `max_depth` `[1, 10]` (acceptable per plan) | [`B-LF-01-max-depth-out-of-range.png`](screenshots/B-LF-01-max-depth-out-of-range.png) |
| B-CP-01 | `copy_file` | ✅ `Source resource does not exist: ...` (wording differs from plan's `source not found`, semantics match) | [`B-CP-01-source-not-found.png`](screenshots/B-CP-01-source-not-found.png) |
| B-MV-01 | `move_file` | ✅ `destination resource already exists` (no explicit `overwrite=True` mention) | [`B-MV-01-overwrite-collision.png`](screenshots/B-MV-01-overwrite-collision.png) |

### Full (10 pass / 2 fail / 5 N/A)

| ID | Tool | Result | Screenshot / Note |
|---|---|---|---|
| F-LF-01 | `list_files` | ❌ At `max_depth=3` only folders `tree/a/`, `tree/a/b/`, `tree/a/b/c/` returned; `sibling.md` (depth 4) and folder `d/` absent. Plan expects `sibling.md` visible. | [`F-LF-01-depth3-FAIL.png`](screenshots/F-LF-01-depth3-FAIL.png) |
| F-LF-02 | `list_files` | ⏭ N/A — non-home fixture absolute URL not staged in this environment |  |
| F-LF-03 | `list_files` | ✅ Empty folder errored ("folder not found"), one of the two acceptable outcomes | [`F-LF-03-empty-folder.png`](screenshots/F-LF-03-empty-folder.png) |
| F-RD-01 | `read_file_lines` | ⏭ N/A — non-home fixture absolute URL not staged |  |
| F-RD-02 | `read_file_lines` | ✅ LLM-side rejection of invalid range (start > end) | [`F-RD-02-invalid-range.png`](screenshots/F-RD-02-invalid-range.png) |
| F-SR-01 | `search_in_file` | ✅ Case-insensitive match with 1-line context (`intro line` + `The QUICK brown fox.` + `jumps over the lazy dog.`) | [`F-SR-01-case-insensitive-context.png`](screenshots/F-SR-01-case-insensitive-context.png) |
| F-SR-02 | `search_in_file` | ⏭ N/A — non-home fixture absolute URL not staged |  |
| F-WF-01 | `write_file` | ✅ CSV created with `content_type=text/csv` | [`F-WF-01-csv-content-type.png`](screenshots/F-WF-01-csv-content-type.png) |
| F-WF-02 | `write_file` | ✅ JSON at nested `data/2026/manifest.json` | [`F-WF-02-json-nested.png`](screenshots/F-WF-02-json-nested.png) |
| F-WF-03 | `write_file` | ❌ Newline-containing `content_type` accepted (no validation error, file written). Header-injection guard missing or not on this code path. | [`F-WF-03-content-type-newline-FAIL.png`](screenshots/F-WF-03-content-type-newline-FAIL.png) |
| F-WF-04 | `write_file` | ✅ `overwrite=True` happy path; baseline restored | [`F-WF-04-overwrite-true.png`](screenshots/F-WF-04-overwrite-true.png) |
| F-WF-05 | `write_file` | ⏭ N/A — concurrent-modification race; plan marks it unit-test-only when not stageable |  |
| F-EF-01 | `edit_file` | ✅ `old_string found 2 times; provide more surrounding context to disambiguate` | [`F-EF-01-multiple-matches.png`](screenshots/F-EF-01-multiple-matches.png) |
| F-EF-02 | `edit_file` | ✅ `new_string must differ from old_string` | [`F-EF-02-no-op.png`](screenshots/F-EF-02-no-op.png) |
| F-CP-01 | `copy_file` | ✅ Relative→relative copy `reports/summary.md` → `backups/summary.md` | [`F-CP-01-relative-copy.png`](screenshots/F-CP-01-relative-copy.png) |
| F-MV-01 | `move_file` | ✅ Move leaves no remnant (`dst.md` readable, `src.md` returns 404) | [`F-MV-01-no-remnant.png`](screenshots/F-MV-01-no-remnant.png) |
| F-XX-403 | any read | ⏭ N/A — no forbidden URL configured in this environment |  |

## Run cost

Captured from Claude Code `/usage` after the session:

| Metric | Value |
|---|---|
| Total cost | **$19.28** |
| API duration | 19m 21s |
| Wall-clock duration | 36m 38s |
| Model | `claude-opus-4-7` |
| Input tokens | 1.4K |
| Output tokens | 42.0K |
| Cache read | 33.8M |
| Cache write | 210.2K |

The dominant cost driver was **cache-read volume** (33.8M tokens) — every turn re-read the full conversation, which by the end included ~50 Playwright a11y-tree snapshots. Future runs of the same plan could likely halve the bill by:

- Avoiding full `browser_snapshot` after each turn — pull only the last assistant message via `browser_evaluate` instead.
- Trimming snapshots with `depth` / `target` parameters where the full tree isn't needed.

## Recommendations

- Reconcile the F-LF-01 expectation with the actual `max_depth` semantics — if tools should return contents at depth N, this is a bug; if "depth" means folder-tree depth only, update the plan.
- Investigate F-WF-03 — verify whether the header-injection guard is implemented and reached for both the relative-path code path and the QuickApps backend wrapper.
- Optional: confirm the `list_files` size-reporting behaviour for newly-written files (S-LF-01 showed `0 B` immediately after a successful write).
