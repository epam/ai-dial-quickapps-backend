# Design: Folder Context

- **Status:** Implemented
- **Dependencies:**
  - [dial_files_tools.md](dial_files_tools.md) — DIAL file tools (`list`, read/write surface)
  - [preview_feature_gating.md](preview_feature_gating.md) — preview gating for folder contexts and dial-files
  - [generic_synthetic_toolcall_injector.md](generic_synthetic_toolcall_injector.md) — attachment-notification injector pattern
- **Replaces:** An earlier draft that proposed request-time folder expansion via a `/.dial_folder` URL convention on `FileContextConfig`. Intermediate drafts proposed synthetic `internal_file_list` message pairs — superseded by enriching the available-context tool response (see Concern 3).

## Problem Statement

QuickApps administrators can attach **contexts** — static knowledge the agent should be aware of — via `application_properties.contexts`. Today each attached **file** requires its own `FileContextConfig` entry with an explicit DIAL URL.

When an administrator wants the agent to work with a **shared document folder** (e.g. a team docs bucket that users upload to over time), every new or removed file requires a configuration change. The admin must edit the QuickApp manifest to add or remove individual `FileContextConfig` entries. This is brittle, slow, and does not scale for folders that change frequently.

A single `FileContextConfig` can carry a `description` that tells the orchestrator what the file contains. A `FolderContextConfig` has only an optional folder-level `description` — it does not describe individual files inside. That gap may be filled in future by convention files living in the folder itself (see *Future: folder instruction files*).

## Design Goals

- Administrators can attach a **folder** as a context item alongside files and user-defined text (**preview-gated** until stable).
- New files and subfolders added under an attached folder become discoverable by the agent **without** changing QuickApp configuration.
- Folder expansion (files **and** child folders, recursively) is delivered through the **`internal_attachments_available_context` tool response** — no separate synthetic `internal_file_list` assistant/tool message pairs.
- For every `FolderContextConfig` in `contexts`, the backend **always** runs folder expansion when building the available-context response (same as if the tool were invoked for that folder on every request).
- Expanded file URLs are then available to whatever tools the QuickApp author configured (RAG, MCP, get-content, dial-files, etc.).
- Folder expansion uses a **`FolderListingProvider` port** in `dial_core_services` — it does **not** require `features.dial_files` or LLM-invoked file tools.
- Folder contexts and dial-files remain **preview-gated** until they graduate to stable.

---

## Use Cases

### UC-1: Admin attaches a shared docs folder (RAG-backed QuickApp, preview on)

**Trigger:** Operator sets `ENABLE_PREVIEW_FEATURES=true`. Administrator configures a folder context at `metadata/files/{bucket}/shared-docs/` and a DIAL RAG tool. No `features.dial_files` block.

**Behavior:** On every request, `_AvailableContextTool` / notification injector builds an available-context response that includes the folder root entry **and** recursively expanded child folders and files under `files/{bucket}/shared-docs/`. The attachment-notification injector surfaces this response when membership changes. The orchestrator passes discovered file URLs to RAG.

**Outcome:** The agent can answer questions about documents in the folder using RAG. A new upload under `shared-docs/` or a nested subfolder appears on the next request's available-context response — no manifest update required.

### UC-2: Mixed static file and dynamic folder

**Trigger:** Contexts include one `FileContextConfig` (policy PDF) and one `FolderContextConfig` (living FAQ folder with nested subfolders). Preview on.

**Behavior:** Available-context returns the PDF entry plus the expanded tree for the folder (root folder entry, subfolder entries, file entries with inferred MIME types). Static PDF is fetched via get-content; folder files are handled by configured tools (MCP, RAG, etc.).

**Outcome:** Static and dynamic knowledge sources coexist. Nested folder structure is visible to the orchestrator without per-file config entries.

### UC-3: Production deployment without preview features

**Trigger:** Operator deploys with `ENABLE_PREVIEW_FEATURES=false`. App manifest still lists a folder context (e.g. persisted from staging).

**Behavior:** Preview validator nullifies folder context entries (logs warning). Available-context behaves as if folder contexts were absent. No folder expansion runs. `features.dial_files` is also nullified (existing preview behaviour).

**Outcome:** No folder-context or dial-files behaviour in production until the feature graduates from preview.

### UC-4: App with dial-files `all` preset (preview on)

**Trigger:** Preview on. App configures `features.dial_files.enabled_tools: "all"` alongside folder context.

**Behavior:** Available-context response includes recursively expanded folder tree. All eight dial-files tools are registered for LLM invocation (read + write). Folder discovery does not depend on the LLM calling `list` — expansion is always in the available-context payload.

**Outcome:** Agent sees full folder tree via available-context; may additionally use dial-files tools for appdata read/write during the conversation.

### UC-5: Context change notification on folder membership update

**Trigger:** A new file is uploaded to a nested subfolder under an attached folder context.

**Behavior:** `build_context_entries` (async, with expansion) produces an updated set of entries compared to history from prior available-context tool results. New file URLs produce `status: "new"`; removed URLs produce `status: "removed"`. Subfolder entries appear when subfolders are created. The attachment-notification injector surfaces the delta.

**Outcome:** The agent is notified when folder **membership** changes, not only when admin edits folder metadata in config.

---

## Proposed Design

### Concern 1: `FolderContextConfig` (config schema, preview-gated)

**What:** A dedicated context discriminator `type: "folder"` in the `Context` union.

**Owner:** `src/quickapp/config/context.py`

**Semantics:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"folder"` | `"folder"` | Discriminator value. **Preview-gated** — omitted from JSON schema when preview is off. |
| `url` | DIAL file URL | required | Folder path in DIAL storage. Format: `metadata/files/{bucket}/{path}/` (trailing slash). |
| `mime` | string | `application/vnd.dial.metadata+json` | MIME for the **root** folder entry in available-context. Child folders use the same default unless overridden later. |
| `description` | string \| null | null | Optional label for the root folder entry. |
| `max_depth` | integer | `10` | Maximum recursion depth when expanding child folders and files (same bound as dial-files `list`). |

**Preview gating:**

- Mark the `folder` variant as preview in schema generation (same mechanism as `PreviewField` — hidden from schema when `ENABLE_PREVIEW_FEATURES=false`).
- At runtime, `_gate_preview_fields` / context validation strips `FolderContextConfig` entries from `contexts` when preview is off; log warning if present in persisted config.

**Change:** Implemented — `max_depth`, preview-gated discriminator, trailing-slash URL validation.

### Concern 2: Recursive folder expansion in available-context response

**What:** When building the `internal_attachments_available_context` response, **expand each `FolderContextConfig` recursively** into `ContextEntry` rows for the root folder, every nested subfolder, and every file under the configured tree.

**Owner:** `src/quickapp/attachment_processing/_context_entries.py`, `_available_context_tool.py`, `_attachment_notification_injector.py`

**Semantics:**

- **No synthetic `internal_file_list` pairs.** Expansion results appear only inside the available-context JSON response (`AvailableContextToolResponse.entries`).
- **Always expand for each folder context** whenever the available-context tool runs or when the notification injector builds content — there is no lazy "agent must call list first" path for admin folder contexts.
- **Recursive listing:** For each `FolderContextConfig`, call `FolderListingProvider.expand_folder(files_url, max_depth=ctx.max_depth)` which returns a flat list of `(url, is_folder, mime, description)` entries:
  - Root folder row (metadata MIME + config `description`).
  - Each **child folder** row (metadata MIME; title = folder name; `description` null unless future instruction files apply).
  - Each **file** row (inferred MIME from extension; title = filename).
- **URL mapping:** `metadata/files/{bucket}/{path}/` → `files/{bucket}/{path}/` for DIAL listing API.
- **Ordering:** Deterministic (sort by URL) so new/removed detection is stable across requests.
- **Change detection:** Compare expanded URL set against history from prior available-context tool results. Individual files and subfolders inside configured folders participate in `new` / `removed` / `updated` status — unlike earlier designs that only tracked the root folder URL.
- **Static file contexts unchanged:** `FileContextConfig` and `UserDefinedContextConfig` behaviour is unchanged.

**Response shape (conceptual):**

```json
{
  "entries": [
    {
      "title": "shared-docs",
      "url": "metadata/files/bucket/shared-docs/",
      "type": "application/vnd.dial.metadata+json",
      "description": "Team documentation"
    },
    {
      "title": "2026",
      "url": "files/bucket/shared-docs/2026/",
      "type": "application/vnd.dial.metadata+json"
    },
    {
      "title": "report.pdf",
      "url": "files/bucket/shared-docs/2026/report.pdf",
      "type": "application/pdf",
      "status": "new"
    }
  ]
}
```

**Change:** Implemented — `build_context_entries_async` with `FolderListingProvider`; request-scoped listing cache on `ExpandedContextFileUrls`.

```mermaid
sequenceDiagram
  participant Notif as notification_injector
  participant AC as _AvailableContextTool
  participant BCE as build_context_entries
  participant FLP as FolderListingProvider
  participant Orch as orchestrator

  Notif->>BCE: expand contexts (async)
  loop each FolderContextConfig
    BCE->>FLP: expand_folder(files_url, max_depth)
    FLP-->>BCE: root + subfolders + files
  end
  BCE-->>Notif: entries with status
  Notif-->>Orch: synthetic available_context result
  Orch->>AC: list admin contexts (optional re-fetch)
  AC->>BCE: same expansion path
  BCE-->>Orch: enriched entries
```

### Concern 3: Always surface available-context for folder contexts

**What:** Ensure the orchestrator always receives an up-to-date available-context result when folder contexts are configured (preview on).

**Owner:** `attachment_processing` module

**Semantics:**

- `should_activate_context_tool` remains `true` when any preview-valid `FolderContextConfig` is present.
- `_AttachmentNotificationInjector` uses `InjectionFrequency.ALWAYS` when folder contexts exist (or when any context entry changed), so the enriched response is injected at request setup — the agent does not need to invoke the tool first to see folder contents.
- `_AvailableContextTool` uses the **same** expansion path when the LLM calls it later in the conversation (re-list / refresh).
- `should_enable_get_content_tool`: enabled when expanded entries include file MIME types the deployment accepts (same rules as static file contexts); folder metadata rows alone do not enable get-content.

**Change:** Implemented — membership diff via expanded URL set; `InjectionFrequency.ALWAYS` (unchanged from prior behaviour).

### Concern 4: DIAL file tools move to `shared` (deferred)

**Status:** Out of scope for v1. Folder context does not depend on this move.

**What (future):** Relocate dial-files tooling from `dial_files_tooling/` to `shared/dial_files/` and optionally share listing helpers with `_ListFilesTool`.

**Why deferred:** Folder expansion uses `FolderListingProvider` bound in `dial_core_services`; `attachment_processing` never imports `dial_files_tooling`. The move is a separate refactor with no folder-context functional gain.

### Concern 5: File tool presets — `read_only` and `all` (deferred)

**Status:** Out of scope for v1.

**What (future):** Add a `"read_only"` preset to `DialFilesConfig.enabled_tools` alongside `"all"` and explicit tool lists.

**Note:** Folder expansion does **not** require `features.dial_files` regardless of preset design.

### Concern 6: Preview gating (folder + dial-files)

**What:** Both folder contexts and dial-files remain preview-gated for v1.

**Owner:** `config/context.py`, `config/application.py`, `dial_files_tooling/dial_files_tooling_module.py`, schema generation

**Semantics:**

| Feature | Gating mechanism |
|---------|------------------|
| `FolderContextConfig` in `contexts` | Preview discriminator in schema; runtime strip + warn when preview off |
| `features.dial_files` | Existing `PreviewField` on `Features.dial_files` |
| `DialFilesToolingModule` | Existing `@preview_module` |

When `ENABLE_PREVIEW_FEATURES=false`:

- Folder contexts in persisted configs are ignored (with warning).
- `features.dial_files` nullified (existing behaviour).
- `DialFilesToolingModule` not wired (existing behaviour).

When preview is enabled, both features are fully functional.

**Graduation path (future):** Remove preview marker from folder discriminator and/or remove `@preview_module` / `PreviewField` when stable — independent decisions.

### Concern 7: UI — folder context picker

**What:** Configuration UI support for adding a folder as a contexts item (**visible only when preview features enabled** in the deployment / schema).

**Owner:** QuickApps configuration UI (frontend)

**Semantics:**

- Contexts editor offers **Folder** type when preview schema includes the `folder` discriminator.
- Folder picker writes `{ "type": "folder", "url": "…", "description": "…", "max_depth": 10 }`.
- UI copy: folder contents (files and subfolders) appear automatically in available-context responses; `features.dial_files` is optional for LLM-driven file operations.

---

## Future: folder instruction files (not in v1)

**Problem:** Expanded file entries have inferred MIME only — no per-file description unless each file is a separate `FileContextConfig`.

**Idea:** Well-known files inside the attached folder tree:

| Filename | Purpose |
|----------|---------|
| `agents.md` | Agent/orchestrator instructions for this folder |
| `descriptions.md` | Per-file or section descriptions |
| `README.md` | General orientation |

**Proposed behaviour (future):** During expansion, detect these files at each folder root, download text, and attach content to the root folder entry's `description` or a dedicated field on `ContextEntry`. Same freshness model as recursive expansion (per-request).

---

## Secondary Fixes

### Available-context tool description

Implemented in `attachment_processing/_tool_configs.py`: folder contexts expand recursively into folder and file entries in **this** response. Subfolders use metadata MIME; files use inferred MIME.

### System prompt guidance (optional)

"When available-context returns folder entries (`application/vnd.dial.metadata+json`) and file entries under the same tree, use file URLs with your configured tools."

---

## Out of Scope

- **Synthetic `internal_file_list` assistant/tool message pairs.** Superseded by enriched available-context response.
- **`write`-only dial-files preset.** Use `"all"` instead.
- **Folder instruction files (`agents.md`, etc.).** Future work.
- **Admin UI implementation.** Frontend repo.
- **Non-DIAL folder URLs.** Only `metadata/files/...` supported.
- **Prescribing which tool consumes folder files.** Up to QuickApp tool configuration.

---

## Configuration / Usage Examples

### Folder context only (preview on)

```json
{
  "contexts": [
    {
      "type": "folder",
      "url": "metadata/files/684f6Lz7ubje66aoCRsa5c/shared-docs/",
      "description": "Team documentation",
      "max_depth": 10
    }
  ]
}
```

No `features.dial_files` required. Available-context response includes root folder, subfolders, and files.

### Folder + optional dial-files read-only

```json
{
  "contexts": [
    {
      "type": "folder",
      "url": "metadata/files/org-bucket/faq/",
      "description": "Living FAQ"
    }
  ],
  "features": {
    "dial_files": {
      "enabled_tools": ["list", "read_lines", "search"]
    }
  }
}
```

### Mixed file and folder with dial-files all

```json
{
  "contexts": [
    {
      "type": "file",
      "url": "files/org-bucket/policies/terms.pdf",
      "description": "Terms of service"
    },
    {
      "type": "folder",
      "url": "metadata/files/org-bucket/faq/",
      "description": "Living FAQ"
    }
  ],
  "features": {
    "dial_files": {
      "enabled_tools": "all"
    }
  }
}
```

Requires `ENABLE_PREVIEW_FEATURES=true`.

### `enabled_tools` reference (preview on)

| Value | Tools registered |
|-------|------------------|
| `"all"` | All eight tools |
| `["list", "read_lines"]` | Listed tools only |

See [dial_files_tools.md](dial_files_tools.md) for full dial-files configuration.

---

## Migration

### Breaking changes

- **Folder available-context shape:** Apps that relied on a single metadata row per folder will see many entries (files + subfolders). Notification diffs will include membership changes.

### Non-breaking changes

- `FolderContextConfig` and folder expansion are additive when preview on.
- `dial_files_tooling` package path and `DialFilesConfig` presets are unchanged in v1.

---

## Summary of Changes

| Component | Status | Change |
|-----------|--------|--------|
| **`FolderContextConfig`** | Done | `max_depth`, preview-gated discriminator, URL validation |
| **`build_context_entries_async`** | Done | Recursive expansion via `FolderListingProvider`; per-request listing cache |
| **`_AvailableContextTool`** | Done | Async expansion path |
| **`_AttachmentNotificationInjector`** | Done | Expanded membership diff; `InjectionFrequency.ALWAYS` |
| **`DialFolderListingProvider`** | Done | `FolderListingProvider` in `dial_core_services` |
| **Preview gating** | Done | Folder discriminator strip + warning; existing dial-files preview |
| **Configuration UI** | **TODO** (frontend) | Folder picker (preview schema) |
| **Folder instruction files** | Future | `agents.md` etc. |
| **Dropped:** synthetic `internal_file_list` injection | — | Enriched available-context instead |
| **Deferred:** `shared/dial_files` move | Future | Separate refactor; not required for folder context |
| **Deferred:** `read_only` preset | Future | Separate dial-files enhancement |

---

## Implementation: module structure

### Module inventory (as built)

| Module | Role |
|--------|------|
| `dial_files_tooling` | LLM-facing file tools (unchanged location; optional via `features.dial_files`) |
| `dial_core_services` | `DialFileService` + `DialFolderListingProvider` (`FolderListingProvider` impl) |
| `common/abstract` | `FolderListingProvider` port; `folder_context_urls.py` URL helper |
| `attachment_processing` | Available-context expansion + notification injector |

### Dependency diagram (as built)

```mermaid
flowchart TB
  subgraph allowed["May import: config, common, shared, agent, application"]
    AP["attachment_processing"]
    DFT["dial_files_tooling"]
  end

  subgraph infra["Infrastructure"]
    DCS["dial_core_services"]
  end

  AP --> config
  AP --> common
  DFT --> DCS
  DFT --> config
  DCS --> common
```

`attachment_processing` injects `FolderListingProvider` (ABC in `common`); implementation is `DialFolderListingProvider` in `dial_core_services`. No import from `dial_files_tooling`.

### What we deliberately do **not** do (v1)

| Approach | Why rejected / deferred |
|----------|-------------------------|
| Synthetic `internal_file_list` message pairs | Enrich available-context instead |
| Move `dial_files_tooling` → `shared` | Not required for folder context; separate refactor |
| `read_only` dial-files preset | Separate dial-files enhancement |
| `attachment_processing` → `dial_core_services` direct import | Use `FolderListingProvider` port |
| Stable (non-preview) folder contexts in v1 | Preview-gated until graduation |

### Testing layout

| Module | Tests |
|--------|-------|
| `common` | URL mapping; ABC contract |
| `dial_core_services` | Recursive expansion via `DialFolderListingProvider` |
| `attachment_processing` | Expanded entries in available-context; subfolder rows; new/removed file status |

### Future: `agents.md`

Extend `FolderListingProvider.expand_folder` (or post-process step in `build_context_entries_async`) to merge instruction file content into folder entry descriptions. Still no synthetic tool pairs.
