# Design: Per-toolset forwarding of X-* request headers

- **Status:** Implemented
- **Issue:** [I#765](https://github.com/epam/ai-dial-quickapps-backend/issues/765)
- **Dependencies:**
  - None. Resolves the open question about `x-project-id` and REST tools left by [projects.md](./projects.md) (D-table:
    "`x-project-id` to nested apps and MCP: unchanged").

## Problem Statement

- `extract_x_headers_from_request` (`common/forwarded_headers.py`) collects every request header whose name starts with
  `X-` (case-insensitive) into one `ForwardedHeaders` dict. The dict is injected unchanged into every outbound call: the
  orchestrator (`agent_module.py`, `_chat_completion_config_builder.py`), the shared DIAL deployment client
  (`deployment_client_module.py`, `dial_completion_service.py`), MCP (`_mcp_toolset_client.py`) and REST API tools
  (`_rest_api_tool.py`).
- The consumers have different trust levels. The orchestrator, DIAL deployments and nested DIAL apps are inside the DIAL
  contour. An MCP server or a REST API tool can be any third-party host. All of them get the same headers.
- `X-*` is a syntactic class, not a DIAL one. It holds DIAL headers (`x-project-id`, `X-DIAL-CLIENT-CHANNEL-ID`), client
  headers (`X-Timezone`) and whatever ingresses, proxies and gateways add (`X-Forwarded-For`, `X-Real-IP`,
  `X-Request-Id`). `x-project-id` names the user's bucket and project and reaches external REST hosts today. Any `X-*`
  header added later by Chat, Core or a proxy leaks the same way.
- The only guard, `_validate_forwarded_headers` (`core/application/_request_context.py`), rejects `api-key` and
  `authorization`. Neither starts with `X-`, so the extractor never collects them; the guard is a tripwire that never
  fires today.
- The app builder has no say: no way to block a header for one tool or pass one header to one tool only.
- The "internal" test already used for MCP (`url.startswith(dial_settings.url)` in `_mcp_toolset_client.py`, for the
  DIAL bearer) has no host boundary: with `dial_settings.url == "https://dial.corp"`, the URL
  `https://dial.corp.attacker.io/mcp` also matches.

## Design Goals

- A toolset that talks to a third party gets no `X-*` header unless the builder lists it.
- A toolset inside the DIAL contour keeps getting every `X-*` header unless the builder narrows it.
- The builder controls this per toolset, with one field on every toolset type that forwards headers.
- No wildcard and no app-level default: a header is forwarded to an external host only when it is named on that toolset.
- `api-key` and `authorization` can never be forwarded, whatever the manifest says.
- Existing deployments keep a time-limited way back to the old behaviour for external toolsets, controlled by the admin.
- A builder who loses a header after the upgrade can find out which one.
- The orchestrator model call and the tool-discovery routing call behave as today: they receive every `X-*` header.

## Non-Goals

- Forwarding headers that do not start with `X-` (`traceparent`, `Accept-Language`). `Accept-Language`, the API key and
  the bearer are already handled through their own request-context fields.
- Static headers, header renaming or mapping.
- Wildcards or prefix patterns in the allowlist.
- An app-level default (rejected: it widens the blast radius back to "all external hosts" with one line, and needs
  precedence rules for internal toolsets and the orchestrator; it can be added later as an optional field without
  breaking anything).
- A "known DIAL headers" list. No stable list exists, and `x-project-id` carries no `x-dial-` prefix.

## Use Cases

### UC-1: REST tool never sees the project

**Trigger:** A chat inside a DIAL Chat project calls a REST toolset with no `forwarded_headers`.
**Behavior:** The REST request carries only what the toolset's own authorization and parameters produce.
**Outcome:** `x-project-id` does not reach the external host.

### UC-2: Tenant header to one REST API

**Trigger:** The builder sets `"forwarded_headers": ["X-Tenant-Id"]` on one REST toolset.
**Behavior:** The request carries `X-Tenant-Id` (if the incoming request had it). Other REST toolsets of the same app
still get nothing.
**Outcome:** The header reaches exactly one host.

### UC-3: MCP server that works with Core projects

**Trigger:** A plain `mcp` toolset on a third-party URL lists `["x-project-id"]`.
**Behavior:** The MCP session opens with `x-project-id` in its headers.
**Outcome:** The builder opted in knowingly. Without the entry the header is not sent.

### UC-4: Narrowing an internal toolset

**Trigger:** A `dial-deployment` toolset sets `["X-Request-Id"]`.
**Behavior:** Calls to its deployments carry `X-Request-Id` only.
**Outcome:** The other `X-*` headers (including `x-project-id`) stop at this toolset.

### UC-5: Upgrade of an app that relied on the old behaviour

**Trigger:** An existing app has a REST toolset and relied on `X-Tenant-Id` being forwarded. The operator upgrades.
**Behavior:** Default: the header is gone and an INFO line names the dropped header (not its value). With the admin
switch on: behaviour is unchanged until the switch is removed.
**Outcome:** The builder adds `forwarded_headers`, then the operator turns the switch off.

## Proposed Design

### Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | One policy service. Each module asks it for the headers of a toolset when it builds the tool or client and passes the result in place of raw `ForwardedHeaders`. | One place for the rules. Requires dropping `X-*` from the shared deployment client's `default_headers`. |
| B | Pass the toolset config to every consumer; each filters on send. | Smaller diff, but the rule (internal vs external, case, empty list, switch) is copied into 3-4 places and drifts. The `default_headers` problem remains. |
| C | Precompute `{toolset key: headers}` at request setup; consumers look up by key. | Needs a stable toolset key. Names are `LocalizedString` and not unique; only MCP has a key today. Heaviest. |

### Manifest field

- **What:** `forwarded_headers: list[str] | None`, default `None`, on `RestApiToolSet`, `MCPToolSet`, `DialMCPToolSet`,
  `DeploymentToolSet` and `DialAppToolSet`. Not on `InternalToolSet` or `PredefinedToolSet` (they make no outbound
  calls with request headers). Shared via one mixin or reusable annotated type so the validation lives once.
- **Semantics:**
  - `None` (unset): the default of the toolset's class (below).
  - A list: exactly these headers and nothing else, matched case-insensitively against the incoming request. `[]`
    means none, also for an internal toolset.
  - A name that is absent from the request is simply not sent.
- **Validation (schema level, so `make dump_app_schema` carries it):** each entry must be a valid HTTP header-name
  token, start with `x-` (case-insensitive) and must not contain `*`. Entries are lower-cased and de-duplicated.
  Anything else fails manifest validation with a message naming the entry. This also makes `api-key` and
  `authorization` unforwardable by construction.
- **Description text** for the schema must say "X-* request headers", not "DIAL headers".

### Toolset class: internal or external

| Toolset | Class | Default when `forwarded_headers` is unset |
|---|---|---|
| `dial-deployment` | internal | all `X-*` |
| `dial-app` (MCP or chat-completion branch) | internal | all `X-*` |
| `dial-mcp` | internal | all `X-*` |
| `mcp` whose server origin equals the DIAL origin | internal | all `X-*` |
| `mcp` on any other origin | external | none |
| `rest-api` | external | none |
| orchestrator model call, tool-discovery routing call | not toolsets | all `X-*` (unchanged) |

"Same origin" means equal scheme, host (case-insensitive) and effective port, parsed with `urllib.parse`. A helper
(for example `is_dial_origin(url, dial_url)` in `common/`) replaces the `startswith` check; the existing bearer logic
in `_mcp_toolset_client.py` uses the same helper so the codebase has one definition of "internal MCP". *(My call: it
fixes the missing host boundary as part of this change. Easy to split into its own PR.)*

`rest-api` is external even when its URL points at DIAL: a REST tool is a generic HTTP caller, and a builder who wants
headers there lists them. *(My call.)*

### Admin switch

- **Env:** `FORWARD_ALL_X_HEADERS_TO_EXTERNAL_TOOLSETS`, `bool`, default `false`, in a small `BaseSettings` class next
  to the forwarding code (pattern: `ExternalFetchSettings`).
- **Effect when `true`:** an external toolset whose `forwarded_headers` is unset behaves as before (all `X-*`). A set
  list still wins and is applied exactly. It does not affect internal toolsets.
- **Lifecycle:** documented as deprecated in `CONFIGURATION.md` on introduction, removed after one or two releases.
  When it is `true`, startup logs one WARNING that it is deprecated.

### Policy service

- **What:** `ForwardedHeadersPolicy` (DI, request scope), in `common/` or a small `shared/forwarded_headers/` package
  registered through `shared_module`.
- **Inputs:** the request's `ForwardedHeaders`, the admin setting, `DialSettings`.
- **API (shape, names are the builder's call):** `for_toolset(toolset) -> ForwardedHeaders` returns the dict to send for
  that toolset per the table above; `all() -> ForwardedHeaders` returns the full dict for the orchestrator and the
  routing call.
- **Behaviour:** pure filtering, no mutation of the request context; matching is case-insensitive; header names keep
  the casing of the incoming request.
- **Dropped-header log:** when an external toolset has no `forwarded_headers`, the switch is off and the request carried
  `X-*` headers, log one INFO line per toolset: toolset name and the dropped header names, never values. De-duplicate per
  process by (toolset name, set of names) so the line does not repeat on every request. *(My call, check against
  `docs/designs/log_levels_and_content_policy.md`, which keeps routine per-request outcomes out of INFO.)*

### Consumers

- **REST** (`rest_api_tooling_module.py`, `_rest_api_tool.py`): the module already builds tools per toolset and passes
  `auth_info`; it passes the toolset's headers the same way. The tool merges them into the request as today.
- **MCP** (`_mcp_toolset_client.py`, `_mcp_tool_initializer.py`): the client receives the toolset's headers instead of
  the raw dict. Two places synthesize an `MCPToolSet` field by field (`_mcp_tool_initializer.py:503` from `DialMCPToolSet`,
  `_dial_app_resolver.py:133` from `DialAppToolSet`); both must copy `forwarded_headers`, otherwise a narrowing set on
  the source toolset is silently dropped.
- **DIAL deployment tools** (`dial_completion_service.py`, `deployment_client_module.py`):
  - `DialCompletionService` is request-scoped and shared by all deployment tools, so it cannot know the toolset. The tool
    passes its toolset's headers into `complete_request_async`, which sends them as `extra_headers`.
  - `DEPLOYMENT_AZURE_CLIENT` currently bakes `X-*` into `default_headers`, and per-call `extra_headers` only add to
    them, so a narrowed toolset could not remove a header. Change: the client keeps only `Authorization` in
    `default_headers`; every call site passes its `X-*` headers explicitly.
  - Plumbing from toolset to tool follows the existing precedent of copying toolset fields onto the tool config
    (`DialAppToolSet` branch: `tool_config.model_copy(update={...})` in `_dial_app_resolver.py:170`). The field must not
    appear as a new per-tool manifest field. Covers `DialDeploymentTool`, `DialDeploymentSimpleTool` and the tool
    synthesized from `DialAppToolSet`.
  - The tool-discovery routing call (`tool_discovery/_anonymous_agent.py`) uses the same client and must now pass all
    `X-*` headers explicitly, to keep its behaviour.
- **Orchestrator** (`agent_module.py`, `_chat_completion_config_builder.py`): unchanged.

### Unchanged

- `_validate_forwarded_headers` stays as a last-line guard. `client_channel_id` and `project_context` keep reading from
  the full dict in `_request_context_setup.py`; they are not forwarding.
- Files, skills, hooks and `ExternalUrlFetcher` do not use `ForwardedHeaders` and are not touched.

## Out of Scope

- Wildcards (rejected on purpose: they bring back the leak in one line).
- App-level default (see Non-Goals).
- Non-`X-*` headers, static headers, header mapping.
- Editor UI support for the new field. The quickapps-editor needs its own issue; until then UI-built apps use the admin
  switch.
- Whether `x-project-id` should be a protected header that no manifest may forward. Today an explicit entry is allowed.

## Configuration / Usage Examples

```json
{
  "tool_sets": [
    {
      "type": "rest-api",
      "name": "Billing",
      "forwarded_headers": ["X-Tenant-Id", "X-Request-Id"],
      "tools": [ "..." ]
    },
    {
      "type": "mcp",
      "name": "Third-party search",
      "mcp_server_info": { "url": "https://search.example.com/mcp", "protocol": "streamable_http" }
    },
    {
      "type": "dial-deployment",
      "name": "Internal agents",
      "forwarded_headers": ["x-project-id", "x-request-id"],
      "tools": [ "..." ]
    }
  ]
}
```

| Toolset | Incoming `X-*` | Sent |
|---|---|---|
| Billing (REST, list) | `X-Tenant-Id`, `x-project-id`, `X-Timezone` | `X-Tenant-Id` |
| Third-party search (MCP, external, unset) | all three | none |
| Internal agents (deployment, list) | all three | `x-project-id` |
| Any internal toolset, unset | all three | all three |

## Migration

### Breaking changes

- REST and MCP toolsets on a non-DIAL origin stop receiving `X-*` headers unless `forwarded_headers` lists them.
- A manifest with an invalid entry (no `x-` prefix, contains `*`) now fails validation.
- Mitigation: the admin switch (above), the dropped-header INFO line, and a migration note.

### Non-breaking changes

- Internal toolsets, the orchestrator and the routing call behave as before.
- Apps that never set `forwarded_headers` and have no external toolsets are unaffected.

### Release notes

`Deployment Changes` gets: the breaking default, the switch name and its removal plan, and one `X-Tenant-Id` example.
`CONFIGURATION.md` "Forwarding headers" is rewritten around the table in this doc; its claim "No configuration is
required" is removed.

## Summary of Changes

- **Config:** `forwarded_headers` on five toolset types (shared validation); schema regenerated.
- **New:** `ForwardedHeadersPolicy`, `is_dial_origin` helper, forwarding settings class
  (`FORWARD_ALL_X_HEADERS_TO_EXTERNAL_TOOLSETS`).
- **Changed:** REST module/tool, MCP client and both `MCPToolSet` synthesis sites, deployment tools and
  `DialCompletionService`, `DeploymentClientModule` (no `X-*` in `default_headers`), `_anonymous_agent`, the MCP bearer
  origin check.
- **Docs:** `CONFIGURATION.md` ("Forwarding headers", env table), `docs/designs/projects.md` (update the `x-project-id`
  rows), this doc to Implemented.
- **Tests:** the policy (case, empty list, unset, switch, per toolset class), origin helper (including the lookalike
  host), schema validation (rejected entries), both `MCPToolSet` synthesis sites keep the field, REST/MCP/deployment
  requests carry exactly the expected headers, the routing call still sends all `X-*`.
