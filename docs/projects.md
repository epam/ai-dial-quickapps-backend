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
     body; capped at `PROJECT_INSTRUCTIONS_MAX_CHARS` (default 32 000) characters with a truncation note; a
     `</project_instructions` in the body is escaped so it can't close the frame. A `PROJECT.md` over the
     file-loading size limit, or one Core fails to return, doesn't fail the turn: the user gets a warning in the
     **Initialization issues** stage, a WARNING is logged, and the turn runs without the section.
   - **Project files**: names the working folder and the `context/` folder (read-only). The files aren't listed,
     so the section changes only when `PROJECT.md` does; the agent lists them with the file tools.
3. **Working folder.** The agent home is the project's `artifacts/`, shared by every chat **and every app** used in the
   project. `features.dial_files.agent_home_dir` is ignored. Relative paths in the file tools and `web_fetch`
   `save_path` resolve there; the app's appdata is reachable only by full `files/...` URL.
4. **Project URLs.** A path starting with `projects/` is an absolute URL, like `files/...`, in every chat. The DIAL
   files tools and `web_fetch` accept full URLs of the current project (`projects/{bucket}/{path}/files/...`)
   wherever they accept a `files/...` URL; any other `projects/...` URL is rejected ("only files of the current
   project"). Other consumers (`get_content`, attachments, DIAL deployments, the
   code interpreter) don't take project URLs yet: see [Known issues](#known-issues).
5. **Read-only files.** Write-side tools (`write_file`, `edit_file`, `delete_file`, the `move_file` source,
   `copy_file` / `move_file` destinations, `web_fetch` `save_path`) accept relative paths only, so they never write
   outside `artifacts/`. Given any `files/...` or `projects/...` URL, they ask for a relative path.

In every chat (not only projects), a 403 from Core on a file tool is reported as a permission error ("access
denied; the app has no permission for it"). It goes through the tool's fallback strategies.

### Known issues

| What happens | Why | Workaround |
|---|---|---|
| A chat in a project shared with the user fails with 403 `project_access_denied` | The declaration `projects/{current-user}/` covers only the user's own projects | None yet: needs a Core grant for shared projects |
| The approved dependency opens **all** of the user's projects to the app, not only the current one | Phase-1 static grant | QuickApps itself touches only the project in the header |
| Project files can't be passed to DIAL deployments (RAG, adapters) or to the code interpreter | These don't read `projects/` URLs yet | Copy the content into the conversation, or use a nested QuickApp |
| MCP `dial_url` parameters with project files are unverified | Per-file grants on `projects/` URLs depend on Core | Avoid project URLs in `dial_url` parameters |
| After a project rename, files attached in earlier turns return 404 | Attachments keep the old URL | Attach the file again |
| The system-prompt cache has one entry per project and is rewritten when `PROJECT.md` changes | The project instructions are part of the system prompt | None needed; the first turn after a change costs a cache write |

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| 403 `project_access_denied`: "An administrator must approve the app's access to projects (resource dependencies)." | The app has no approved resource dependency on `projects/{current-user}/` (missing, revoked, or a shared project). An admin declares and approves it: [CONFIGURATION — Projects](../CONFIGURATION.md#projects) |
| 404 `project_not_found`: "The project was not found. It may have been deleted or renamed." | The project in `x-project-id` no longer exists under that name |
| The agent ignores the project instructions or files | `ENABLE_PREVIEW_FEATURES` is off, or the request has no `x-project-id` header (a malformed header is ignored with a WARNING log) |
| The agent can't find the context files | The app has no DIAL files tool that lists or reads files (`features.dial_files.enabled_tools`) |
| Initialization issues: "PROJECT.md could not be loaded" | `PROJECT.md` is over the file-loading size limit, or Core returned an error for it (WARNING log) |
| Something else fails only in project chats (shared projects, deployments, attachments after a rename, ...) | Check [Known issues](#known-issues) |
