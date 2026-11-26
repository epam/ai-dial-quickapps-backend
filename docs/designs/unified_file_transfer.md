# Design: Unified file transfer

- **Status:** Draft. Code references verified against branch `chore/file_transfer_refactoring` on 2026-11-23. The projects stack up to PR 4/5 ([PR#727](https://github.com/epam/ai-dial-quickapps-backend/pull/727)) and `feat/420-skill-script-transfer` are in that tree; PR 5/5 ([PR#729](https://github.com/epam/ai-dial-quickapps-backend/pull/729)) is not. The work is sliced in "Implementation slicing" at the end of this document, which is the entry point for a new session.
- **Issue:** TBD
- **Related:** [`projects.md`](projects.md) (D3-D8, C4), [I#725](https://github.com/epam/ai-dial-quickapps-backend/issues/725) (output name collisions)

Code references are to the `chore/file_transfer_refactoring` tree (projects stack up to PR 4/5, skills branch merged,
`file_transfer/` now in `shared/file_transfer/`). Line numbers drift: find a symbol by name first.

> **Before this draft becomes the final design:** everything this document says about the Core file API for complex
> resources (called "the unified API" below) comes from a Core draft (`design/universal_file_api.md`), which is itself
> not final. The document must be re-checked against the **final** version of that Core design before it leaves draft.
> Walk through "Context: the Core universal file API", "Migration to the unified API" and the Core-related open
> questions, and update at least: the route shapes, the ETag and `PUT` response semantics, the authorization model
> (resource root only) and what it means for grants to external consumers, the copy and move rules, the error codes,
> the rollout and compatibility behaviour, and whether folder listings carry sizes. Any decision here that rests on a
> point the final Core design changes (for example the by-value default for project files, the single canonical URL
> form, skipping C1 to C4) is to be reopened, not carried over.
>
> Last compared with the Core draft on 2026-11-26. The direction changed since the previous comparison (2026-11-24):
> Core extends the existing `/v1` API instead of adding a `/v2/files` family. A file of a complex resource keeps its
> DIAL URL with the reserved `files` segment, so there is no second URL form, no legacy-link fallback and no
> `/v2/ops/files` route. Copy and move now also work across groups. The Core draft is still not final.

## Problem Statement

After the projects stack, "is this chat in a project?" is answered in many places, by different means:

- `DialCoreServicesModule.__provide_file_storage` always builds `RoutedFileStorage(v1, project_storage, project)`; the
  `None` case is handled inside `RoutedFileStorage`, not by a DI branch.
- URL routing by `ProjectContext.contains`: `RoutedFileStorage`.
- `_project is None / is not None` inside services: `HomePathResolver` (home root, path canonicalisation,
  display path), `AttachmentService.upload_output_bytes` (output root), `AttachmentResolver`, `_GetContentTool`, the
  project prompt provider and the access preflight.
- String prefixes, each with its own idea of "a DIAL URL": `HomePathResolver.is_absolute`, `classify_url` (regex,
  tolerates a leading `/`, knows `projects/` but not `skills/`), `is_dial_storage_path` (no leading `/`),
  `startswith("files/")` literals, and `projects/` branches in `RoutedFileStorage`, `AttachmentResolver` and
  `_GetContentTool`.
- Skills (`feat/420-skill-script-transfer`, merged into this branch) add a third kind of path: the `skill://` reference and
  `skills/{bucket}/{name}/files/...` URLs, a second extension point (`FileSource`, above `classify_url`) next to
  `FileStorage` (below it), and a skill-root special case for MCP grants in `_MCPTool`.
- `_MCPTool` rejects appdir-relative `dial_url` paths instead of resolving them (TODO #445), because it has no access to
  the path rules.

Consequences:

- The write root is chosen twice (`HomePathResolver.resolve_home_dir`, `AttachmentService.upload_output_bytes`), the
  escape-from-root guard twice (`has_unsafe_segments` + `_validate_relative_path` vs `contains`).
- The "project files can't reach v1 consumers" limitation (C4) is a doc note, not code. `DialFilePromoter`,
  `AttachmentResolver` and `InputFileHandler` call the v1 client directly, bypassing `FileStorage`. Only
  `AttachmentResolver` has its own `projects/` branch; the promoter and the input handler have none, so a project URL
  reaches the v1 client, and aidial-client rejects it before any request (`InvalidDialURLError`, "Invalid resource
  type"; B1 pins the exact behaviour). A new consumer that forgets the check fails the same way.
- Lifting C4 (deployments and the interpreter reading `projects/` URLs) and I#725 (collision-safe output names) will
  each touch 6-7 of these places.

### Duplicated I/O seams below the routing

Separate from "where does a path live": a few places still do the same thing twice. Some duplication that an earlier
survey of the `development` baseline reported is already gone after the projects stack, so this is the verified list.

**Still duplicated**

1. **Two DIAL download entry points.** `DialFileService.download_file` (`dial_file_service.py:34`) and
   `FileLoaderService.__do_load` → `DialDownloader.fetch` (`shared/file_transfer/_file_loader_service.py:91`, the `fetch` call in `__load_dial` at `:108-109`,
   `dial_downloader.py:30`) both do `StateHolder` lookup, `FileStorage.download`, `StateHolder.store_file_data`. They
   share the `StateHolder`, so a file is not downloaded twice, but `DialDownloader` is a one-line wrapper whose
   docstring carries an invariant that belongs to the cache (the metadata must be stored next to the bytes, or the edit
   tool loses the ETag it needs for `If-Match`), and only `FileLoaderService` de-duplicates concurrent loads of one URL.
2. **Two sources of the appdata root.** `AttachmentService._appdata_root` (`attachment_service.py:98`) asks
   `bucket.get_raw()` and builds `files/{appdata or bucket}/`; `HomePathResolver` (`home_path_resolver.py:122`) asks
   `DialFileService.my_appdata_home()`. Both end in the same Core endpoint (`GET /v1/bucket`, aidial-client
   `resources/bucket.py`), so they agree on the value. They differ in handling: `AttachmentService` takes
   `appdata or bucket`, `HomePathResolver` raises when appdata is missing. The same pattern appears a third time in
   `input_file_handler.py:70-71` (dev DIAL, intentional).
3. **Three caches of external bytes.** `FileLoaderService` (`StateHolder` plus an in-flight map),
   `WebContentFetcher.__fetched_by_url` (`web_content_fetcher.py:36`) and `DialFilePromoter.__cache`
   (declared at `dial_file_promoter.py:44`, written at `:52`, a task per URL whose result is the uploaded file's metadata). `ExternalUrlFetcher` has
   no cache. One external URL can be fetched up to three times in a request: via a `file:` prefix, via `web_fetch`,
   and via promotion (deployment attachment or interpreter input).

**Already consolidated (do not redo)**

- Every write goes through `DialFileService.write_bytes` / `write_file` → `FileStorage.upload`: `AttachmentService`
  (MCP and REST output files, offloads, promoted external files, interpreter display content), `web_fetch`
  `save_path`, the file tools. `AttachmentService` is a thin layer that owns naming and the two roots; the old
  "combine `DialFileService` and `AttachmentService`" TODO is gone.
- `InputFileHandler` (`input_file_handler.py:69-77`) calls the SDK directly, but uploads to the *dev* DIAL, a different
  server with its own bucket. Intentional.

## Context: the Core universal file API

Core is preparing an additive file API for the files of complex resources (`skills`, `projects`) in the `/v1` space. The
Core spec is **not final** and the API has not shipped, so everything below is an assumption to re-check against the
released API. The direction is settled: Core extends `/v1`. Its earlier option of a separate `/v2/files/{group}/...`
family with segment-free logical URLs was rejected by Core (alternatives H and I of its design), because the server
would have to walk up the path to find the resource root and links stored in the segment form would become ambiguous.
What the current Core draft says:

- **Routes.** `GET` / `PUT` / `DELETE` on `/v1/{skills|projects}/{bucket}/{resource}/files/{filePath}` and
  `GET /v1/metadata/{skills|projects}/{bucket}/{resource}/files/{filePath}`. Copy and move are the existing
  `POST /v1/ops/resource/copy` and `/move` (body `{sourceUrl, destinationUrl, overwrite}`), extended to file URLs. The
  routes for plain files (`/v1/files`, `/v1/metadata/files`) and the `/v2/{group}/...` routes stay unchanged, with no
  deprecation in this change. Only the single-file shape is routed: a resource root, a grouping folder and the bucket
  root have no `/v1` route, and `GET`, `PUT` and `DELETE` of a folder inside a resource are `400` (a folder is listed
  through the metadata route).
- **Address.** The request path is `/v1/` followed by the **existing DIAL URL with the reserved `files` segment**:
  `skills/{bucket}/team/my-skill/files/refs/a.md`, `projects/{bucket}/{project}/files/artifacts/x.md`. The first
  `files` segment after the bucket separates the resource root from the file path, as on the `/v2/{group}` routes; the
  server does not search for the root. A file path may itself hold a folder named `files`. This is also the URL form
  that chat attachments, sharing and publications already use, so a stored link works with no conversion and no
  fallback.
- **ETag.** Per file for every group (`GET`, `PUT`, `DELETE`, `If-Match`, `If-None-Match`). The aggregate resource ETag
  is exposed as `X-Resource-ETag`. Two writers editing different files of one resource do not conflict on `If-Match`
  (their commits are still serialized by the resource lock).
- **Write.** `PUT` takes `multipart/form-data` with one file part, as `PUT /v1/files` does (a request without a valid
  multipart `Content-Type` is `400`). It returns `200` with the metadata of the written file, the new file `ETag` and
  `X-Resource-ETag`. A complex group is written only into an existing resource: without a marker `PUT` is a `404` that
  points to the whole-resource API (creating a project or a skill stays on the whole-resource route). A write is
  validated by the type handler (`validateFileMutation`), and a delete that breaks the resource (for example
  `SKILL.md`) is rejected (`409` or `422`, not decided).
- **Metadata.** `url` is the DIAL URL in the segment form. Query parameters `token`, `limit`, `recursive` and
  `permissions`, as in `/v1/metadata/files`; `permissions` is evaluated on the resource root, so every item of a listing
  carries the resource's permissions. A file carries `etag` (the file's), `contentLength`, `contentType` and an
  optional `resource: {url, etag}` for the owning root. Folders inside a resource are listed in the `/v1/metadata/files`
  folder shape (whether that shape carries sizes is not stated). Resources and grouping folders are still listed on
  `/v2/metadata/{group}/...`.
- **Authorization.** Checked at the **resource root** with the existing access checks; per-file sharing inside a
  complex resource is explicitly rejected. A caller who can read a project can read every file in it.
  `.dial-resource`, `.dial-folder` and `v/` paths are hidden (404).
- **Copy and move.** `POST /v1/ops/resource/copy` and `/move` copy and move **single files** inside a group and across
  groups: `files` ↔ `skills`, `files` ↔ `projects`, `skills` ↔ `projects`. Both sides name a file; a folder or a resource
  root on either side is `400`, and so is a whole resource mixed with a file. A complex destination must already be an
  existing resource (copy and move never create one: `404` otherwise). The type handler validates every complex side
  that changes, so a file copied from plain storage into a skill is checked like any write, and a move that would delete
  `SKILL.md` is rejected before anything is written. `overwrite` defaults to `false`, and an existing destination is then
  `409` (to be confirmed). A move inside one resource is one new version (a rename, atomic). A move between resources or
  groups is not atomic (the destination commits first), so a failure leaves a duplicate and never loses the file; the
  client can retry with `overwrite: true`. The response is `200` with an empty body, as the ops return today.
- **Rollout.** Pods of the previous Core release answer `404` on the new routes and fail the extended ops during a
  rolling deploy, so a client must not use them until the rollout finishes. The Core draft says a client may also fall
  back to the `/v2` routes on failure; this design does not (see "Migration to the unified API", point 1).

What it does to the questions this design answers:

| Question | After the unified API |
|---|---|
| Which client / API reads or writes this URL (v1, `ProjectFilesClient`, skills reader) | Disappears: the request path is `/v1/` plus the URL for every group, so one storage over `/v1` serves them. `RoutedFileStorage`, `FileSource` and the hand-written project client collapse into one backend. The SDK `files` client rejects `projects/` and `skills/` URLs today (aidial-client 0.19.0 validates the resource type), so M1 does not use it for these groups. It calls `/v1/` plus the URL through the HTTP client of `AsyncDial`, as `ProjectFilesClient` does today, and does not wait for an SDK change (another developer's). |
| Which consumers can read a project or skill file (C4) | Mostly disappears: a consumer that reads by DIAL URL through `/v1` reads them too, once the Core release is rolled out and the consumer's client does not reject the prefix (to verify per consumer). `V1ReadPolicy` stays until then. |
| Metadata (size, type, ETag) of a file | Disappears as a workaround: `GET /v1/metadata/{group}/...` replaces the header-only GET of `ProjectFileStorage` (Core ignores `Range` on a project file). |
| Concurrent writes, create-only outputs | Solved by the per-file ETag: no non-atomic project upload, collision-safe output names (I#725) become possible. |
| Server-side copy and move | Works inside a group and across groups, including a project and personal files (`files` ↔ `projects`). Our download and upload (`_transfer.py`) is replaced for single files. Still ours: creating the destination project (the destination must exist) and folders (`400`). |
| DIAL URL or external URL | Stays (`classify`). |
| Is the path allowed in this request (current project vs foreign, `context/` vs `artifacts/`, skills read-only) | Stays. Core authorizes at the resource root, so confinement is ours (D4, D8). |
| How a model path (relative, appdata-relative, `skill://`) becomes a DIAL URL; where outputs go | Stays. It is a product decision. |
| A link stored in old history (`.../files/...`) | Disappears as a problem: the segment form is the only form, so a stored link is a request path after `/v1/`, with no conversion and no fallback. |
| Granting an external consumer access to a file | Stays ours, and gets coarser: a grant on a project or a skill file is a grant on the whole resource. |

So `FileLayout` is the part that survives the migration, and the backend-routing part is what the migration removes.
This decides the delivery order below: the layout first, the storage-routing step only if the unified API is late.

## Design Goals

- `PROJECT_CONTEXT` is read in exactly one provider; every other class gets the right collaborator through DI and
  contains no `if project` and no `projects/` / `files/` literals.
- All roots (home, output, appdata) and all path rules (classification, read/write resolution, display form,
  root-escape guard) have one owner.
- C4 is expressed in code: a consumer asks "can v1 read this URL?", it does not test a prefix.
- Every file operation goes through `FileStorage`; no consumer calls the v1 client or `ProjectFilesClient` for
  project-or-not routing.
- One DIAL download path, with the "store metadata next to the bytes" invariant written once.
- One request-scoped cache of external bytes shared by the `file:` loader, `web_fetch` and the promoter.
- No behaviour change in the refactor. Before the first code move, every file-transfer case is covered by an
  integration test against a real Core (Delivery, track 0); those tests are the yardstick for "nothing broke", with
  the unit matrix (B1) and per-step tests on top.

## Proposed Design

### `FileLayout` (new, `shared/file_layout/`)

One DI-provided abstraction answers every "where / what kind of path" question. Decision D-2: the interface is
implemented by one class, `DialFileLayout`, that holds the project decision inside. A single `@provider` (request scope)
is the only reader of `PROJECT_CONTEXT` for this concern and passes it to the class:

```python
class DialPathKind(StrEnum):
    HOME_RELATIVE = "home_relative"      # report.md
    FILES = "files"                      # files/{bucket}/...
    CURRENT_PROJECT = "current_project"  # projects/{b}/{p}/files/... of this request's project
    FOREIGN_PROJECT = "foreign_project"  # any other projects/... URL (also every one outside a project)
    SKILL = "skill"                      # skills/{bucket}/{name}/files/...: read-only for the agent


class FileLayout(ABC):
    async def home_root(self) -> str                       # tools' working folder
    async def output_url(self, filename: str) -> str       # user-facing outputs; raises on an unsafe name
    async def appdata_url(self, filename: str) -> str      # internal files (offloads, promoted URLs)
    def classify(self, path: str) -> DialPathKind          # the single definition of a DIAL path
    async def resolve_read(self, path: str) -> str         # absolute canonical URL; rejects FOREIGN_PROJECT
    async def resolve_write(self, path: str) -> str        # relative paths only, under home_root
    async def to_display_path(self, url: str) -> str       # inverse, for the model and stage titles
```

| Mode inside `DialFileLayout` | Chosen when | home / output | appdata |
|---|---|---|---|
| standalone | `PROJECT_CONTEXT is None` | `files/{appdata}/{agent_home_dir}` / appdata root | appdata root |
| project | project present | `artifacts/` / `artifacts/` | appdata root |

Outside a project, `classify` returns `FOREIGN_PROJECT` for every `projects/` URL. This matches the storage today:
`RoutedFileStorage._route` refuses any `projects/` URL that is not the request's project (and every one without a
project) with a 403, "current project only". The consumers that bypass the storage (promoter, input handler) send such a
URL to the v1 client, where the SDK rejects it (`InvalidDialURLError`); `AttachmentResolver` has its own `projects/`
branch. Each keeps its current
outcome, and the B1 matrix pins it.

Rules that keep the single class cheap to split later (D-2):

- Consumers type against the `FileLayout` interface, never against `DialFileLayout`. The interface stays even while
  there is one implementation.
- The project decision lives inside the layout and does not leak out. The state comes from one field set in the
  constructor, and a public method has at most one branch point on it. Private helpers do not re-test it.
- If the project mode grows enough to make the class hard to read (for example the `context/` and `artifacts/` rules
  together with the current-project root checks), split it into `StandaloneFileLayout` and `ProjectFileLayout`
  behind the same provider. Consumers and their tests do not change, and the B1 matrix pins the behaviour across the
  split.

`SKILL` URLs are readable and never writable: `resolve_write` rejects them in both modes. The `skill://`
reference stays a boundary pre-step (skills package: `build_skill_file_url` in `skills/skill_file_url.py`); the layout only classifies the resulting
`skills/...` URL. Today a `skills/...` URL that comes from the model, not through `skill://` or a file source, classifies
as `dial_appdir_relative`, so a consumer that resolves it would put it under the agent home. The `SKILL` kind changes
that on purpose: B3a either keeps today's result for the consumers it has not moved yet, or calls the change out in its
PR (the B1 matrix pins the starting point). Who owns the "grant target" of a URL (the resource root for a skill or project file, the file itself
for `files/`) is an open question below.

**`V1ReadPolicy` (decision D-6).** C4 ("can the v1 client read this URL?") is a question about the reader, not about the
path, so it is not on the layout. A small DI service in `shared/file_layout/` answers it from the layout's
classification:

```python
class V1ReadPolicy:
    def can_read(self, kind: DialPathKind) -> bool         # C4: False for CURRENT_PROJECT and FOREIGN_PROJECT
```

A consumer asks `policy.can_read(layout.classify(url))`; the policy does not depend on the layout. It holds the one C4
rule today, and the B1 matrix pins what it returns for `SKILL`. Lifting C4 is a change in this class only. M4 replaces
it with an explicit per-consumer capability setting, then deletes it.

**Canonical URL form.** The code holds a project or skill file as `projects/{b}/{p}/files/...` and
`skills/{b}/{name}/files/...` (`canonical_url`, `ProjectContext.contains`, `artifacts_root`, `build_skill_file_url`). This is
the one form of the DIAL URL, the one the old routes return, the one chat attachments, sharing and publications use,
and, since Core extends `/v1`, the one the unified API takes (`/v1/` plus the URL). There is no second form to convert
to, so the unified API does not change what the layout emits. The layout is still the single place that owns the form,
because today the `/files/` segment is spread over `canonical_url`, `ProjectContext`, `artifacts_root`,
`build_skill_file_url` and several consumers: it hands out one canonical URL and one answer to "where is the resource root".
Decision D-3 (revised): the segment form is the only canonical form, and no URL conversion exists in the layout.

What the layout owns about the form:

- **The resource root.** For a project or skill URL the root is the part before the first `files` segment after the
  bucket (`files` is a reserved name, so no folder or resource can be called that). The layout never decides by
  pattern that a `files/` belongs to the file path: a resource may hold a folder named `files`
  (`skills/{b}/{name}/files/files/x`), and the first segment still splits root and path. The B1 matrix pins this.
- **The current project.** The root `projects/{b}/{p}` is known from `ProjectContext`. The project tree is
  `PROJECT.md`, `context/`, `conversations/`, `artifacts/` (D2). Foreign projects are rejected (`FOREIGN_PROJECT`).
- **Skills.** URLs we build (`build_skill_file_url`, the `skill://` reference) carry a known bucket and skill name. A
  `skills/...` URL that arrives from outside (typed by the model, taken from history) is classified as `SKILL` and
  passed through as it is. Skills are not writable (`SKILL`).
- **Stored links.** A link in old chat history, in an attachment or in a tool result is in this form already, and is
  read with no conversion. The layout needs no tolerant-input mode.

`HomePathResolver` is the nearest existing thing and is folded into the layout (its caching of the resolved home and the
`my_appdata_home()` call move with it; decision D-5: it is deleted with `shared/home_path/` once its last consumer moves,
and the layout lives in `shared/file_layout/`). Pure URL syntax (`canonical_url`, `has_unsafe_segments`) stays in
`common/`; the layout is its only caller outside tests.

### `FileStorage` gets `metadata(url)` (conditional, Delivery track C)

Today `DialFilePromoter` calls `dial_client.files.get_metadata` directly (`dial_file_promoter.py:62`), and the project
side has a module function `project_file_metadata`, not a `ProjectFilesClient` method. Instead,
`FileStorage.metadata(url)` is added (v1: `files.get_metadata`; project: a header-only GET). `RoutedFileStorage` stays the
only router. The promoter, the attachment resolver and the interpreter input handler stop touching the v1 client or the
project client for DIAL URLs.

The `metadata(url)` method itself survives the unified API (`GET /v1/metadata/{group}/...` returns content length,
content type and the per-file ETag, and it is the same route family as `files.get_metadata`); only the project
implementation (the header-only GET) and `RoutedFileStorage` are throw-away. The project half of this step is the first
candidate to skip: once Core ships, the v1 metadata call may serve a `projects/` URL as it is.

### Delivering a file to an external consumer: by value or by link

An MCP toolset receives a file either by value (`file:base64::`, `file:text::`, `file:data::`: QuickApps loads the bytes
and sends them) or by link (a `dial_url` parameter: QuickApps grants the toolset access and passes the URL, the server
downloads it). Core authorizes at the resource root and rejects per-file sharing, so a link to a file of a project or a
skill is a grant on the whole resource (for a project: `context/`, `conversations/`, `PROJECT.md` and every other
artifact). The D4 and D8 confinement does not constrain an external consumer. For skills the grant is already on the skill root (the skill
bundle is the unit that is meant to be shared). Once Core ships `/v1` for complex resources, a consumer that downloads
by DIAL URL through `/v1` can read such a link with the same code as a plain file, so a link to a project file becomes
useful to external consumers (this lifts C4 for them); the grant question below does not change.

Decision D-4 (a stop-gap): a project file reaches a `dial_url` parameter by link, and the intended grant is on the
`artifacts/` folder of the current project, not on the project root (the first bullet below says what is likely to
happen instead). Only files under `artifacts/` of the current project are
delivered this way. Any other project path (`context/`, `conversations/`, `PROJECT.md`, a foreign project) is rejected
for a `dial_url` parameter with an explicit error. By-value delivery (`file:` prefixes) is unchanged.

- **Likely outcome: a grant on the whole project.** The Core draft authorizes at the resource root only, and the repo
  already records two refusals to grant inside a complex resource: `_MCPTool._grant_resource` maps a skill file to its
  skill root because Core cannot grant a single skill file, and `projects.md` notes that Core refuses to share a single
  project file downstream. Expect the grant on the whole project resource until consent ships, and ask the Core team to
  confirm. The confinement stays ours either way: only `artifacts/` files of the current project are accepted for
  `dial_url`, whatever the scope of the grant. B6 does not wait for the answer, and the PR states which grant scope it
  uses.
- **A consumer can read the file only after the Core `/v1` release.** Until then C4 holds: the grant exists, but the
  consumer's `/v1` call for a `projects/` URL is not served. D-4 rules (what is accepted and rejected) can ship earlier;
  the link becomes useful only behind the Core gate.
- **Temporary.** Core is adding consent for the files and resources of toolsets, given by an admin or a user when the
  toolset is configured. When it ships, QuickApps stops granting, and this logic is replaced by showing the consent.
  Reopen D-4 then.

### Consumers after the refactor

| Consumer | Asks the layout | No longer knows |
|---|---|---|
| file tools, path-argument transformer | `resolve_read`, `resolve_write`, `to_display_path` | `PROJECT_CONTEXT`, prefixes |
| `AttachmentService` | `output_url`, `appdata_url` | `PROJECT_CONTEXT`, `contains` |
| `DialFilePromoter`, `AttachmentResolver`, `InputFileHandler` | `classify`, `V1ReadPolicy.can_read` | `PROJECT_CONTEXT` and `startswith("projects/")` (resolver), direct v1 metadata calls |
| `get_content` tool, keep policy, materializer | `classify` | `PROJECT_CONTEXT`, `startswith("files/")`, `is_dial_storage_path` |
| `_MCPTool` (`dial_url` parameters), skill file source | `classify`, `resolve_read` | appdir-relative gap (TODO #445), `skill_root_of_file_url` import into `mcp_tooling` |

### Download: `DialFileService.download_file` is the only DIAL download-with-cache

- `FileLoaderService` calls `DialFileService.download_file` for DIAL URLs, and `DialDownloader` is deleted with its DI
  binding (`dial_core_services_module.py`) and tests. `FileLoaderService` keeps its in-flight map, scheme dispatch and
  content-type handling; it no longer stores the DIAL result itself, because `download_file` already did.
- The stored content type is `None` for a DIAL URL today and stays so, so `load_with_content_type` resolves it exactly
  as before (stored value, then file name, then the default).
- The "metadata is stored with the bytes" invariant, and its comment, live in `download_file` only.
- No new import direction: `shared/file_transfer` already imports `dial_core_services` (`DialDownloader`), as do
  `shared/home_path`, `shared/user_access` and `shared/project`. `dial_core_services` does not import
  `shared/file_transfer` (checked by import search, direct imports only), so there is no cycle.

### External bytes: one cache inside `ExternalUrlFetcher`

- `ExternalUrlFetcher` is already request-scoped (`external_fetch_module.py:27`). `fetch(url)` gets an in-flight task
  map and a result map keyed by the requested URL, and returns the same `FetchedBytes` (data, content type, file name)
  to every caller.
- `WebContentFetcher` drops its own dict. `FileLoaderService` keeps writing the bytes to the `StateHolder`, and the
  promoter keeps its task map: its value is the *upload result*, not the bytes.
- Policy does not change: the SSRF guard, redirect cap and per-app switches run inside the first fetch, a cache hit
  returns what that fetch produced in the same request, and a failed fetch is not cached. The size limit, the timeout and
  the egress policy are resolved once per request by `ExternalUrlFetcher` itself (not per consumer), so a hit cannot
  return a result produced under a different policy.
- Callers wait on a shared in-flight task through `asyncio.shield`, so cancelling the caller that started the fetch does
  not cancel it for the others. A failed or cancelled task is removed from the map, so the next call retries.
- An external URL is fetched once per request instead of up to three times. The bytes are held in the fetcher's cache, and
  a `file:` load also keeps them in the `StateHolder` (the default, see the open question), so at most two copies.

### Appdata root

Owned by `FileLayout.appdata_url`; `AttachmentService._appdata_root` and `HomePathResolver` both use it. The one piece of
work specific to this item is deciding which Core call the layout makes (`my_appdata_home()` or `bucket.get_raw()`),
see the open questions.

### Guard against regression

An architecture test parses `src/quickapp` with `ast` (no such test exists in the repo yet) and fails when `PROJECT_CONTEXT`
is referenced, or a string constant appears that starts with `files/`, `projects/`, `skills/` or `metadata/files/`,
contains the `/files/` segment (also inside an f-string), or is a regex alternating the resource types
(`files|projects`), outside an allow-list. The last two forms matter because the form of the URL is built that way:
`ProjectContext` builds `f"{url}/files/"`, `build_skill_file_url` builds `.../files/...`, and `classify_url` and
`skill_root_of_file_url` match by regex. Docstrings and comments are not scanned, so they cannot cause false positives. The allow-list is one table in the test,
one line of reason per entry, and a failure names the file and the line. It holds: `common/project_context.py`, `common/url_classification.py` (until absorbed), the layout package, the
storage DI provider and `RoutedFileStorage`, the places that create `PROJECT_CONTEXT` (`AppModule` provider,
`_request_context.py`, `_request_context_setup.py`), and the genuinely project-only features (`ProjectModule`: prompt
provider, instructions, access preflight). The code survey of 2026-11-23 also found literals in
`skills/skill_file_url.py`, `config/dial_files.py`, `common/folder_context_urls.py` and `input_file_handler.py` (dev
DIAL); B7 decides for each whether it moves behind the layout or joins the allow-list. New code that needs the
decision has to take `FileLayout`.

## Delivery

Every step is its own small PR with no behaviour change, leaves the tree green (existing unit suites plus the
file-transfer integration suite from track 0) and can be shipped without the steps after it. Sizes: S is a few files,
M is a package.

Track 0 comes first and gates the rest. After it, tracks A and B do not depend on each other. The projects stack (up to
PR 4/5) and the skills branch are both merged into the working branch, so no PR below waits for either of them. Track A
needs only `FileStorage`; track B needs both, because the skills URLs and `FileSource` are part of what the layout
classifies. Track C is conditional.

### Track 0: file-transfer integration suite (before any refactor)

**Purpose.** Cover every way a file moves through QuickApps with integration tests against a real DIAL Core, so that
"no behaviour change" is checked by running them, not by reading a diff. The suite is the success criterion of every PR
below: a step may start only when the cases it touches are green on the unchanged tree, and it must keep them green.
This is the "Core-path integration suite" of the projects series (PR5), widened to all file-transfer cases and moved in
front of the refactor.

**Probe pattern.** The tests do not check business logic. They use tiny probe servers in the style of the #420 PoC
(`local_test_servers/mcp_skill_file_server.py`): a probe receives a file by one delivery mechanism and reports what
arrived (HTTP status, size, short sha256, content type, file name, a preview), nothing more. The test sends a fixture
of known bytes and asserts the report (for example `ToolCall(...).add_result_check(contains=<sha256>)`), so a pass means
"the bytes arrived intact through this path". For output paths a probe returns a known file, and the test reads the
resulting file back from Core and compares the hash and the folder (`artifacts/` or appdata).

| Probe | Mechanism it checks |
|---|---|
| `inspect_by_link` (MCP; parameter flagged `dial_url`) | The link plus the permission grant: downloads from Core with the forwarded credential and reports status, size, hash. Promoted from the #420 PoC |
| `inspect_by_value` (MCP and REST) | Content delivered by value for a `file:text::`, `file:base64::` or `file:data::` argument |
| `produce_file` (MCP non-text content block, REST `response_as_attachment`) | Output files: upload to the output root and the returned attachment |
| Stub deployment (exists: `test_runner/stub_deployment.py`) | Attachments passed to a DIAL deployment; the test fetches their metadata |
| Python interpreter (real, live; existing session marker) | Interpreter input staging and display output |

Probes live next to `data_server_for_tests.py` and are started by `make start_test_server`.

**Case groups.**

| Group | Cases | Probe |
|---|---|---|
| In-1 | `file:url / text / base64 / data::` x resource: own `files/` (also read by an absolute URL from a project chat), appdata-relative, a chat attachment, the project's `context/` and `artifacts/`, an external URL, a skill file | `inspect_by_value` |
| In-2 | MCP `dial_url` link and grant x resource: own file, project file, `skill://` skill file, appdata-relative (TODO #445: fails today, recorded as such) | `inspect_by_link` |
| In-3 | File tools: read, search, find on `files/` and in a project; write, edit (a stale ETag is rejected), copy, move, delete, list in the agent home and in `artifacts/` | read back from Core |
| In-4 | `get_content` and `web_fetch` (with `save_path`) x `files/`, appdata-relative, project, external | read back from Core |
| In-5 | Deployment attachment x `files/`, a project file (known C4 failure), an external URL with `url_attachments` on and off | stub deployment |
| In-6 | Interpreter input x `files/`, an external URL (promoted), a project file (known error) | interpreter |
| Out-1 | MCP output file, REST `response_as_attachment`, interpreter display content: appdata root outside a project, `artifacts/` inside one; the same name twice replaces the file (I#725) | `produce_file`, read back |
| Out-2 | A large tool result is offloaded to appdata, in a project as well | read back |
| Cp | Copy and move: inside the agent home, inside `artifacts/`, from a personal file into `artifacts/` and back (a download and an upload today, server-side through `/v1/ops/resource/copy` after the unified API, which allows `files` ↔ `projects`), `overwrite` on and off | read back from Core. The failed delete after the copy (`PartialMoveException`) needs fault injection on a real Core, so it stays a unit test of `_transfer.py` until M3 |
| Et | Per-file ETag semantics: `If-Match` on edit, `If-None-Match` on create-only, two writes to different files of one project. Today a project write is a plain PUT after a file-level check; the same cases must pass unchanged after the migration | read back from Core |
| Sk | `read_skill` of a bundled file; `skill://` delivered by content and by link | after the skills merge |
| Neg | Foreign project URL, `..` traversal, an oversized file, external fetch switched off, an unsupported scheme, an absolute `files/` or `projects/` write target (also in a project chat: the personal folder is not writable there, D4): the error the model sees, pinned by its class and a key substring, not by the full text. Also a resource that holds a real `files/` folder (`skills/{b}/{name}/files/files/x`: the first `files` splits the root), an internal path (`.dial-resource`, `v/`) and a folder as the target of a read or a write | tool result text |

Cases that fail today by design or because Core support is unverified (C4, links to `projects/` files, TODO #445)
are recorded with their current outcome and error class (plus a key substring) and marked as known, so a refactor cannot change them silently.
A case changes status only in the PR that intentionally changes the behaviour, and that PR updates the expectation.

**Which cases gate which step.**

| Step | Cases that must be green first |
|---|---|
| A1 download path | In-1, In-3 (the edit tool's `If-Match` depends on the stored metadata), In-4, Neg |
| A2 external cache | external rows of In-1, In-4, In-5, In-6 |
| A3 in-flight de-duplication | In-3 |
| B3 - B5b layout and literals | The outside-a-project cases of In-1 to In-4, Out-1, Out-2, Cp, Sk, Neg (T2, T3, T6) and the B1 matrix. The project variants (T4) are not required to start: until T4 is green, project behaviour is pinned by the B1 matrix only, and the PRs say so |
| B6 `dial_url` parameters | The above, and the In-2 project cases from T4: B6 changes the grant for a `projects/` URL on purpose, so it is not merged without a live Core check |
| B4 appdata root | Out-1, Out-2, In-3 (agent home) |
| C1 - C4 metadata through the storage | In-5, In-6, In-2 |
| M1 storage over the unified API | Every group, with Cp and Et as the cases that exercise what the new API changes (per-file ETag, copy and move) |

**PRs.**

| # | PR | Size | Depends on |
|---|---|---|---|
| T1 | Probe servers, fixtures with known bytes and hashes, the read-back helper, started by `make start_test_server` | M | none |
| T2 | In-1, In-3, In-4, Cp, Et outside a project (own `files/`, appdata, external) | M | T1 |
| T3 | Out-1, Out-2 outside a project, and Neg | S | T1 |
| T4 | The same groups inside a project (needs a Core with project support and a per-request key); known C4 and link cases recorded. This is PR5 of the projects series | M | T2, T3, Core release with project support |
| T5 | In-5 and In-6: deployment attachments and the interpreter | M | T1 |
| T6 | Sk, and `skill://` in In-1 and In-2 | S | T1 (skills branch merged) |

The suite needs a live Core. Decision D-7: it runs on the author's machine against a real Core, through the existing
proxy-based integration tests, and is not a CI gate. A PR that is gated on Track 0 (B3a to B6) states in its description
which groups were run and that they were green; the reviewer checks that statement. A nightly or docker-based job is
possible later and is not part of this design.

### Track A: I/O seams

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| A1 | `FileLoaderService` uses `DialFileService.download_file` for DIAL URLs; delete `DialDownloader` (class, DI binding, `test_dial_downloader.py`; the tests that mock it are in `test_file_loader_service.py`, `test_skill_file_reference_wiring.py` and `test_async_dial_http_calls.py`) | S | none (projects stack merged) | A `FileLoaderService` test that a DIAL load stores the metadata, so the edit tool's `If-Match` still has an ETag |
| A2 | Request-scoped fetch cache (in-flight map plus results) inside `ExternalUrlFetcher`; `WebContentFetcher` drops its dict | S | none | Two consumers of one URL cause one HTTP fetch; a failed fetch is retried; cancelling the first caller does not fail the second; SSRF and size-limit tests unchanged |
| A3 | In-flight de-duplication in `DialFileService.download_file` | S | A1 | Two concurrent downloads of one file hit Core once. Only if the open question below answers yes |

### Track B: the layout

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| B1a - B1d | **Pin behaviour.** A parametrised unit matrix: consumer x (project / no project) x (relative / `files/` / current `projects/` / foreign `projects/` / `skills/` / host-matched absolute `/v1/projects/`; no normaliser for the last one exists, so the matrix only records what each consumer does with it). Records today's results, including the known C4 failures, a resource with a real `files/` folder, and two inconsistencies of today's classification: `classify_url` ignores case and a leading `/` (`Files/x` and `/files/x` are `DIAL`) while `is_dial_storage_path` and the `projects/` prefix checks do not, and a `skills/...` URL is `dial_appdir_relative`. Tests only. Split by consumer group, one PR each (size S to M): **B1a** `HomePathResolver` and `RoutedFileStorage` (gates B3), **B1b** `AttachmentService` (gates B4), **B1c** `AttachmentResolver`, `_GetContentTool`, keep policy, materializer, `DialFilePromoter`, `InputFileHandler`, `FileLoaderService` (gates B5), **B1d** `_MCPTool` and `_SkillFileSource` (gates B6) | S - M | none (both merged) | Itself |
| B2 | **Pin the appdata root.** Both calls hit `GET /v1/bucket` and agree on the value (code survey), so this is a test that pins the one real difference: `appdata or bucket` in `AttachmentService` against an error in `HomePathResolver` when appdata is missing. The result picks the rule `FileLayout` applies | S | none | The test itself |
| B3a | **Introduce `FileLayout`** (interface, `DialPathKind`, `DialFileLayout` with the standalone branch, `V1ReadPolicy`, provider) with `classify`, `home_root`, `resolve_read`, `resolve_write`, `to_display_path`; `HomePathResolver` delegates to it. Callers unchanged | M | B1a, B2 | B1 matrix, unchanged results |
| B3b | **Project branch** of `DialFileLayout` (the current-project root, `context/` and `artifacts/` rules, the resource root of a project or skill URL) | M | B3a | B1 matrix, unchanged results |
| B4 | **`AttachmentService`** switches to `output_url` / `appdata_url` and drops `PROJECT_CONTEXT`; `HomePathResolver` and `AttachmentService` use the same appdata call, so the appdata root has one owner | S | B3b, B1b | B1 matrix; the existing output-root tests |
| B5 | **Literals, group 1:** `get_content` tool (it also reads `PROJECT_CONTEXT`), keep policy, materializer, `AttachmentResolver` (`PROJECT_CONTEXT` and a `projects/` branch), `is_dial_storage_path`, the path-argument transformer take `classify` / `resolve_read`. One PR per consumer if the diff gets large | M | B3b, B1c | B1 matrix |
| B5b | **Literals, group 1b:** the file tools (`_base_file_tool` and the write, edit, delete, move, copy, read, search, list and find tools) and `web_fetch` `save_path` take `resolve_read` / `resolve_write` / `to_display_path` from `FileLayout`. They are the last consumers of `HomePathResolver`, so this PR deletes it and `shared/home_path/` (D-5) | M | B5, B1a | B1 matrix; the file-tool suites (`test_base_file_tool.py`, `test_project_file_flow.py`, `test_path_argument_transformer.py`) |
| B6 | **Literals, group 2:** `_MCPTool` `dial_url` parameters (also closes TODO #445) and the skill file source stop importing `skill_root_of_file_url` into `mcp_tooling` | S | B3b, B1d | B1 matrix plus the skills branch's MCP tests |
| B7 | **Architecture test** with the allow-list (see "Guard against regression") | S | B4, B5, B5b, B6 | Itself |

**Checkpoint after B4.** Track C is the only step that touches classes talking to a real Core outside the storage. Do it
if the unified API and its rollout are further away than Track C itself, or if lifting C4 (deployments and the
interpreter reading `projects/`) is needed first. Otherwise skip it and go straight to the migration below.

### Track C (conditional): metadata through the storage

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| C0 | Gate: T4, T5 and the In-2 cases are green and run in CI | n/a | T4, T5 | n/a |
| C1 | `FileStorage.metadata(url)`: v1 `files.get_metadata`, project via a header-only GET; `RoutedFileStorage` routes it | S | B4, C0 | New storage unit tests |
| C2 | `DialFilePromoter` uses `FileStorage.metadata` and `classify` / `V1ReadPolicy`; `ProjectFilesClient` leaves its constructor | S | C1 | B1 matrix, promoter tests |
| C3 | `AttachmentResolver` uses `FileStorage.metadata` instead of `metadata.get("files", ...)` | S | C1 | B1 matrix, resolver tests |
| C4 | `InputFileHandler` uses `classify` / `V1ReadPolicy` for the request DIAL side (the dev-DIAL upload stays as is) | S | C1 | B1 matrix, interpreter input tests |

With the unified API on the way, the project half of C1 (the header-only GET) is throw-away work: if the API ships before
this track starts, skip C1 to C4 for projects and take the `metadata` method straight from the migration (M1, M2).

Follow-ups this makes cheap: lifting C4 (change `V1ReadPolicy` in one place; the read path itself comes from Core's
`/v1` routes), collision-safe output names ([I#725](https://github.com/epam/ai-dial-quickapps-backend/issues/725): one
change in `output_url`).

## Migration to the unified API

The Core spec is not final, so this is the shape of the migration, not a step list to start.

**Core gate.** No step here, and no PR that targets the extended `/v1`, starts until both hold: Core has released the
`/v1` file API for complex resources, and that release is rolled out in every environment we run. Track 0 must also be
green on the old backend, and this document must be re-checked against the final Core design. The SDK is not a
condition: the calls go through our own client over `AsyncDial`'s HTTP client (M1). Until the gate opens, M1 to M4 stay
`blocked` (see "Core-gated work" in "Implementation slicing").

| # | Step | Size | Notes |
|---|---|---|---|
| M1 | One `FileStorage` over `/v1` for every group replaces `V1FileStorage`, `ProjectFileStorage` and `RoutedFileStorage`, behind an explicit setting. It takes the URL as it is (`/v1/` plus the URL) through a thin hand-written client over `AsyncDial`'s HTTP client, as `ProjectFilesClient` does today (no SDK change; switching to the SDK later is optional) | M | Waits for the Core release and rollout (see the Core gate), not for the SDK. Old and new backends coexist until M3; track 0 runs on both |
| M2 | `FileStorage.metadata`, `download`, `upload` use per-file ETags, the metadata endpoint and the `PUT` response body (metadata plus the new ETag, no follow-up call); the header-only GET goes; create-only outputs (I#725) | S | `If-None-Match: *` replaces the unconditional overwrite where the product wants it |
| M3 | Delete `ProjectFilesClient`, `RoutedFileStorage`, `V1FileStorage` / `ProjectFileStorage`, the skills `FileSource`, the download and upload part of `_transfer.py` (copy and move go to `/v1/ops/resource/copy` and `move`), and the setting | S | After the rollout of the Core release is complete everywhere we run |
| M4 | `V1ReadPolicy` answers `True` for project and skill URLs per consumer and is then deleted when every consumer is verified to read them through `/v1` | S | We cannot see a consumer's client, so the answer is explicit configuration until each consumer is checked |

Points that shape these steps:

1. **Explicit gate, not a 404 fallback.** Pods of the previous Core release answer `404` on the new routes, and a `404`
   is also an ordinary "file not found", so a client cannot fall back on it. The switch is a setting (or a Core version
   check at startup) that the operator turns on after the rollout. The Core draft suggests falling back to the `/v2`
   routes on failure; we do not, for the reason above.
2. **Copy and move go server-side, including across groups.** `POST /v1/ops/resource/copy` and `move` work inside a
   group and across groups, so a copy between personal files and a project is no longer our download and upload. What
   stays ours: a server-side copy or move needs the destination to be an existing resource, so it cannot create a
   project; `overwrite` defaults to `false` (an existing destination is `409`), so the file tools set it explicitly
   where they overwrite today; a folder as source or destination is `400`, so the file tools' folder cases are checked
   (the projects design copies single files only); a move across resources or groups is not atomic. The failure shape
   of that move is the same as our `PartialMoveException` (a duplicate, never a lost file), so the error mapping keeps
   its meaning. The response has an empty body, so a caller that needs the destination metadata asks for it.
3. **Per-file ETag changes edit and upload semantics for projects**, so Et cases in track 0 are the acceptance of M2:
   `If-Match` on edit, create-only outputs, two writers of different files.
4. **Delivery to external consumers.** The grants for MCP `dial_url` parameters stay ours and, for a project or a
   skill, become grants on the resource (see "by value or by link" and D-4: for a project, the `artifacts/` folder).
   Core's consent feature is expected to take these grants over. `url_attachments` is a model capability, not an API
   one, and does not change. What does change: a link to a project file can be read by a consumer through `/v1`, once
   its client accepts the prefix (M4).
5. **New error shapes to map:** `404` on a write without a resource marker (a project that does not exist), `409` /
   `422` on a delete rejected by the type's `validateFileMutation` (to check: whether deleting the last file of a
   project is rejected, since the project handler accepts only a non-empty file tree), `400` on a folder or a resource
   root as the target (also on `GET`, `PUT` and `DELETE` of a folder inside a resource), `404` on `.dial-resource`,
   `.dial-folder` and `v/` paths, `409` on an existing destination of a copy with `overwrite` off, `404` on a copy or
   move whose destination is not an existing resource, `400` on a whole resource mixed with a file URL in the ops.
6. **Stored links need no handling.** A link in history is in the segment form and is a request path after `/v1/`, so
   there is no conversion step, no fallback and no second form to test. The Neg cases of track 0 pin the one edge that
   remains: a resource that holds a real `files/` folder.
7. **Cost.** A complex-group request reads the marker once at the root given by the path (cached by Core), with no
   walk up the path. A single-file write on a complex resource has the cost of Core's single-file write, which commits a
   new version under the resource lock and copies the files of the current one natively, so it grows with the number of
   files in the resource. `artifacts/` is written often (every tool output), so this is the number to measure in the
   same track 0 run, together with the latency of a read and a write against the `/v2` route.

## Alternatives Considered

- **Two `FileLayout` implementations (standalone and project) chosen by the provider.** Rejected for now (D-2).
  Polymorphism wins only if the two modes keep diverging (a third mode, per-chat subfolders); with today's two modes it
  is more ceremony for one decision. The unified API makes the two modes converge (one backend for both), so the single
  class leaves less to throw away. The split stays cheap if the rules in "`FileLayout`" are kept.
- **Only route everything through `FileStorage`, no layout.** Closes the v1 bypass but leaves roots and prefixes
  scattered. Necessary (track C) but not sufficient.
- **Docs + test matrix only.** B1 alone. Cheap and worth doing regardless, but it documents the spread instead of
  removing it.
- **Fold `AttachmentService` into `DialFileService`.** Rejected: the old TODO is gone, and the split (naming and roots
  versus ETag semantics) is reasonable.

## Out of Scope

- Lifting C4 and collision-safe output names (follow-ups above).
- The dev-DIAL upload in `InputFileHandler`: a different server by design.
- Business logic and model behaviour in the track 0 tests: the probes check that bytes and metadata arrive, not what an
  agent does with them.
- Changing the project semantics decided in `projects.md` (D3-D8).
- Moving `ProjectModule` features (prompt provider, access preflight) onto the layout: they are project-only by
  design and stay gated by `@preview_module`.

## Open Questions

- Should a host-matched absolute URL (`https://{DIAL host}/v1/projects/...`) be accepted at all? No normaliser for it
  exists in the tree: `to_relative_project_url` lived only in intermediate commits of PR#727 and was dropped before the
  merge, in favour of classifying `projects/` by prefix. Today `classify_url` calls such a URL `DIAL`, while the prefix
  checks (`RoutedFileStorage`, `AttachmentResolver`, `_GetContentTool`, `ProjectContext.contains`) do not recognise it. The
  only pre-step is stripping a leading `/` (`normalize_attachment_url_argument`). Decide in B3a: keep rejecting it (the
  layout classifies by prefix only and the B1 matrix pins the outcome), or add a pre-step at the boundary that strips the
  host and `/v1/`. It does not belong in `classify` either way.
- Who owns the grant target of a URL (the resource root for `skills/...` and `projects/...`, the file for `files/...`):
  the layout, or a separate grants component next to `DialFileService.grant_permissions_to_files`?
- Can Core grant on the `artifacts/` folder of a project alone (D-4)? Ask the Core team. If not, the grant is on the
  whole project resource until consent ships; B6 does not wait for the answer.
- Does each consumer that reads by DIAL URL (adapter-dial, RAG, the code interpreter, the MCP servers we know) accept
  the `projects/` and `skills/` prefixes through `/v1`? It decides when `V1ReadPolicy` can answer `True` for them (M4).
  The SDK itself rejects both prefixes in aidial-client 0.19.0; that does not block M1, which uses its own client.
- Unified API, still open in the Core spec: the error codes (`409` or `422` on a rejected delete, internal paths, no
  resource root on `PUT`, a whole resource mixed with a file URL in the ops); the default of `overwrite` (`false` and
  `409`, to be confirmed); whether folder listings carry sizes; the rejection of deleting the last file of a project;
  error bodies we have to map. Answered by the current draft: Core extends `/v1` and the URL keeps its `files` segment
  (no second form, no legacy fallback), `PUT` is multipart and returns the metadata, access is granted at the resource
  root only (no per-file grants), the destination of a copy or move must already be a resource, and copy and move work
  across groups (`files` ↔ `projects` ↔ `skills`) with an empty response body.
- Unified API, timeline: when does Core ship it, and do we have to support a Core without it? The answer sets the
  checkpoint after B4 and whether M1 needs a setting at all.
- Where does the skills `FileSource` end up in the meantime: kept as is, or folded into `FileStorage` routing? With
  `/v1` serving `skills/.../files/...`, it can fold into the storage at M1 (the skills reader on `/v2/skills` stays for
  `SKILL.md` and listings).
- Does `DialFileService.download_file` need in-flight de-duplication (A3)? The code says concurrent downloads of one
  file are possible: `tool_executor.py:106` runs the tool calls of one turn with `asyncio.gather`, so two reads of one
  URL both miss the cache. The harm is small, because the GETs are idempotent. Default: skip A3 unless a real case shows up.
- Appdata root: `my_appdata_home()` and `bucket.get_raw()` call the same endpoint (`GET /v1/bucket`), so they agree on
  the value (see the duplicated list). What is open is only the fallback: `appdata or bucket` in `AttachmentService`
  against an error in `HomePathResolver`. B2 shrinks to a test that pins the difference, and the layout picks one rule.
- Should the `StateHolder` entry for an external URL stay once `ExternalUrlFetcher` caches (A2)? It is harmless, so the
  default is to keep it.
- Track 0, how a test drives a tool deterministically: through the live orchestrator and an `add_result_check` on the
  probe's report (nondeterministic model, repeat runs), or through a hook-called hidden tool as `test_hidden_from_model.py`
  does (deterministic, but skips the model-facing path)? The default: hook-driven for the transport cases, the
  orchestrator only where the model-facing shape (`skill://`, relative paths) is the thing under test.
- Track 0, how a test reads a file back from Core and with which credential, given that access to a project is granted
  at the resource root (D7).

## Implementation slicing

This section is the entry point for a new session: read it, pick a PR id, do only that PR, then update its status here.
The sections above give the reasoning; this one gives the work. Everything in waves 1 to 3 is independent of the Core
unified API. Only track M (see "Migration to the unified API") waits for it, and is not started: see "Core-gated work"
below.

**Rules for every PR**
- No behaviour change. Known failures (C4, links to `projects/` files, TODO #445) keep failing the same way and are pinned
  by a test, not fixed.
- After the code: `make format`, then `make lint`. `make test` only when asked. Stage new files with `git add`; commit
  and push only when asked.
- The branch and base for each PR are chosen by the owner at the start of the PR.
- Find symbols by name, not by line number (lines drift).
- Status values: `todo`, `in progress`, `done` (add the PR link), `blocked` (name the blocker).

**Gate for waves 1 and 3 (proposal, to confirm).** The track 0 rule "a step starts only when its integration cases are
green" is relaxed: A1, A2, B1 and B2 go under unit tests (their "Pinned by" column), and track 0 (T1 to T3, T6) must be
green before B3a starts. B3b, B4 and B5 do not wait for T4 (blocked on PR#729 and a Core release with project support):
project behaviour is pinned by the B1 matrix alone until then, and each of those PRs says so. T4 is a condition for
merging B6 and for releasing the layout. If the owner prefers the strict rule, wave 2 moves in front of A1 and A2.

### Wave 1: no decisions needed, PRs are independent

| ID | What | Touches | Tests | Status |
|---|---|---|---|---|
| A1 | `FileLoaderService.__load_dial` calls `DialFileService.download_file`; delete `DialDownloader`. The "metadata is stored next to the bytes" comment moves into `download_file`. Keep the stored content type `None` for DIAL URLs. Note: `download_file` logs an ERROR with `exc_info` on any failure, which `FileLoaderService` did not; decide whether that is acceptable noise | `shared/file_transfer/_file_loader_service.py`, `dial_core_services/dial_downloader.py` (delete), `dial_core_services/dial_core_services_module.py` (binding), `dial_file_service.py` | Delete `test_dial_downloader.py`. Update `test_file_loader_service.py`, `test_skill_file_reference_wiring.py`, `test_async_dial_http_calls.py`. New: a DIAL load stores the metadata (ETag) | todo |
| A2 | In-flight map plus result map keyed by the requested URL inside `ExternalUrlFetcher.fetch`; `WebContentFetcher` drops `__fetched_by_url`. The promoter keeps its task map (its value is the upload result). SSRF guard, redirect cap and per-app switches run inside the first fetch; a failed fetch is not cached | `shared/external_fetch/external_url_fetcher.py`, `WebContentFetcher` (find by name) | `test_external_url_fetcher.py`, `test_web_fetch_tool.py`. New: two consumers of one URL cause one HTTP fetch; a failed fetch is retried; cancelling the first caller does not fail the second | todo |
| B1a - B1d | Parametrised unit matrix, tests only, one PR per consumer group (the groups are in the B1 row of "Track B"). Axes: consumer x (project / no project) x path kind (relative, `files/`, current `projects/`, foreign `projects/`, `skills/`, host-matched absolute `/v1/projects/`; no normaliser for it exists, record what each consumer does). Consumers: `HomePathResolver` (the file tools, the argument transformer), `AttachmentService`, `RoutedFileStorage`, `AttachmentResolver`, `_GetContentTool`, keep policy, materializer, `DialFilePromoter`, `InputFileHandler`, `_MCPTool._collect_dial_url_files`, `FileLoaderService`, `_SkillFileSource`. Record today's results, including the known C4 failures, a resource with a real `files/` folder, the case and leading-`/` mismatch between `classify_url` and `is_dial_storage_path`, the `skills/` URL classified as `dial_appdir_relative`, and the fact that `_MCPTool` passes a `projects/` URL through `_validate_dial_file` to the grant as is, with no current-project check | new test module(s) next to the consumers | Extend `test_home_path_resolver.py`, `test_file_storage_wiring.py`, `test_project_file_flow.py`, `test_attachment_resolver.py`, `test_get_content_tool.py`, `test_dial_file_promoter.py` | todo |
| B2 | Test that pins the appdata fallback difference (see the B2 row above) | `AttachmentService`, `HomePathResolver` tests | New test | todo |
| T1 | Probe servers (`inspect_by_link`, `inspect_by_value`, `produce_file`), fixtures with known bytes and hashes, the read-back helper. Extension points: `src/tests/integration_tests/data_server_for_tests.py` (REST on `:8002`, MCP on `:8003` via `test_runner/mcp_server/mcp_http_test_server.py`), `test_runner/stub_deployment.py` (a stub response only today, no file probes), `make start_test_server`. `local_test_servers/mcp_skill_file_server.py` (untracked, the #420 PoC, `fetch_skill_file`, port 8007) is the base of `inspect_by_link` | `src/tests/integration_tests/` | The probes are exercised by T2 onwards | todo |

### Wave 2: integration suite (needs a live Core), after T1

| ID | What | Blocked by | Status |
|---|---|---|---|
| T2 | In-1, In-3, In-4, Cp, Et outside a project | T1 | todo |
| T3 | Out-1, Out-2 outside a project, and Neg | T1 | todo |
| T5 | In-5 (deployment attachments) and In-6 (interpreter) | T1 | todo |
| T6 | Sk, and `skill://` in In-1 and In-2 | T1 | todo |
| T4 | The same groups inside a project, known C4 and link cases recorded (PR 5/5 of the projects series) | T2, T3, PR#729, a Core release with project support | blocked |

### Wave 3: the layout, after the decisions below and after T1 to T3

Decisions to take first (see Open Questions):
- **D-1** (decided) Writing to the personal folder from a project chat stays impossible: write tools take relative paths
  only, and in a project the home is `artifacts/` (D4). Reading it by an absolute `files/` URL keeps working.
  `resolve_write` does not change.
- **D-2** (decided) One `DialFileLayout` class with the project decision inside, behind the `FileLayout` interface. The
  rules that keep a later split into two classes cheap are in "`FileLayout`".
- **D-3** (decided, revised after Core chose `/v1`) Canonical URL form: the segment form
  (`projects/{b}/{p}/files/...`) is the only form. The layout owns it (the resource root, the current project), and no
  conversion to a logical form exists.
- **D-5** (decided) `HomePathResolver` is removed, not kept as a facade: B3a makes it delegate to the layout, and B5b
  (the PR that moves its last consumer onto `FileLayout`) deletes it and `shared/home_path/`. The layout lives in the new
  `shared/file_layout/` package.
- **D-6** (decided) C4 ("can the v1 client read this URL?") lives in a separate `V1ReadPolicy` service next to the layout,
  not on `FileLayout`. It takes a `DialPathKind` and is replaced by a per-consumer capability setting in M4.
- **D-7** (decided) Track 0 runs locally against a real Core (the existing proxy-based integration tests), not in CI. A
  gated PR states in its description which groups ran green.
- **D-4** (decided, a stop-gap until Core consent) A project file reaches a `dial_url` parameter by link, with a grant on
  the `artifacts/` folder of the current project only; other project paths are rejected for `dial_url`. Core most likely
  cannot grant on a folder, so expect the grant on the whole project until consent ships (see "by value or by link").
- Builder call, settle in the PR: who owns the grant target.

| ID | What | Touches | Depends on | Status |
|---|---|---|---|---|
| B3a | `FileLayout` interface, `DialPathKind`, `DialFileLayout` with the standalone branch, `V1ReadPolicy` (D-6), the provider; `HomePathResolver` (bound in `shared/home_path/home_path_module.py`, request scope) delegates. `PROJECT_CONTEXT` is still created in `AppModule` and `_request_context`; the layout provider is its only reader for this concern | new `shared/file_layout/`, `shared/home_path/` | B1a, B2, T1 to T3, T6 | todo |
| B3b | The project branch of `DialFileLayout`: the current-project root, `context/` and `artifacts/` rules, the resource root of a project or skill URL (see "Canonical URL form") | `shared/file_layout/`, `common/project_context.py` | B3a | todo |
| B4 | `AttachmentService` uses `output_url` / `appdata_url` and drops `PROJECT_CONTEXT`; one appdata rule | `dial_core_services/attachment_service.py` | B3b, B1b | todo |
| B5 | Literals, group 1 (see the B5 row above). One PR per consumer if large | `_get_content_tool.py`, keep policy, materializer, `_attachment_resolver.py`, `url_classification.py`, the argument transformer | B3b, B1c | todo |
| B5b | The file tools and `web_fetch` `save_path` move onto `FileLayout`; deletes `HomePathResolver` and `shared/home_path/` (D-5). Without this PR nothing owns that deletion | `dial_files_tooling/` (`_base_file_tool.py` and the tools), `web_tooling/_web_fetch_tool.py`, `shared/home_path/` (delete) | B5, B1a | todo |
| B6 | `_MCPTool` `dial_url` parameters (closes TODO #445); the skill file source stops importing `skill_root_of_file_url` into `mcp_tooling`. The current pass-through of a `projects/` URL to the grant changes here: a deliberate behaviour change, call it out in the PR | `mcp_tooling/_mcp_tool.py`, `skills/skill_file_url.py` | B3b, B1d | todo |
| B7 | Architecture test with the allow-list from "Guard against regression" | new test | B4, B5, B5b, B6 | todo |

### Core-gated work (do not start)

Moving a consumer from today's backends (`V1FileStorage`, `ProjectFileStorage`, `RoutedFileStorage`,
`ProjectFilesClient`, the skills `FileSource`, `_transfer.py`) to the extended `/v1` waits for two things, both at once:
Core has released the `/v1` file API for complex resources, and that release is rolled out in every environment we run.
The final Core design must also be re-checked first (note at the top of this document). The SDK is not a condition: M1
uses its own client, as `ProjectFilesClient` does today.

| ID | What | Blocked by | Status |
|---|---|---|---|
| M1 | One `FileStorage` over `/v1` for every group, behind a setting | Core release and rollout | blocked |
| M2 | Per-file ETags, metadata endpoint, `PUT` response body; create-only outputs (I#725) | M1 | blocked |
| M3 | Delete the old storages, `ProjectFilesClient`, the skills `FileSource`, the download and upload part of `_transfer.py`, and the setting | M2, rollout complete everywhere | blocked |
| M4 | `V1ReadPolicy` answers `True` per consumer, then is deleted | M1, per-consumer check | blocked |

While these are blocked:
- Do not file M1 to M4 as issues or branches, and do not write code that targets the new routes, not even behind a
  setting.
- A PR from waves 1 to 3 must not rely on the new routes, on the per-file ETag of project files, on `X-Resource-ETag`, or
  on server-side cross-group copy and move. Track 0 cases that Core changes (Cp across groups, Et per-file ETag, reading
  a project link by a consumer) are recorded with today's outcome, and change status in the M PR that switches the
  backend.
- T4 and B6 keep their own gate (a Core release with project support, listed above). Meeting it does not open this one.
- The project half of C1 stays throw-away work: if Core ships before track C starts, skip C1 to C4 for projects.

### Conditional and not sliced yet

- **A3** (de-duplication in `download_file`): skip unless a real case shows up (see Open Questions).
- **Checkpoint after B4**, then **C0 to C4**: C2 to C4 now have to start from the real code (the promoter calls
  `dial_client.files.get_metadata` directly, there is no `ProjectFilesClient.file_metadata`). Rewrite them at the
  checkpoint.
- **M1 to M4**: see "Core-gated work" above.

### Log

Add one line per finished PR: id, date, link, anything that changed the plan.
