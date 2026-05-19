# Test Plan: DIAL Files Tools (Manual QA via Playwright MCP)

- **Status:** Draft
- **Owner:** Andrii Novikov
- **Date:** 2026-05-19
- **Targets:** the eight `internal_file_*` tools described in [`docs/designs/dial_files_tools.md`](../designs/dial_files_tools.md) (`list`, `read_lines`, `search`, `write`, `edit`, `delete`, `copy`, `move`)
- **Audience:** a Playwright-MCP-equipped agent driving the DIAL chat UI. Each scenario is written so the agent can act and verify without out-of-band API calls.

## 1. Overview

This plan exercises the eight DIAL files tools end-to-end through the DIAL chat UI. The Playwright agent:

1. Loads the chat UI for a QuickApp configured with the manifest in §3.
2. Sends a natural-language prompt to trigger a tool.
3. Observes the streamed assistant response (stages, attachments, text) using semantic checks defined in §4 — **no hard-coded CSS selectors**.
4. Verifies side effects by sending a follow-up prompt that uses another file tool to inspect state.

Three suites, additive in scope:

| Suite | Contents | Purpose |
|---|---|---|
| **Success Path** (§6) | One happy path per tool, ordered so each scenario seeds the next. | Smoke test of all eight tools in a single sequential run. |
| **Basic** (§7) | Success Path + the basic errors the LLM is most likely to hit. | Default acceptance gate before merging. |
| **Full** (§8) | Basic + depth/edge/content-type/race/cross-namespace cases. | Pre-release coverage. |

Each higher tier *includes* the lower tiers; the agent runs them in order. A failed scenario aborts the suite by default — see §5.

## 2. Prerequisites

The Playwright agent is responsible for satisfying these before suite execution. Environment-specific details (URLs, credentials) are filled in at runtime.

### 2.1 Common

- **Preview features enabled.** `ENABLE_PREVIEW_FEATURES=true` on the QuickApps backend; without this, the `dial_files` module contributes nothing and every scenario will fail with "tool not found".
- **Model deployment.** A working chat-completion model deployment is reachable from QuickApps and configured in the test app manifest (§3). The plan does not prescribe which model — pick whatever the target environment runs day-to-day.
- **Test app deployed.** A QuickApp using the manifest in §3 exists and is reachable through the DIAL chat UI.
- **Playwright MCP tools available.** `browser_navigate`, `browser_type`, `browser_click`, `browser_snapshot`, `browser_wait_for`, `browser_network_requests` are sufficient to run the plan.
- **Fresh appdata.** The test app's appdata namespace starts empty (no leftover files from prior runs). If a prior run left state, the agent runs `F-CLEANUP-00` (§8.0) before the suite.
- **Pre-staged non-home fixture.** One absolute-URL fixture file is needed for non-home read/search/list scenarios (F-LF-02, F-RD-01, F-SR-02). The runner pre-stages a small UTF-8 text file at an absolute `files/{fixture_bucket}/qa/notes.txt` URL that the test app's agent has read access to. The exact URL is recorded in the runner's environment block and substituted into the prompts below.

### 2.2 Local target (docker-compose stack)

- DIAL Core, file storage, and any auxiliary services are up via `docker_compose_files/` from this repo.
- QuickApps backend running locally via `make run_chat`.
- DIAL chat UI reachable at the local URL the runner records.

### 2.3 Remote target (staging / dev DIAL)

- The agent is already authenticated against the hosted DIAL UI (cookies/SSO completed before suite start).
- Network access from the agent's host to the deployed QuickApps backend is verified.

## 3. Test app manifest

The QuickApp deployed for this plan uses the configuration below. It follows the same shape as the existing `files-app` entry in [`docker_compose_files/core/configuration/applications.json`](../../docker_compose_files/core/configuration/applications.json) — snake_case fields, an `application_properties` wrapper, an explicit `application_type_schema_id` binding the app to the QuickApps 2.0 schema, and a structured `deployment` / `system_prompt`. Anything in `<…>` is filled in by the runner.

For the **local target** (§2.2) the entry is added to the `applications` map of that JSON file before `make run_chat`. For the **remote target** (§2.3) it is registered through whatever app-deployment surface the target environment uses, preserving the field structure below.

```jsonc
"dial-file-tools-qa": {
  "name": "DIAL-Files-Tools-QA",
  "display_name": "DIAL Files Tools QA",
  "display_version": "0.0.1",
  "description": "QA app for the eight DIAL files tools (preview).",
  "max_retry_attempts": 1,
  "application_properties": {
    "orchestrator": {
      "deployment": {
        "name": "<model-deployment-id>",
        "parameters": {
          "temperature": 0.2
        }
      },
      "system_prompt": {
        "type": "custom",
        "variables": {},
        "content": "You are a file-tools QA assistant. Use ONLY the internal_file_* tools (list, read_lines, search, write, edit, delete, copy, move) to satisfy the user's requests. When the user gives a relative path, treat it as relative to the agent's home directory. When the user gives a path starting with 'files/', pass it through as an absolute DIAL URL. After each tool call, briefly state in plain text what the tool returned (success line, error, or listing) so the user can verify. Do not invent paths the user did not provide."
      },
      "max_iterations": 6
    },
    "contexts": [],
    "tool_sets": [],
    "features": {
      "dial_files": {}
    }
  },
  "application_type_schema_id": "https://mydial.epam.com/custom_application_schemas/quickapps2",
  "routes": {}
}
```

Notes:

- **`application_type_schema_id`** binds the app to the QuickApps 2.0 schema — without it, `application_properties` is not parsed as a QuickApps config and the file tools never come up.
- **`features.dial_files: {}`** enables all eight tools (`enabled_tools` defaults to `"all"`, `agent_home_dir` defaults to `files/{appdata}/`).
- The **system prompt** deliberately nudges the LLM toward the file tools and toward echoing tool output, so the chat-text assertions in §4 are reliable.
- **`temperature: 0.2`** keeps tool-selection deterministic across runs; lower than the `files-app` value because this is QA, not exploration.
- **`max_iterations: 6`** because some scenarios chain a tool call with a verification call in the same turn.
- **`contexts: []` and `tool_sets: []`** are explicit empty arrays — the file tools come from the `features.dial_files` module wiring, not from a tool set.

If a scenario calls for a different config (e.g., `agent_home_dir` repointed under `features.dial_files`), the scenario states the override explicitly and the runner redeploys before running it.

## 4. Verification primitives (UI-agnostic)

Each scenario asserts in these semantic terms. The Playwright agent maps them to whatever the current DIAL chat UI renders.

| Primitive | Meaning |
|---|---|
| **Stage `<Title>` appears** | A tool-stage block with the given title (e.g. `Write file`, `List files`) is rendered under the current assistant message. |
| **Stage `<Title>` completes successfully** | The stage has no error indicator and its body shows the tool's success content. |
| **Stage `<Title>` errors with /pattern/** | The stage is rendered in its error variant and its body matches the regex (case-insensitive substring is fine). |
| **Attachment chip `<basename>`** | A file attachment chip whose visible label ends with the given basename appears under the assistant message. |
| **Assistant text contains "X"** | The streamed assistant text (excluding stage bodies) contains substring X (case-insensitive). |
| **Assistant text mentions path `P`** | The assistant text contains a token equal to `P` (e.g. `reports/summary.md`). Tolerates surrounding punctuation/backticks. |
| **No stage labelled `<Title>` appears** | Used for negative assertions (e.g. a path-traversal-rejected `Write file` should never reach the stage-success branch). |

The agent should treat these as black-box checks. **Do not** assert on specific CSS classes, ARIA roles, or DOM structure that may change with DIAL UI upgrades.

## 5. Conventions

- **Scenario ID:** `<Suite>-<Tool>-<NN>` where suite ∈ {`S`, `B`, `F`}, tool ∈ {`LF`, `RD`, `SR`, `WF`, `EF`, `DL`, `CP`, `MV`}, and `NN` is a per-tool counter. `CHAIN` is used for cross-tool flows.
- **Suite ordering:** Success Path → Basic → Full. Each suite runs to completion before the next begins.
- **State:** the Success Path Suite leaves a specific directory layout under the agent's home dir; Basic and Full scenarios state their own preconditions and (where needed) reset state explicitly.
- **Prompt style:** natural language, no `internal_file_*` tool names in the prompt. If the LLM picks the wrong tool, the scenario fails — that is intentional, the system prompt in §3 should make the right choice obvious.
- **One prompt per turn.** The agent does not bundle multiple operations into one prompt unless the scenario explicitly chains them.
- **Wait for completion.** Before reading assistant text or stage state, the agent waits for the streamed response to terminate (no further stages or tokens for ≥1s).
- **Failure handling.** On a failed scenario, the agent records the chat transcript, the rendered stage tree (snapshot), and aborts the current suite. Subsequent suites are skipped.

## 6. Success Path Suite

The suite builds up state sequentially. Each scenario assumes the prior ones succeeded.

### S-WF-01 — write_file: create a new file at a nested path

**Exercises:** `internal_file_write`

**Preconditions:** the agent's home dir contains no `reports/` subtree.

**Prompt:**
> Create a markdown file at `reports/summary.md` whose contents are exactly:
>
> ```
> # Q1 Summary
> All green.
> ```

**Expected observations:**
- Stage `Write file` appears and completes successfully.
- Assistant text contains `reports/summary.md` and indicates the file was created.
- Attachment chip `summary.md` is present.

**Self-verification:** none here — verified by S-LF-01.

**Cleanup:** none.

---

### S-LF-01 — list_files: depth=1 listing of the home dir sees the new file

**Exercises:** `internal_file_list`

**Preconditions:** S-WF-01 succeeded.

**Prompt:**
> List the files under `reports/` (immediate children only).

**Expected observations:**
- Stage `List files` appears and completes successfully.
- Assistant text mentions path `reports/summary.md` with a non-zero size.

**Self-verification:** the listing itself is the verification.

**Cleanup:** none.

---

### S-RD-01 — read_file_lines: read the file back

**Exercises:** `internal_file_read_lines`

**Preconditions:** S-WF-01 succeeded.

**Prompt:**
> Read lines 0 through 5 of `reports/summary.md` and show them to me verbatim.

**Expected observations:**
- Stage `Read file lines` appears and completes successfully.
- Assistant text contains `# Q1 Summary` and `All green.`.

**Cleanup:** none.

---

### S-SR-01 — search_in_file: substring match returns the line

**Exercises:** `internal_file_search`

**Preconditions:** S-WF-01 succeeded.

**Prompt:**
> Search `reports/summary.md` for the substring `green` and show me any matching lines.

**Expected observations:**
- Stage `Search in file` appears and completes successfully.
- Assistant text contains `All green.`.

**Cleanup:** none.

---

### S-EF-01 — edit_file: surgical patch via unique substring

**Exercises:** `internal_file_edit`

**Preconditions:** S-WF-01 succeeded (file contains `All green.`).

**Prompt:**
> In `reports/summary.md`, replace the text `All green.` with `All green and audited.`.

**Expected observations:**
- Stage `Edit file` appears and completes successfully.
- Assistant text indicates the edit applied.

**Self-verification (next prompt):**
> Read lines 0 through 5 of `reports/summary.md`.

Expected: assistant text now contains `All green and audited.` and **does not** contain the bare phrase `All green.` (i.e. the unedited string).

**Cleanup:** none.

---

### S-CP-01 — copy_file: home → home

**Exercises:** `internal_file_copy`

**Preconditions:** S-WF-01 succeeded.

**Prompt:**
> Copy `reports/summary.md` to `archive/summary.md`.

**Expected observations:**
- Stage `Copy file` appears and completes successfully.
- Assistant text mentions path `archive/summary.md`.

**Self-verification (next prompt):**
> List the files under `archive/` (immediate children).

Expected: listing includes `archive/summary.md`.

**Cleanup:** none — `archive/summary.md` is consumed by S-MV-01.

---

### S-MV-01 — move_file: rename within home

**Exercises:** `internal_file_move`

**Preconditions:** S-CP-01 succeeded (`archive/summary.md` exists).

**Prompt:**
> Rename `archive/summary.md` to `archive/old.md`.

**Expected observations:**
- Stage `Move file` appears and completes successfully.
- Assistant text mentions path `archive/old.md`.

**Self-verification (next prompt):**
> List the files under `archive/`.

Expected: listing includes `archive/old.md` and **does not** include `archive/summary.md`.

**Cleanup:** none — `archive/old.md` is consumed by S-DL-01.

---

### S-DL-01 — delete_file: hard delete

**Exercises:** `internal_file_delete`

**Preconditions:** S-MV-01 succeeded.

**Prompt:**
> Delete `archive/old.md`.

**Expected observations:**
- Stage `Delete file` appears and completes successfully.
- Assistant text confirms the file was deleted.

**Self-verification (next prompt):**
> List the files under `archive/`.

Expected: either an empty listing or `archive/old.md` absent from it.

**Cleanup:** at this point the residual state is `reports/summary.md` (containing `All green and audited.`). Basic and Full suites expect this baseline.

## 7. Basic Error Suite

Run after Success Path. State baseline: `reports/summary.md` exists (from S-EF-01 result).

### B-WF-01 — write_file rejects path traversal

**Exercises:** `internal_file_write` (relative-path validator).

**Prompt:**
> Create a file at `../escape.md` with the content `should fail`.

**Expected observations:**
- Either: Stage `Write file` errors with `/contain.*\.\./` (or `not.*allowed.*\.\./`), **or** the assistant refuses without ever invoking the tool because the system prompt forwarded the rejection.
- The acceptable failure shape: any stage rendering of the tool **must** be in the error variant; **no successful** `Write file` stage may appear.

**Self-verification (next prompt):**
> List the files under the home directory (depth 1).

Expected: no entry named `escape.md` at any level.

**Cleanup:** none.

---

### B-WF-02 — write_file rejects absolute `files/...` URL

**Exercises:** `internal_file_write` (mutating-tool absolute-URL guard).

**Prompt:**
> Create a file at `files/some-other-bucket/foo.md` with the content `should fail`.

**Expected observations:**
- Stage `Write file` errors with `/relative path/` (or `/absolute files\/\.\.\. URL/`).
- No successful `Write file` stage appears.

**Cleanup:** none.

---

### B-WF-03 — write_file overwrite=False collides on existing file

**Exercises:** `internal_file_write` (collision branch).

**Preconditions:** `reports/summary.md` exists from Success Path baseline.

**Prompt:**
> Create a new file at `reports/summary.md` with the content `replacement`. Do **not** overwrite if it already exists.

**Expected observations:**
- Stage `Write file` errors with `/already exists/` and references `overwrite=True` (or `pass overwrite`).
- No attachment chip for `summary.md` is added by this turn (the pre-existing one from Success Path may still be visible in earlier turns — that's fine).

**Self-verification (next prompt):**
> Read lines 0 through 5 of `reports/summary.md`.

Expected: contents still include `All green and audited.` (i.e. the Success Path edit). The collision must not have replaced bytes.

**Cleanup:** none.

---

### B-EF-01 — edit_file: `old_string` not found

**Exercises:** `internal_file_edit`.

**Prompt:**
> In `reports/summary.md`, replace the text `THIS_SUBSTRING_IS_NOT_PRESENT` with `whatever`.

**Expected observations:**
- Stage `Edit file` errors with `/not found/` (or `/no match/`).

**Self-verification (next prompt):**
> Read lines 0 through 5 of `reports/summary.md`.

Expected: file content unchanged from Success Path baseline.

**Cleanup:** none.

---

### B-DL-01 — delete_file: target not found

**Exercises:** `internal_file_delete` (404 branch).

**Prompt:**
> Delete the file `reports/this_does_not_exist.md`.

**Expected observations:**
- Stage `Delete file` errors with `/not found/`.

**Cleanup:** none.

---

### B-LF-01 — list_files: `max_depth` out of range

**Exercises:** `internal_file_list` (parameter validator).

**Prompt:**
> List the files under `reports/` recursively to a depth of 11 levels.

**Expected observations:**
- Stage `List files` errors with `/max_depth/` and `/1.*10/` (or similar; the message references the [1, 10] range).

**Cleanup:** none.

---

### B-CP-01 — copy_file: source not found

**Exercises:** `internal_file_copy` (404 on source).

**Prompt:**
> Copy `reports/this_does_not_exist.md` to `archive/copy_of_missing.md`.

**Expected observations:**
- Stage `Copy file` errors with `/source not found/` (or `/source.*not found/`).

**Self-verification (next prompt):**
> List the files under `archive/`.

Expected: no entry named `copy_of_missing.md`.

**Cleanup:** none.

---

### B-MV-01 — move_file: destination collision without overwrite

**Exercises:** `internal_file_move`.

**Preconditions:** need a source and a destination that already exists. The agent first creates them:

**Setup prompts (sequential):**
1. > Create a file at `mv_test/src.md` with content `source`.
2. > Create a file at `mv_test/dest.md` with content `destination`.

(Both should succeed; verify with two `Write file` stages completing successfully.)

**Main prompt:**
> Move `mv_test/src.md` to `mv_test/dest.md` without overwriting.

**Expected observations:**
- Stage `Move file` errors with `/already exists/` and references `overwrite=True`.

**Self-verification (next prompt):**
> Read lines 0 through 1 of `mv_test/dest.md`.

Expected: content is still `destination` (the move did not happen).

**Cleanup:** delete both `mv_test/src.md` and `mv_test/dest.md` so the directory is empty for the Full suite. The agent issues two `delete_file` prompts; both must succeed.

## 8. Full Suite

Run after Basic. State baseline: `reports/summary.md` (containing `All green and audited.`) exists; everything else clean.

### 8.0 F-CLEANUP-00 — Pre-suite reset (optional)

If the suite is being re-run without re-deploying the app, the agent first deletes any leftover residue by:

1. Listing `home/` with `max_depth=10`.
2. Issuing a `delete_file` for every file in the listing **except** `reports/summary.md`.
3. Confirming a second listing matches the expected baseline.

This is not a test — failures here abort the run before assertions begin.

---

### F-LF-01 — list_files: depth=3 recursion, depth-bound folders listed-not-expanded

**Exercises:** `internal_file_list` (depth bounding).

**Preconditions:** need a tree at least 4 levels deep. Setup sub-prompts:

1. > Create a file at `tree/a/b/c/d/leaf.md` with content `leaf`.
2. > Create a file at `tree/a/b/c/sibling.md` with content `sibling`.

**Main prompt:**
> List the files under `tree/` recursively to a depth of 3.

**Expected observations:**
- Stage `List files` completes successfully.
- Assistant text mentions paths `tree/a/`, `tree/a/b/`, `tree/a/b/c/`, `tree/a/b/c/sibling.md`.
- The folder `tree/a/b/c/d/` may be listed by name, but `tree/a/b/c/d/leaf.md` **must not** appear (it is past the depth bound).

**Cleanup:** delete `tree/a/b/c/sibling.md` and `tree/a/b/c/d/leaf.md`.

---

### F-LF-02 — list_files: non-home folder via absolute URL

**Exercises:** `internal_file_list` (absolute-URL pass-through on read tool).

**Preconditions:** the pre-staged non-home fixture (§2.1) is reachable. Its folder URL is `files/{fixture_bucket}/qa/`.

**Prompt:**
> List the files under `files/{fixture_bucket}/qa/` (depth 1). Substitute `{fixture_bucket}` with the actual bucket.

**Expected observations:**
- Stage `List files` completes successfully.
- Assistant text emits the listing with **absolute** paths (entries starting with `files/{fixture_bucket}/qa/...`), not relative ones.

**Cleanup:** none.

---

### F-LF-03 — list_files: empty folder

**Exercises:** `internal_file_list` (empty-listing path).

**Preconditions:** create an empty folder via a write-then-delete trick — write a file, then delete it; the folder remains in listings if Core retains it. **Note:** DIAL Core may or may not retain empty folders. The agent first probes:

1. Setup: > Create a file at `empty_probe/sentinel.md` with content `x`.
2. Setup: > Delete `empty_probe/sentinel.md`.
3. Main: > List the files under `empty_probe/` (depth 1).

**Expected observations:**
- Stage `List files` either:
  - Completes successfully with an empty listing (Core retains the folder), **or**
  - Errors with `/folder not found/` (Core garbage-collects empty folders).
- Both outcomes are acceptable; the scenario records which path the deployment exhibits in the run log.

**Cleanup:** none.

---

### F-RD-01 — read_file_lines: non-home file via absolute URL

**Exercises:** `internal_file_read_lines` (UC-6b).

**Preconditions:** non-home fixture `files/{fixture_bucket}/qa/notes.txt` exists with known UTF-8 content; the agent's runner records the first line (call it `<FIXTURE_FIRST_LINE>`).

**Prompt:**
> Read lines 0 through 3 of `files/{fixture_bucket}/qa/notes.txt`.

**Expected observations:**
- Stage `Read file lines` completes successfully.
- Assistant text contains `<FIXTURE_FIRST_LINE>`.

**Cleanup:** none.

---

### F-RD-02 — read_file_lines: invalid range (end < start)

**Exercises:** `internal_file_read_lines` (parameter validator).

**Prompt:**
> Read lines 10 through 5 of `reports/summary.md`.

**Expected observations:**
- Stage `Read file lines` errors with `/start.*end/` or `/range/` or `/invalid/`.

**Cleanup:** none.

---

### F-SR-01 — search_in_file: case-insensitive + context lines

**Exercises:** `internal_file_search` (full parameter surface).

**Preconditions:** need a file with mixed-case content over multiple lines. Setup:

> Create a file at `search_test/mixed.md` with the content:
>
> ```
> intro line
> The QUICK brown fox.
> jumps over the lazy dog.
> another line
> ```

**Main prompt:**
> Search `search_test/mixed.md` for the substring `quick`, case-insensitive, with 1 line of context around each match.

**Expected observations:**
- Stage `Search in file` completes successfully.
- Assistant text contains `The QUICK brown fox.` and **also** contains either `intro line` or `jumps over the lazy dog.` (i.e. context lines are present).

**Cleanup:** delete `search_test/mixed.md`.

---

### F-SR-02 — search_in_file: non-home file via absolute URL

**Exercises:** `internal_file_search` (absolute-URL pass-through).

**Preconditions:** non-home fixture from F-RD-01.

**Prompt:**
> Search `files/{fixture_bucket}/qa/notes.txt` for the substring `<FIXTURE_KNOWN_WORD>` (recorded by the runner from the fixture).

**Expected observations:**
- Stage `Search in file` completes successfully.
- Assistant text contains the matched line from the fixture.

**Cleanup:** none.

---

### F-WF-01 — write_file: `content_type=text/csv` (UC-4)

**Exercises:** `internal_file_write` (caller-controlled content type).

**Prompt:**
> Create a CSV file at `orders.csv` with the content:
>
> ```
> id,total
> 1,42
> ```
>
> Set the content type to `text/csv`.

**Expected observations:**
- Stage `Write file` completes successfully.
- Attachment chip `orders.csv` appears.
- (If the runner inspects the attachment download response in the network log) the response `Content-Type` header begins with `text/csv`. This network-level check is optional — record it but do not fail the scenario on it alone, since the chat UI may not expose the MIME directly.

**Cleanup:** delete `orders.csv`.

---

### F-WF-02 — write_file: `content_type=application/json` with nested path

**Exercises:** `internal_file_write` (content_type + nesting).

**Prompt:**
> Create a JSON file at `data/2026/manifest.json` with the content `{"version": 1, "ok": true}` and content type `application/json`.

**Expected observations:**
- Stage `Write file` completes successfully.
- Assistant text mentions path `data/2026/manifest.json`.
- Attachment chip `manifest.json` appears.

**Self-verification (next prompt):**
> Read lines 0 through 2 of `data/2026/manifest.json`.

Expected: content contains `"version"` and `"ok"`.

**Cleanup:** delete `data/2026/manifest.json`.

---

### F-WF-03 — write_file: `content_type` with embedded newline rejected

**Exercises:** `internal_file_write` (content_type header-injection guard).

**Prompt:**
> Create a file at `weird.md` with the content `hi` and the content type `text/plain\nX-Injection: evil`.

(The literal `\n` in the prompt is meant to test that the LLM passes through the newline character as a backslash-n; the agent should use whatever prompt phrasing reliably causes the LLM to forward a content type containing a newline. If the LLM systematically refuses to forward a malformed content type, restate the prompt as: "Pass `text/plain` followed by a newline followed by `X-Injection: evil` as the content type.")

**Expected observations:**
- Stage `Write file` errors with `/content_type/` and `/newline/`.
- No successful `Write file` stage appears for this turn.

**Cleanup:** none.

**Reachability:** if the LLM refuses three rephrased prompts in a row to send a newline-containing content_type, mark scenario as **N/A — unit-test-only** and continue. The unit test `test_write_file_tool.py` covers it directly.

---

### F-WF-04 — write_file: `overwrite=True` happy path

**Exercises:** `internal_file_write` (overwrite branch, ETag-guarded).

**Preconditions:** `reports/summary.md` exists (Success Path baseline).

**Prompt:**
> Overwrite `reports/summary.md` with the new content:
>
> ```
> # Q2 Summary
> Different content now.
> ```

**Expected observations:**
- Stage `Write file` completes successfully.
- Attachment chip `summary.md` appears (the new version).

**Self-verification (next prompt):**
> Read lines 0 through 5 of `reports/summary.md`.

Expected: content is the new Q2 text; the prior `All green and audited.` is gone.

**Cleanup:** restore the baseline by running:
> Overwrite `reports/summary.md` with the content `# Q1 Summary\nAll green and audited.\n`.

Verify with a re-read.

---

### F-WF-05 — write_file: `overwrite=True` concurrent modification (race)

**Exercises:** `internal_file_write` (ETag-mismatch error path).

**Reachability:** this requires the runner to mutate `reports/summary.md` from outside the chat session between the metadata fetch and the upload. Two viable techniques:

- **Two-tab** — the runner opens a second authenticated browser tab on the same QuickApp and times a `Overwrite reports/summary.md with content "race-winner"` prompt to land while the first tab's `write_file(overwrite=True)` is mid-flight.
- **Direct REST** — the runner uses the DIAL Core files API directly to PUT new bytes to the file's URL between the metadata fetch and the upload.

Both are timing-sensitive. **If neither is achievable, mark scenario as N/A — unit-test-only.** The unit test `test_write_file_tool.py` covers `EtagMismatchError`.

**If reachable:**

**Prompt (tab 1):**
> Overwrite `reports/summary.md` with the new content `tab-1 wins`.

(Runner stages the concurrent mutation here.)

**Expected observations (tab 1):**
- Stage `Write file` errors with `/concurrent/` and `/re-read/` (or `/retry/`).

**Cleanup:** restore baseline as in F-WF-04.

---

### F-EF-01 — edit_file: `old_string` matches multiple sites

**Exercises:** `internal_file_edit` (uniqueness check).

**Preconditions:** need a file where the same substring appears twice. Setup:

> Create a file at `edit_test/dup.md` with the content:
>
> ```
> foo
> bar
> foo
> ```

**Main prompt:**
> In `edit_test/dup.md`, replace the text `foo` with `baz`.

**Expected observations:**
- Stage `Edit file` errors with `/multiple/` or `/occur.*more than once/` (or similar uniqueness-violation message).

**Self-verification (next prompt):**
> Read lines 0 through 3 of `edit_test/dup.md`.

Expected: file content unchanged (still has both `foo` lines).

**Cleanup:** delete `edit_test/dup.md`.

---

### F-EF-02 — edit_file: `old_string == new_string`

**Exercises:** `internal_file_edit` (no-op rejection).

**Preconditions:** any existing file. `reports/summary.md` works.

**Prompt:**
> In `reports/summary.md`, replace the text `Q1 Summary` with `Q1 Summary` (yes, identical).

**Expected observations:**
- Stage `Edit file` errors with `/identical/` or `/same/` or `/no-op/` (or whatever the design's specific message is for this case).

**Self-verification:** file content unchanged — confirmed by next `read_file_lines`.

**Cleanup:** none.

---

### F-CP-01 — copy_file: relative source within home

**Exercises:** `internal_file_copy` (relative→relative path, not just absolute→relative).

**Preconditions:** `reports/summary.md` exists.

**Prompt:**
> Copy `reports/summary.md` to `backups/summary.md`.

**Expected observations:**
- Stage `Copy file` completes successfully.
- Assistant text mentions path `backups/summary.md`.

**Self-verification (next prompt):**
> List the files under `backups/`.

Expected: listing includes `backups/summary.md` with non-zero size.

**Cleanup:** delete `backups/summary.md`.

---

### F-MV-01 — move_file: within-home rename leaves no remnant

**Exercises:** `internal_file_move` (atomic remove of source).

**Preconditions:** setup:
> Create a file at `mv_remnant/src.md` with content `payload`.

**Main prompt:**
> Move `mv_remnant/src.md` to `mv_remnant/dst.md`.

**Expected observations:**
- Stage `Move file` completes successfully.

**Self-verification (two prompts):**
1. > Read lines 0 through 1 of `mv_remnant/dst.md`.

   Expected: content is `payload`.
2. > Read lines 0 through 1 of `mv_remnant/src.md`.

   Expected: stage `Read file lines` errors with `/not found/` or similar — i.e., the source is truly gone.

**Cleanup:** delete `mv_remnant/dst.md`.

---

### F-XX-403 — Tool surfaces 403 Forbidden as actionable error

**Exercises:** any read tool against a forbidden URL.

**Reachability:** this requires an absolute `files/...` URL the test app's identity can resolve but cannot read (403 from DIAL Core). If no such URL is available in the target environment, **mark scenario as N/A — unit-test-only**. The unit test for `_DialFileTool` covers the 403 branch.

**If reachable:**

**Prompt:**
> Read lines 0 through 3 of `files/{forbidden_bucket}/path/that/exists.txt`.

**Expected observations:**
- Stage `Read file lines` errors with `/access denied/` or `/forbidden/` (matches the design's "access denied: {url}" message).

**Cleanup:** none.

## 9. Out of plan

The following are deliberately excluded from this manual plan; they are either unit-test-only or unreachable from the chat UI without significant infrastructure.

- **Path-traversal regex coverage edge cases** — `foo//bar`, segments equal to `..`, trailing whitespace, leading `/`. B-WF-01 covers the user-facing rejection shape; per-form coverage lives in unit tests (`_base_file_tool` / `_resolve_appdata_url` tests).
- **`DialFilesConfig` field-validator failures at startup** — missing `files/` prefix, missing trailing `/`, unknown `{...}` token, `..` segment. Verified at app boot; not exposed in the chat UI.
- **`agent_home_dir` template without `{appdata}`** — operator-side config; no LLM-visible difference beyond a different resolved home dir. Out of scope for this plan; covered by `test_base_file_tool.py`.
- **Appdata-missing branch (`my_appdata_home()` returns `None`)** — every supported deployment populates appdata; the chat UI cannot easily simulate the absence. Unit-test-only.
- **Recursive folder copy/move** — not implemented (design explicitly excludes); nothing to test.
- **Binary / non-UTF-8 files** — design explicitly excludes; not a scenario.
- **Pagination on `list_files`** — not implemented in v1.
- **10 MB read-size limit** — listed for completeness in the design's Error Handling table; staging a >10 MB UTF-8 fixture through the chat UI adds setup overhead disproportionate to the signal. Unit-test-only unless a future regression motivates it.

## 10. Scenario index by tool (for cross-reference)

| Tool | Success | Basic | Full |
|---|---|---|---|
| `list_files` | S-LF-01 | B-LF-01 | F-LF-01, F-LF-02, F-LF-03 |
| `read_file_lines` | S-RD-01 | — | F-RD-01, F-RD-02 |
| `search_in_file` | S-SR-01 | — | F-SR-01, F-SR-02 |
| `write_file` | S-WF-01 | B-WF-01, B-WF-02, B-WF-03 | F-WF-01, F-WF-02, F-WF-03, F-WF-04, F-WF-05 |
| `edit_file` | S-EF-01 | B-EF-01 | F-EF-01, F-EF-02 |
| `delete_file` | S-DL-01 | B-DL-01 | — |
| `copy_file` | S-CP-01 | B-CP-01 | F-CP-01 |
| `move_file` | S-MV-01 | B-MV-01 | F-MV-01 |
| (cross-cutting) | — | — | F-XX-403 |

Totals: **8 Success Path**, **8 Basic**, **17 Full** (plus optional F-WF-05, F-XX-403 gated on reachability), **33 scenarios** total.
