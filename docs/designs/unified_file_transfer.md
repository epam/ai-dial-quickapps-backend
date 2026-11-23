# Design: Unified file transfer

- **Status:** Draft. Code references verified against branch `chore/file_transfer_refactoring` on 2026-11-23. The projects stack up to PR 4/5 ([PR#727](https://github.com/epam/ai-dial-quickapps-backend/pull/727)) and `feat/420-skill-script-transfer` are in that tree; PR 5/5 ([PR#729](https://github.com/epam/ai-dial-quickapps-backend/pull/729)) is not. The work is sliced in "Implementation slicing" at the end of this document, which is the entry point for a new session.
- **Issue:** TBD
- **Related:** [`projects.md`](projects.md) (D3-D8, C4), [I#725](https://github.com/epam/ai-dial-quickapps-backend/issues/725) (output name collisions)

Code references are to the `chore/file_transfer_refactoring` tree (projects stack up to PR 4/5, skills branch merged,
`file_transfer/` now in `shared/file_transfer/`). Line numbers drift: find a symbol by name first.

> **Before this draft becomes the final design:** everything this document says about the Core unified file API comes
> from a Core draft (`design/universal_file_api.md`), which is itself not final. The document must be re-checked
> against the **final** version of that Core design before it leaves draft. Walk through "Context: the Core unified
> file API", "Migration to the unified API" and the Core-related open questions, and update at least: the route
> shapes and the logical URL form (the `/files/` segment), the ETag and `PUT` response semantics, the authorization
> model (resource root only) and what it means for grants to external consumers, the copy and move rules, the error
> codes, the rollout and compatibility behaviour, and whether folder listings carry sizes. Any decision here that
> rests on a point the final Core design changes (for example the by-value default for project files, the canonical
> URL form, skipping C1 to C4) is to be reopened, not carried over.

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
- `_MCPTool` leaves appdir-relative `dial_url` paths unresolved (TODO #445), because it has no access to the path rules.

Consequences:

- The write root is chosen twice (`HomePathResolver.resolve_home_dir`, `AttachmentService.upload_output_bytes`), the
  escape-from-root guard twice (`has_unsafe_segments` + `_validate_relative_path` vs `contains`).
- The "project files can't reach v1 consumers" limitation (C4) is a doc note, not code. `DialFilePromoter`,
  `AttachmentResolver` and `InputFileHandler` call the v1 client directly, bypassing `FileStorage`. Only
  `AttachmentResolver` has its own `projects/` branch; the promoter and the input handler have none, so a project URL
  reaches the v1 client and fails at runtime against a real Core (B1 pins the exact behaviour). A new consumer that
  forgets the check fails the same way.
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

## Context: the Core unified file API

Core is preparing an additive unified file API. The Core spec is **not final** and the API has not shipped (expected in
weeks; the SDK method and consumer adoption come after it), so everything below is an assumption to re-check against the
released API. What the current Core draft says:

- **Routes.** `GET` / `PUT` / `DELETE` on `/v2/files/{group}/{bucket}/{path...}`, `GET /v2/metadata/files/...`, and
  `POST /v2/ops/files/copy` and `/move` (body `{sourceUrl, destinationUrl, overwrite}`), for the groups `files`,
  `skills` and `projects`. The old routes (`/v1/files`, `/v2/{group}/.../files/...`) stay unchanged, with no deprecation
  in this change.
- **Address.** The tail is the **logical DIAL URL**, without the reserved `/files/` segment of the old complex-resource
  routes: `skills/{bucket}/team/my-skill/refs/a.md`, `projects/{bucket}/{project}/artifacts/x.md`. The server finds the
  resource root by walking up to the nearest `.dial-resource` marker; the client does not need to know where it is.
  This is also the URL form that chat attachments, sharing and publications already use.
- **ETag.** Per file for every group (`GET`, `PUT`, `DELETE`, `If-Match`, `If-None-Match`). The aggregate resource ETag
  is exposed as `X-Resource-ETag`. Two writers editing different files of one resource do not conflict.
- **Write.** `PUT` returns the file metadata and the new ETag (proposed, to be confirmed). A complex group is written only
  into an existing resource: without a marker `PUT` is a 404 that points to the whole-resource API.
- **Metadata.** `url` is the logical URL, files in a complex resource carry an optional `resource: {url, etag}`, content
  length and content type are present; folder listings reuse the existing shape (whether they carry sizes is not
  stated).
- **Authorization.** Checked at the **resource root** with the existing access checks; per-file sharing inside a
  complex resource is explicitly rejected. A caller who can read a project can read every file in it.
  `.dial-resource`, `.dial-folder` and `v/` paths are hidden (404).
- **Copy and move.** Same group only. Allowed: plain to plain, a file to a file in the same resource, a file to a file
  in another existing resource of the same group. Complex to plain, plain to complex, and `skills` to `projects` are
  `400`. A move between two resources is not atomic (the destination commits first), so a failure leaves a duplicate
  and never loses the file.
- **Rollout.** Pods of the previous Core release answer `404` on the new routes during a rolling deploy, so a client
  must not use them until the rollout finishes.

What it does to the questions this design answers:

| Question | After the unified API |
|---|---|
| Which client / API reads or writes this URL (v1, `ProjectFilesClient`, skills reader) | Disappears: one storage over `/v2/files` for every group. `RoutedFileStorage`, `FileSource` and the hand-written project client collapse into one backend. We do not have to wait for the SDK for this: `ProjectFilesClient` is hand-written anyway. |
| Metadata (size, type, ETag) of a file | Disappears as a workaround: the metadata endpoint replaces the ranged GET of `ProjectFileStorage`. |
| Concurrent writes, create-only outputs | Solved by the per-file ETag: no non-atomic project upload, collision-safe output names (I#725) become possible. |
| Server-side copy and move | Only inside one group and one resource, or between resources of one group. Between a project and personal files it stays our download and upload. |
| DIAL URL or external URL | Stays (`classify`). |
| Is the path allowed in this request (current project vs foreign, `context/` vs `artifacts/`, skills read-only) | Stays. Core authorizes at the resource root, so confinement is ours (D4, D8). |
| How a model path (relative, appdata-relative, `skill://`) becomes a logical URL; where outputs go | Stays. It is a product decision. |
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

One DI-provided abstraction answers every "where / what kind of path" question. Two implementations, chosen by a single
`@provider` (request scope) that is the only reader of `PROJECT_CONTEXT` for this concern:

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
    def v1_readable(self, url: str) -> bool                # C4: False for a project URL
```

| Implementation | Chosen when | home / output | appdata | `v1_readable(project URL)` |
|---|---|---|---|---|
| `StandaloneFileLayout` | `PROJECT_CONTEXT is None` | `files/{appdata}/{agent_home_dir}` / appdata root | appdata root | n/a (`classify` returns `FOREIGN_PROJECT`) |
| `ProjectFileLayout` | project present | `artifacts/` / `artifacts/` | appdata root | `False` |

`SKILL` URLs are readable and never writable: `resolve_write` rejects them in both implementations. The `skill://`
reference stays a boundary pre-step (skills package: `skill_file_url`); the layout only classifies the resulting
`skills/...` URL. Who owns the "grant target" of a URL (the resource root for a skill or project file, the file itself
for `files/`) is an open question below.

**Canonical URL form.** Today the code holds a project or skill file as `projects/{b}/{p}/files/...` and
`skills/{b}/{name}/files/...`, the form of the old complex-resource routes (`canonical_url`, `ProjectContext.contains`,
`artifacts_root`, `skill_file_url`). The unified API addresses the same file by the logical URL without `/files/`, and
that is the form the rest of DIAL (attachments, sharing, publications) uses. The layout is therefore the single place
that owns the form: it hands out one canonical URL, and the `/files/` segment becomes a private detail of the legacy
`ProjectFileStorage` / `ProjectFilesClient`, added when a request goes through the old route and removed with them.
Whether the layout switches to the logical form during track B or only at the migration is an open question; the
default is to isolate the legacy form behind the layout in B3 and switch at the migration.

**The two forms are ambiguous.** The old complex-resource routes return `projects/{b}/{p}/files/artifacts/x.md`, where
`files/` separates the resource root from the file path. The unified API reads the same string as a resource whose own
tree has a folder named `files`. Neither Core nor a client holding only the string can tell the two apart, so a legacy
URL passed to the new API can silently address a different file when such a folder exists. The legacy form does not go
away: the old routes keep returning it, and old chats hold it in their history, in attachments and in tool results. So
the conversion is ours, it happens at one place (the layout) and only where the origin of the path is known:

- **Current project.** The root `projects/{b}/{p}` is known from `ProjectContext`. The project tree is `PROJECT.md`,
  `context/`, `conversations/`, `artifacts/` (D2), so `files/` right after the known root is the legacy separator. The
  layout strips it. Foreign projects are rejected (`FOREIGN_PROJECT`), so there is nothing to guess for them.
- **Skills.** URLs we build (`skill_file_url`, the `skill://` reference) carry a known bucket and skill name, so we emit
  the right form directly. A `skills/...` URL that arrives from outside (typed by the model, taken from history) has no
  known origin: the layout converts it only when the skill is known to the registry, and otherwise leaves it as it is. It
  never strips `files/` by pattern alone, because a skill may bundle a real `files/` folder.
- **Input stays tolerant.** `resolve_read` accepts both forms for as long as old history exists, which is longer than the
  migration: M4 changes what the layout emits, it does not stop it accepting the old form.

`HomePathResolver` is the nearest existing thing and is folded into the layout (its caching of the resolved home and the
`my_appdata_home()` call move with it). Pure URL syntax (`canonical_url`, `has_unsafe_segments`,
`to_relative_project_url`) stays in `common/`; the layout is its only caller outside tests.

### `FileStorage` gets `metadata(url)` (conditional, Delivery track C)

Today `DialFilePromoter` calls `dial_client.files.get_metadata` directly (`dial_file_promoter.py:62`), and the project
side has a module function `project_file_metadata`, not a `ProjectFilesClient` method. Instead,
`FileStorage.metadata(url)` is added (v1: `files.get_metadata`; project: the ranged GET). `RoutedFileStorage` stays the
only router. The promoter, the attachment resolver and the interpreter input handler stop touching the v1 client or the
project client for DIAL URLs.

The `metadata(url)` method itself survives the unified API (it has a metadata endpoint, with content length, content
type and the per-file ETag); only the project implementation (the ranged GET) and `RoutedFileStorage` are throw-away.
Since the endpoint is expected within weeks, the project half of this step is the first candidate to skip.

### Delivering a file to an external consumer: by value or by link

An MCP toolset receives a file either by value (`file:base64::`, `file:text::`, `file:data::`: QuickApps loads the bytes
and sends them) or by link (a `dial_url` parameter: QuickApps grants the toolset access and passes the URL, the server
downloads it). Core authorizes at the resource root and rejects per-file sharing, so a link to a file of a project or a
skill is a grant on the whole resource (for a project: `context/`, `conversations/`, `PROJECT.md` and every other
artifact). The D4 and D8 confinement does not constrain an external consumer. Proposal, to be decided before B6:
project files go to external consumers by value by default, and a link with a root grant is an explicit opt-in per
toolset. For skills the grant is already on the skill root (the skill bundle is the unit that is meant to be shared).

### Consumers after the refactor

| Consumer | Asks the layout | No longer knows |
|---|---|---|
| file tools, path-argument transformer | `resolve_read`, `resolve_write`, `to_display_path` | `PROJECT_CONTEXT`, prefixes |
| `AttachmentService` | `output_url`, `appdata_url` | `PROJECT_CONTEXT`, `contains` |
| `DialFilePromoter`, `AttachmentResolver`, `InputFileHandler` | `classify`, `v1_readable` | `PROJECT_CONTEXT` and `startswith("projects/")` (resolver), direct v1 metadata calls |
| `get_content` tool, keep policy, materializer | `classify` | `PROJECT_CONTEXT`, `startswith("files/")`, `is_dial_storage_path` |
| `_MCPTool` (`dial_url` parameters), skill file source | `classify`, `resolve_read` | appdir-relative gap (TODO #445), `skill_file_url` imports into `mcp_tooling` |

### Download: `DialFileService.download_file` is the only DIAL download-with-cache

- `FileLoaderService` calls `DialFileService.download_file` for DIAL URLs, and `DialDownloader` is deleted with its DI
  binding (`dial_core_services_module.py`) and tests. `FileLoaderService` keeps its in-flight map, scheme dispatch and
  content-type handling; it no longer stores the DIAL result itself, because `download_file` already did.
- The stored content type is `None` for a DIAL URL today and stays so, so `load_with_content_type` resolves it exactly
  as before (stored value, then file name, then the default).
- The "metadata is stored with the bytes" invariant, and its comment, live in `download_file` only.

### External bytes: one cache inside `ExternalUrlFetcher`

- `ExternalUrlFetcher` is already request-scoped (`external_fetch_module.py:27`). `fetch(url)` gets an in-flight task
  map and a result map keyed by the requested URL, and returns the same `FetchedBytes` (data, content type, file name)
  to every caller.
- `WebContentFetcher` drops its own dict. `FileLoaderService` keeps writing the bytes to the `StateHolder`, and the
  promoter keeps its task map: its value is the *upload result*, not the bytes.
- Policy does not change: the SSRF guard, redirect cap and per-app switches run inside the first fetch, a cache hit
  returns what that fetch produced in the same request, and a failed fetch is not cached. The same bytes are held once
  per request instead of up to three times.

### Appdata root

Owned by `FileLayout.appdata_url`; `AttachmentService._appdata_root` and `HomePathResolver` both use it. The one piece of
work specific to this item is deciding which Core call the layout makes (`my_appdata_home()` or `bucket.get_raw()`),
see the open questions.

### Guard against regression

An architecture test fails when `PROJECT_CONTEXT` or the literals `"files/"` / `"projects/"` / `"skills/"` appear outside an
allow-list: `common/project_context.py`, `common/url_classification.py` (until absorbed), the layout package, the
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

Track 0 comes first and gates the rest. After it, tracks A and B do not depend on each other. Track A needs only
`FileStorage`, which the projects stack already introduced, so it can start as soon as that stack is merged and the
cases it needs are green; it does not wait for the skills branch. Track B needs both the projects stack and the skills
branch merged (the skills URLs and `FileSource` are part of what the layout classifies). Track C is conditional.

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
| Cp | Copy and move: inside the agent home, inside `artifacts/`, from a personal file into `artifacts/` and back (a download and an upload today, and still after the unified API: Core rejects complex to plain), `overwrite` on and off, a failed delete after the copy (`PartialMoveException`) | read back from Core |
| Et | Per-file ETag semantics: `If-Match` on edit, `If-None-Match` on create-only, two writes to different files of one project. Today a project write is a plain PUT after a file-level check; the same cases must pass unchanged after the migration | read back from Core |
| Sk | `read_skill` of a bundled file; `skill://` delivered by content and by link | after the skills merge |
| Neg | Foreign project URL, `..` traversal, an oversized file, external fetch switched off, an unsupported scheme, an absolute `files/` or `projects/` write target (also in a project chat: the personal folder is not writable there, D4): the exact error the model sees. Also the two URL forms: the same file in the legacy (`.../files/artifacts/x`) and the logical (`.../artifacts/x`) form, and a skill that bundles a real `files/` folder | tool result text |

Cases that fail today by design or because Core support is unverified (C4, links to `projects/` files, TODO #445)
are recorded with their current outcome and error text and marked as known, so a refactor cannot change them silently.
A case changes status only in the PR that intentionally changes the behaviour, and that PR updates the expectation.

**Which cases gate which step.**

| Step | Cases that must be green first |
|---|---|
| A1 download path | In-1, In-3 (the edit tool's `If-Match` depends on the stored metadata), In-4, Neg |
| A2 external cache | external rows of In-1, In-4, In-5, In-6 |
| A3 in-flight de-duplication | In-3 |
| B3 - B6 layout and literals | In-1 to In-4, Out-1, Out-2, Cp, Sk, Neg |
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
| T6 | Sk, and `skill://` in In-1 and In-2 | S | T1, skills merged |

The suite needs a live Core, so it follows the existing integration workflow (manual in CI, not a PR gate; see the
open questions).

### Track A: I/O seams

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| A1 | `FileLoaderService` uses `DialFileService.download_file` for DIAL URLs; delete `DialDownloader` (class, DI binding, `test_dial_downloader.py`; the tests that mock it are in `test_file_loader_service.py`, `test_skill_file_reference_wiring.py` and `test_async_dial_http_calls.py`) | S | projects stack | A `FileLoaderService` test that a DIAL load stores the metadata, so the edit tool's `If-Match` still has an ETag |
| A2 | Request-scoped fetch cache (in-flight map plus results) inside `ExternalUrlFetcher`; `WebContentFetcher` drops its dict | S | none | Two consumers of one URL cause one HTTP fetch; a failed fetch is retried; SSRF and size-limit tests unchanged |
| A3 | In-flight de-duplication in `DialFileService.download_file` | S | A1 | Two concurrent downloads of one file hit Core once. Only if the open question below answers yes |

### Track B: the layout

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| B1 | **Pin behaviour.** A parametrised unit matrix: consumer x (project / no project) x (relative / `files/` / current `projects/` / foreign `projects/` / `skills/` / host-matched absolute `/v1/projects/`) x (legacy `/files/` form / logical form). Records today's results, including the known C4 failures, and the skill with a real `files/` folder. Tests only | M | both merged | Itself |
| B2 | **Pin the appdata root.** Both calls hit `GET /v1/bucket` and agree on the value (code survey), so this is a test that pins the one real difference: `appdata or bucket` in `AttachmentService` against an error in `HomePathResolver` when appdata is missing. The result picks the rule `FileLayout` applies | S | none | The test itself |
| B3 | **Introduce `FileLayout`** (interface, the chosen implementation shape, provider) with `classify`, `home_root`, `resolve_read`, `resolve_write`, `to_display_path`; `HomePathResolver` delegates to it. Callers unchanged | M | B1, B2 | B1 matrix, unchanged results |
| B4 | **`AttachmentService`** switches to `output_url` / `appdata_url` and drops `PROJECT_CONTEXT`; `HomePathResolver` and `AttachmentService` use the same appdata call, so the appdata root has one owner | S | B3 | B1 matrix; the existing output-root tests |
| B5 | **Literals, group 1:** `get_content` tool (it also reads `PROJECT_CONTEXT`), keep policy, materializer, `AttachmentResolver` (`PROJECT_CONTEXT` and a `projects/` branch), `is_dial_storage_path`, the path-argument transformer take `classify` / `resolve_read`. One PR per consumer if the diff gets large | M | B3 | B1 matrix |
| B6 | **Literals, group 2:** `_MCPTool` `dial_url` parameters (also closes TODO #445) and the skill file source stop importing `skill_file_url` into `mcp_tooling` | S | B3, skills merged | B1 matrix plus the skills branch's MCP tests |
| B7 | **Architecture test** with the allow-list (see "Guard against regression") | S | B4, B5, B6 | Itself |

**Checkpoint after B4.** Track C is the only step that touches classes talking to a real Core outside the storage. Do it
if the unified API and its SDK method are further away than Track C itself, or if lifting C4 (deployments and the
interpreter reading `projects/`) is needed first. Otherwise skip it and go straight to the migration below.

### Track C (conditional): metadata through the storage

| # | PR | Size | Depends on | Pinned by |
|---|---|---|---|---|
| C0 | Gate: T4, T5 and the In-2 cases are green and run in CI | n/a | T4, T5 | n/a |
| C1 | `FileStorage.metadata(url)`: v1 `files.get_metadata`, project via the ranged GET; `RoutedFileStorage` routes it | S | B4, C0 | New storage unit tests |
| C2 | `DialFilePromoter` uses `FileStorage.metadata` and `classify` / `v1_readable`; `ProjectFilesClient` leaves its constructor | S | C1 | B1 matrix, promoter tests |
| C3 | `AttachmentResolver` uses `FileStorage.metadata` instead of `metadata.get("files", ...)` | S | C1 | B1 matrix, resolver tests |
| C4 | `InputFileHandler` uses `classify` / `v1_readable` for the request DIAL side (the dev-DIAL upload stays as is) | S | C1 | B1 matrix, interpreter input tests |

With the unified API on the way, the project half of C1 (the ranged GET) is throw-away work: if the API ships before
this track starts, skip C1 to C4 for projects and take the `metadata` method straight from the migration (M1, M2).

Follow-ups this makes cheap: lifting C4 (flip `v1_readable` and add a v2 read path in one place), collision-safe output
names ([I#725](https://github.com/epam/ai-dial-quickapps-backend/issues/725): one change in `output_url`).

## Migration to the unified API

The Core spec is not final, so this is the shape of the migration, not a step list to start. It begins once the API is
released and track 0 is green on the old backend.

| # | Step | Size | Notes |
|---|---|---|---|
| M1 | One `FileStorage` over `/v2/files` (hand-written, like `ProjectFilesClient`) replaces `V1FileStorage`, `ProjectFileStorage` and `RoutedFileStorage`, behind an explicit setting | M | Does not wait for the SDK. Old and new backends coexist until M3; track 0 runs on both |
| M2 | `FileStorage.metadata`, `download`, `upload` use per-file ETags and the metadata endpoint; the ranged GET goes; create-only outputs (I#725) | S | `If-None-Match: *` replaces the unconditional overwrite where the product wants it |
| M3 | Delete `ProjectFilesClient`, `RoutedFileStorage`, `V1FileStorage` / `ProjectFileStorage` (as far as v1 consumers allow), the skills `FileSource`, and the setting | S | After the rollout of the Core release is complete everywhere we run |
| M4 | The layout switches its canonical form to the logical URL (no `/files/`) | S | Only if not already done in B3; `skill_file_url` and `ProjectContext` follow |
| M5 | `v1_readable` becomes a capability flag on the consumer, then is deleted when every consumer is past the version with the new SDK method | S | We cannot see a consumer's SDK version, so the flag is explicit configuration |

Points that shape these steps:

1. **Explicit gate, not a 404 fallback.** Pods of the previous Core release answer `404` on the new routes, and a `404`
   is also an ordinary "file not found", so a client cannot fall back on it. The switch is a setting (or a Core version
   check at startup) that the operator turns on after the rollout.
2. **Copy and move stay ours across the boundary.** Server-side copy and move work only inside a group (a file to a
   file in the same or another resource of that group). A copy between personal files and a project is complex to
   plain: `400`. So `_transfer.py` (download, upload, `PartialMoveException`) stays for that case and the server-side
   ops replace it only for plain to plain and project to project. The non-atomic cross-resource move of Core has the
   same failure shape as ours (a duplicate, never a lost file).
3. **Per-file ETag changes edit and upload semantics for projects**, so Et cases in track 0 are the acceptance of M2:
   `If-Match` on edit, create-only outputs, two writers of different files.
4. **Delivery to external consumers.** The grants for MCP `dial_url` parameters stay ours and, for a project or a
   skill, become grants on the whole resource (see "by value or by link"). `url_attachments` is a model capability,
   not an API one, and does not change.
5. **New error shapes to map:** `404` on a write without a resource marker (a project that does not exist), `409` /
   `422` on a delete rejected by the type's `validateFileMutation` (to check: whether deleting the last file of a
   project is rejected, since the project handler accepts only a non-empty file tree), `400` on a folder or a resource
   root as the target, `409` on an existing destination of a copy with `overwrite` off.
6. **Cost.** A complex-group request does up to one marker read per path segment above the file (cached by Core);
   `artifacts/` paths are shallow, so this is expected to be small. Measure in the same track 0 run.

## Alternatives Considered

- **One `FileLayout` class with the single `if project is None` inside.** Less ceremony, still one place for the
  decision. Polymorphism wins only if the two modes keep diverging (a third mode, per-chat subfolders); with today's
  two modes this is a legitimate lighter choice. To settle in review. The unified API makes the two modes converge
  (one backend for both), which favours this lighter variant and leaves less to throw away.
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

- Does `HomePathResolver` survive as a thin facade for tool-argument concerns, or is it removed outright?
- Does the host-matched absolute-URL normalisation (`to_relative_project_url`, needs `DIAL_URL`) belong in
  `classify`, or stay a pre-step at the boundary (tool argument parsing)?
- Name and package: `shared/file_layout/` next to `shared/home_path/`, or inside `dial_core_services/`?
- Who owns the grant target of a URL (the resource root for `skills/...` and `projects/...`, the file for `files/...`):
  the layout, or a separate grants component next to `DialFileService.grant_permissions_to_files`?
- Project files to external consumers: by value by default with an opt-in link per toolset (the proposal above), or
  always by link with a root grant? Decide before B6.
- Writing to the personal folder from a project chat: today impossible by design (D4: write tools take relative paths
  only, and in a project the home is `artifacts/`); reading it by an absolute `files/` URL works. Keep, or allow an
  explicit target? An explicit target changes `FileLayout.resolve_write` and must be decided before B3. Server-side copy
  does not help here: Core rejects complex to plain.
- Canonical URL form: does the layout switch to the logical URL (no `/files/`) in B3 or at the migration (M4)? The
  default is to isolate the legacy form behind the layout in B3.
- Legacy versus logical URL ambiguity (see "The two forms are ambiguous"): `projects/.../files/x` and `skills/.../files/x`
  mean different files in the old and the new form, and Core cannot tell them apart. Is "convert only where the root is
  known (current project, registered skill), never by pattern" enough, or do we also ask the Core team to reject the
  ambiguous case (for example a `files` folder directly under a resource root)? And how long does the layout keep
  accepting the legacy form, given that old chat history holds it?
- Unified API, still open in the Core spec: the body of `PUT` (metadata, proposed) and raw bytes versus multipart; the
  error codes (`409` or `422` on a rejected delete, unsupported group, internal paths); the route and default
  `overwrite` of copy and move; whether folder listings carry sizes; the rejection of deleting the last file of a
  project; error bodies we have to map. Answered by the current draft: the logical URL has no `/files/` segment, and
  access is granted at the resource root only (no per-file grants).
- Unified API, timeline: when do Core and the SDK method ship, and do we have to support a Core without it? The answer
  sets the checkpoint after B4 and whether M1 needs a setting at all.
- Where does the skills `FileSource` end up in the meantime: kept as is, or folded into `FileStorage` routing?
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
- Track 0, where it runs: the existing integration workflow is manual and needs a live Core. As the refactor's yardstick
  it should run on every refactor PR; options are a manual run per PR, a nightly run, or a job against a Core in
  docker (`docker_compose_files/`). Which of them, and is a Core with project support available there (series PR5 waits
  for the Core release)?
- Track 0, how a test reads a file back from Core and with which credential, given that access to a project is granted
  at the resource root (D7).

## Implementation slicing

This section is the entry point for a new session: read it, pick a PR id, do only that PR, then update its status here.
The sections above give the reasoning; this one gives the work. Everything in waves 1 to 3 is independent of the Core
unified API. Only track M (see "Migration to the unified API") waits for it, and is not sliced yet. The SDK-side
alternative to that API is explored separately in [`sdk_level_file_resolution.md`](sdk_level_file_resolution.md).

**Rules for every PR**
- No behaviour change. Known failures (C4, links to `projects/` files, TODO #445) keep failing the same way and are pinned
  by a test, not fixed.
- After the code: `make format`, then `make lint`. `make test` only when asked. Stage new files with `git add`; commit
  and push only when asked.
- The branch and base for each PR are chosen by the owner at the start of the PR.
- Find symbols by name, not by line number (lines drift).
- Status values: `todo`, `in progress`, `done` (add the PR link), `blocked` (name the blocker).

**Gate for waves 1 and 3 (proposal, to confirm).** The track 0 rule "a step starts only when its integration cases are
green" is relaxed: A1, A2, B1 and B2 go under unit tests (their "Pinned by" column), and track 0 (T1 to T3) must be green
before B3 starts. If the owner prefers the strict rule, wave 2 moves in front of A1 and A2.

### Wave 1: no decisions needed, PRs are independent

| ID | What | Touches | Tests | Status |
|---|---|---|---|---|
| A1 | `FileLoaderService.__load_dial` calls `DialFileService.download_file`; delete `DialDownloader`. The "metadata is stored next to the bytes" comment moves into `download_file`. Keep the stored content type `None` for DIAL URLs. Note: `download_file` logs an ERROR with `exc_info` on any failure, which `FileLoaderService` did not; decide whether that is acceptable noise | `shared/file_transfer/_file_loader_service.py`, `dial_core_services/dial_downloader.py` (delete), `dial_core_services/dial_core_services_module.py` (binding), `dial_file_service.py` | Delete `test_dial_downloader.py`. Update `test_file_loader_service.py`, `test_skill_file_reference_wiring.py`, `test_async_dial_http_calls.py`. New: a DIAL load stores the metadata (ETag) | todo |
| A2 | In-flight map plus result map keyed by the requested URL inside `ExternalUrlFetcher.fetch`; `WebContentFetcher` drops `__fetched_by_url`. The promoter keeps its task map (its value is the upload result). SSRF guard, redirect cap and per-app switches run inside the first fetch; a failed fetch is not cached | `shared/external_fetch/external_url_fetcher.py`, `WebContentFetcher` (find by name) | `test_external_url_fetcher.py`, `test_web_fetch_tool.py`. New: two consumers of one URL cause one HTTP fetch; a failed fetch is retried | todo |
| B1 | Parametrised unit matrix, tests only. Axes: consumer x (project / no project) x path kind (relative, `files/`, current `projects/`, foreign `projects/`, `skills/`, host-matched absolute `/v1/projects/`) x (legacy `/files/` form / logical form). Consumers: `HomePathResolver` (the file tools, the argument transformer), `AttachmentService`, `RoutedFileStorage`, `AttachmentResolver`, `_GetContentTool`, keep policy, materializer, `DialFilePromoter`, `InputFileHandler`, `_MCPTool._collect_dial_url_files`, `FileLoaderService`, `_SkillFileSource`. Record today's results, including the known C4 failures, a skill with a real `files/` folder, and the fact that `_MCPTool` passes a `projects/` URL through `_validate_dial_file` to the grant as is, with no current-project check | new test module(s) next to the consumers | Extend `test_home_path_resolver.py`, `test_file_storage_wiring.py`, `test_project_file_flow.py`, `test_attachment_resolver.py`, `test_get_content_tool.py`, `test_dial_file_promoter.py` | todo |
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
- **D-1** Writing to the personal folder from a project chat (changes `resolve_write`): before B3.
- **D-2** One `FileLayout` class with a single `if project` or two implementations: before B3.
- **D-3** Canonical URL form: the default (isolate the legacy form behind the layout in B3, switch at M4) holds unless changed.
- **D-4** Project files to external consumers, by value or by link: before B6.
- Builder calls, settle in the PR: the fate of `HomePathResolver`, the package (`shared/file_layout/`), who owns the grant target.

| ID | What | Touches | Depends on | Status |
|---|---|---|---|---|
| B3a | `FileLayout` interface, `DialPathKind`, the standalone implementation, the provider; `HomePathResolver` (bound in `shared/home_path/home_path_module.py`, request scope) delegates. `PROJECT_CONTEXT` is still created in `AppModule` and `_request_context`; the layout provider is its only reader for this concern | new `shared/file_layout/`, `shared/home_path/` | B1, B2, T1 to T3, D-1, D-2 | todo |
| B3b | The project implementation and the legacy to logical URL conversion for known roots only (see "The two forms are ambiguous") | `shared/file_layout/`, `common/project_context.py` | B3a | todo |
| B4 | `AttachmentService` uses `output_url` / `appdata_url` and drops `PROJECT_CONTEXT`; one appdata rule | `dial_core_services/attachment_service.py` | B3b | todo |
| B5 | Literals, group 1 (see the B5 row above). One PR per consumer if large | `_get_content_tool.py`, keep policy, materializer, `_attachment_resolver.py`, `url_classification.py`, the argument transformer | B3b | todo |
| B6 | `_MCPTool` `dial_url` parameters (closes TODO #445); the skill file source stops importing `skill_root_of_file_url` into `mcp_tooling`. The current pass-through of a `projects/` URL to the grant changes here: a deliberate behaviour change, call it out in the PR | `mcp_tooling/_mcp_tool.py`, `skills/skill_file_url.py` | B3b, D-4 | todo |
| B7 | Architecture test with the allow-list from "Guard against regression" | new test | B4, B5, B6 | todo |

### Conditional and not sliced yet

- **A3** (de-duplication in `download_file`): skip unless a real case shows up (see Open Questions).
- **Checkpoint after B4**, then **C0 to C4**: C2 to C4 now have to start from the real code (the promoter calls
  `dial_client.files.get_metadata` directly, there is no `ProjectFilesClient.file_metadata`). Rewrite them at the
  checkpoint.
- **M1 to M5**: after the Core API is final, and after the choice between the unified API and the SDK approach.

### Log

Add one line per finished PR: id, date, link, anything that changed the plan.
