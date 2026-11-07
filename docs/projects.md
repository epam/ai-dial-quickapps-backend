# Projects

`[Preview]` Requires `ENABLE_PREVIEW_FEATURES=true`. Configure: [CONFIGURATION — Projects](../CONFIGURATION.md#projects).
Design: [designs/projects.md](./designs/projects.md).

## What it does

DIAL Chat projects hold instructions, context files and chats. On every model call of a project chat Chat sends one
header, `x-project-id: projects/{bucket}/{path}`. QuickApps uses it as the only link to the project: no manifest field
is needed. Without the header (or with preview features off) the app behaves as in any other chat.

A project lives under Core's `projects/{bucket}/{path}/files/`:

| Path | Content | Agent access |
|---|---|---|
| `PROJECT.md` | Project instructions (YAML frontmatter + body) | read |
| `context/` | Files the user added to the project | read |
| `conversations/` | The project's chats (Chat only) | read |
| `artifacts/` | Files produced in the project, shown by Chat as **Outputs** | read + write (the working folder) |

## In a project chat

1. **Access check.** Before any model or tool call, one `GET /v2/metadata/projects/{bucket}/{path}` with the request's
   key. Without access the turn ends at once (see [Troubleshooting](#troubleshooting)).
2. **System prompt.** Two sections follow the app's own system prompt:
   - **Project instructions**: the `PROJECT.md` body with the frontmatter removed, framed as user context (the app's
     prompt wins on conflict). No section for a missing or empty file; malformed frontmatter is kept as part of the
     body; capped at 32 000 characters with a truncation note; a `</project_instructions` in the body is escaped so
     it can't close the frame. A `PROJECT.md` over the file-loading size limit, or one Core fails to return, doesn't
     fail the turn: the section only says "PROJECT.md could not be loaded (reason)" and a WARNING is logged.
   - **Project files** (only when the app has a [DIAL files tool](../CONFIGURATION.md#dial-files-configuration)
     that reads files: `read_lines`, `read_chars` or `search` in `enabled_tools`): names the working folder, then
     lists the `context/` files by full path, read-only, up to 100 entries. The listing walks `context/`
     folder by folder and stops once more than 100 files are found (at most 10 levels deep and 50 folders);
     the note is "and N more" when the walk finished, "and more" when it stopped early. If the listing fails, the
     list is left out (WARNING log).
3. **Working folder.** The agent home is the project's `artifacts/`, shared by every chat **and every app** used in the
   project. `features.dial_files.agent_home_dir` is ignored. Relative paths in the file tools and `web_fetch`
   `save_path` resolve there; the app's appdata is reachable only by full `files/...` URL.
4. **Project URLs.** The DIAL files tools, `web_fetch`, `get_content` and message attachments accept full URLs of the
   current project (`projects/{bucket}/{path}/files/...`) wherever they accept a `files/...` URL. Any other
   `projects/...` string is an ordinary relative path, as outside projects. In attachments, the absolute Core form
   (`{DIAL_URL}/v1/projects/...` of the current project) is turned into the relative form first. DIAL deployments and
   the code interpreter don't read project URLs yet: see **Downstream** below and [Known issues](#known-issues).
5. **Read-only files.** Write-side tools (`write_file`, `edit_file`, `delete_file`, the `move_file` source,
   `copy_file` / `move_file` destinations, `web_fetch` `save_path`) accept relative paths only. Given a project file
   outside `artifacts/`, they answer "read-only project file; write under the working folder with a relative path".

6. **Downstream.** Project files and home-relative paths go to DIAL deployments as `url` attachments as is; a
   deployment that can't read `projects/` URLs answers with its own error, shown as a tool error. The code
   interpreter refuses project files at once ("project files can't be passed to the interpreter yet"). Nested apps and
   MCP servers receive `x-project-id` as before; REST API tools don't.

In every chat (not only projects), a 403 from Core on a file tool is reported as a permission error that the agent
should not retry with other paths. It goes through the tool's fallback strategies.

### Known issues

| What happens | Why | Workaround |
|---|---|---|
| A chat in a project shared with the user fails with 403 `project_access_denied` | The declaration `projects/{current-user}/` covers only the user's own projects | None yet: needs a Core grant for shared projects |
| The approved dependency opens **all** of the user's projects to the app, not only the current one | Phase-1 static grant | QuickApps itself touches only the project in the header |
| Project files can't be passed to DIAL deployments (RAG, adapters) or to the code interpreter | These don't read `projects/` URLs yet | Copy the content into the conversation, or use a nested QuickApp |
| MCP `dial_url` parameters with project files are unverified | Per-file grants on `projects/` URLs depend on Core | Avoid project URLs in `dial_url` parameters |
| After a project rename, files attached in earlier turns return 404 | Attachments keep the old URL | Attach the file again |
| The system-prompt cache has one entry per project and is rewritten when `PROJECT.md` or `context/` changes | The project sections are part of the system prompt | None needed; the first turn after a change costs a cache write |

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| 403 `project_access_denied`: "An administrator must approve the app's access to projects (resource dependencies)." | The app has no approved resource dependency on `projects/{current-user}/` (missing, revoked, or a shared project). An admin declares and approves it: [CONFIGURATION — Projects](../CONFIGURATION.md#projects) |
| 404 `project_not_found`: "The project was not found. It may have been deleted or renamed." | The project in `x-project-id` no longer exists under that name |
| The agent ignores the project instructions or files | `ENABLE_PREVIEW_FEATURES` is off, or the request has no `x-project-id` header (a malformed header is ignored with a WARNING log) |
| The agent doesn't list the context files | The app has no DIAL files tool that reads files (`read_lines`, `read_chars` or `search` in `features.dial_files.enabled_tools`), or listing `context/` failed (WARNING log) |
| The prompt says "PROJECT.md could not be loaded" | `PROJECT.md` is over the file-loading size limit, or Core returned an error for it (WARNING log) |
| Something else fails only in project chats (shared projects, deployments, attachments after a rename, ...) | Check [Known issues](#known-issues) |

### Testing

| Suite | Runs | Covers |
|---|---|---|
| `src/tests/integration_tests/test_projects.py` | with the other integration tests (`make integration_test MODEL=...`): in-process, static key; skipped when Core has no v2 project API | instructions, `context/` read, a file written in chat 1 found in chat 2 under `artifacts/`, no header, an MCP file output in `artifacts/` |
| `src/tests/integration_tests/test_projects_core_path.py` | opt-in: `make projects_core_path_test MODEL=...` (sets `PROJECTS_CORE_PATH=true`); skipped without the Core URL and user/admin credentials | the same through Core with a user token and the per-request key, plus a nested app, and 403 `project_access_denied` after the admin consent is revoked |

The Core-path suite needs a Core with resource dependencies ([#1930](https://github.com/epam/ai-dial-core/issues/1930))
and `projects` as a declarable target, a QuickApps instance registered in it with `ENABLE_PREVIEW_FEATURES=true`, and
an admin who can consent. The suite registers its two apps with the `projects/{current-user}/` READ + WRITE
dependencies and grants the consent itself. Setup and the `PROJECTS_CORE_*` variables: the module docstring.
