# Design: ai-dial-interpreter-mcp — Cloud Python Interpreter Adapter

- **Status:** Approved
- **Last updated:** 2026-08-25
- **Dependencies:**
  - None — this design describes a **new, standalone project** (`ai-dial-interpreter-mcp`).
    Changes to quickapps itself are configuration-only (no code modifications).

---

## Problem Statement

QuickApps ships a built-in Python interpreter tool (`internal_tooling/py_interpreter_tooling/`).
It talks to a self-hosted interpreter service via the `/v1/ops/code_interpreter/*` HTTP API,
routed either through DIAL Core or directly (`PY_INTERPRETER_LOCAL_RUN=true`).

Enterprise clients increasingly want to run code execution on their existing cloud infrastructure
(Azure, AWS) rather than provisioning and operating their own interpreter service.
The current design offers no extension point for cloud-managed sandboxes: there is one hardcoded
HTTP client, one set of env vars, no provider abstraction.

Adding cloud provider support directly to quickapps would couple interpreter-backend concerns into
the core agent runtime, complicate the configuration surface, and grow `internal_tooling/` with
logic that has nothing to do with the rest of the application.

---

## Design Goals

- **G1 — Zero changes to quickapps.** Existing deployments continue to work as today.
  New cloud providers are adopted purely through configuration.
- **G2 — Provider-agnostic interface.** A single MCP server exposes a stable set of tools
  regardless of which cloud backend is active.
- **G3 — Enterprise-ready auth.** Each provider's auth (Entra ID, IAM, API key) is handled
  inside the adapter; quickapps never holds cloud-provider credentials.
- **G4 — DIAL file integration.** Display content (charts, images) and output files produced
  by the sandbox are uploaded to the calling quickapps instance's DIAL file bucket, using
  credentials forwarded on the MCP connection.
- **G5 — Extensibility.** Adding a new provider (E2B, AWS AgentCore) requires implementing
  one abstract interface and registering it — nothing else changes.
- **G6 — Internal interpreter remains a first-class backend.** The existing interpreter
  service can be used as a backend of the adapter, consolidating all interpreter traffic
  through a single integration point over time.

---

## Use Cases

### UC-1: Enterprise client on Azure

**Trigger:** A client has an Azure subscription and a provisioned Azure Container Apps
Session Pool. They want to use it as the code execution backend without running their own
interpreter service.
**Behavior:** They deploy `ai-dial-interpreter-mcp` with `INTERPRETER_BACKEND=azure` and
their Azure credentials. They configure a quickapps MCP toolset pointing to the adapter URL.
**Outcome:** The LLM calls `execute_python`; the adapter opens an Azure Dynamic Session,
runs the code, uploads any generated charts to the client's DIAL bucket, and returns the
result with DIAL attachment URLs. quickapps code is unchanged.

### UC-2: Session continuity across turns

**Trigger:** A user asks the agent to load a CSV in turn 1, then filters it in turn 2.
**Behavior:** The adapter returns a `session_id` on the first call. quickapps stores it in
`StateHolder` and passes it back on the next tool call. The adapter reuses the existing
sandbox session.
**Outcome:** Variables and files from turn 1 are available in turn 2.

### UC-3: Expired session recovery

**Trigger:** The cloud provider expires the sandbox session between conversation turns.
**Behavior:** The adapter receives a 404/expired error from the provider, transparently opens
a new session, and retries the code execution.
**Outcome:** The call succeeds against a fresh session. The new `session_id` is returned and
quickapps updates its state.

### UC-4: Existing deployment (no migration)

**Trigger:** A client already uses quickapps with the built-in internal interpreter.
**Behavior:** Nothing changes — `InternalToolModule` and `_PyInterpreterTool` are untouched.
**Outcome:** Zero disruption. Adoption of the adapter is purely opt-in through config.

---

## Proposed Design

### New project: ai-dial-interpreter-mcp

`ai-dial-interpreter-mcp` is a standalone Python service built with FastAPI + the MCP SDK.
It is deployed independently, in the client's infrastructure, and configured to point at one
cloud provider backend.

```
quickapps
  └─ MCP toolset (url: https://interpreter-adapter/mcp)
       │  MCP streamable-HTTP  (X-Dial-Api-Key, X-Dial-Url headers)
       ▼
ai-dial-interpreter-mcp
  ├─ MCP layer          — tool dispatch, session tracking, DIAL credential extraction
  ├─ ProviderFactory    — selects backend from INTERPRETER_BACKEND env var
  │    ├─ InternalProvider   — HTTP client → /v1/ops/code_interpreter/*
  │    └─ AzureProvider      — REST client → Azure Dynamic Sessions
  └─ DialStorageClient  — uploads display content to caller's DIAL bucket
```

One running instance = one provider. Multiple providers = multiple adapter deployments,
each reachable at its own URL in quickapps's MCP toolset config.

### Project layout

```
ai-dial-interpreter-mcp/
  src/
    interpreter_mcp/
      server.py              — FastAPI app + MCP server entry point
      tools.py               — MCP tool handlers (execute_python, upload_file, list_files)
      session_manager.py     — maps adapter session_ids to provider-native session handles
      dial_storage.py        — DIAL file bucket client (upload, download)
      settings.py            — env-var config (pydantic-settings)
      providers/
        base.py              — ExecutionResult, FileInfo, abstract ProviderBase
        internal.py          — InternalProvider: HTTP client to /v1/ops/code_interpreter/*
        azure.py             — AzureProvider: REST client to Azure Dynamic Sessions
      model/
        request.py           — CodeExecutionRequest, UploadFileRequest
        response.py          — ExecutionResult, DisplayItem, FileInfo
  tests/
  pyproject.toml
  Dockerfile
```

### MCP tools

The adapter exposes three MCP tools. Their signatures are stable across all backends.

#### `execute_python`

Executes Python code in a sandbox session.

| Parameter | Type | Description |
|---|---|---|
| `code` | `string` | Python code to execute |
| `session_id` | `string \| null` | Existing session ID; `null` to open a new session |
| `attachment_urls` | `string[]` | DIAL file URLs to transfer into the sandbox before execution |
| `data_sample_config` | `object \| null` | Pagination config for large outputs (mirrors existing model) |
| `display_title` | `string \| null` | Title for the display stage |

Returns:

| Field | Type | Description |
|---|---|---|
| `session_id` | `string` | Session ID to pass on the next call |
| `status` | `string` | `"success"` \| `"error"` |
| `result` | `string` | Primary output (paginated if large) |
| `stdout` | `string` | Standard output (paginated) |
| `stderr` | `string` | Standard error |
| `attachments` | `object[]` | DIAL attachment objects for display content (charts, images) |

#### `upload_file`

Transfers a DIAL file into an existing sandbox session.

| Parameter | Type | Description |
|---|---|---|
| `session_id` | `string` | Target session |
| `dial_file_url` | `string` | Source DIAL file URL |

#### `list_files`

Lists files in the sandbox session working directory.

| Parameter | Type | Description |
|---|---|---|
| `session_id` | `string` | Target session |

### Provider abstraction

All backends implement `ProviderBase`:

```python
class ExecutionResult(BaseModel):
    status: str
    result: str
    stdout: str
    stderr: str
    display: list[DisplayItem]

class ProviderBase(ABC):
    @abstractmethod
    async def open_session(self) -> str: ...

    @abstractmethod
    async def validate_session(self, session_id: str) -> bool: ...

    @abstractmethod
    async def execute_code(self, session_id: str, code: str) -> ExecutionResult: ...

    @abstractmethod
    async def transfer_file(self, session_id: str, filename: str, content: bytes) -> None: ...

    @abstractmethod
    async def list_files(self, session_id: str) -> list[FileInfo]: ...

    @abstractmethod
    async def close_session(self, session_id: str) -> None: ...
```

`ProviderFactory` reads `INTERPRETER_BACKEND` at startup and instantiates the appropriate
implementation. Adding a new provider means implementing `ProviderBase` and adding a branch
to the factory — nothing else changes.

### Session management

Cloud provider session IDs are opaque to quickapps. The flow:

1. First call arrives with `session_id=null`.
2. `SessionManager` calls `provider.open_session()` → provider-native session ID.
3. The adapter returns `session_id` in the tool result JSON.
4. The LLM receives `session_id` as part of the tool result and is expected to pass it back
   on the next `execute_python` call. This relies on the LLM following the tool's schema
   description. See Open Question #5 for the risk and mitigation options.
5. On expiry (provider returns 404 / session-not-found), `SessionManager` transparently
   opens a new session and retries the execution once.

The adapter itself is stateless with respect to session IDs — it does not persist them between
requests. The session ID flows through the LLM's context window as a tool result value,
analogous to how smolagents and other agent frameworks handle sandbox session continuity.

The adapter is stateless — it holds no session-to-conversation mapping. The session ID is
returned in the tool result JSON and travels through the LLM's context window; the LLM is
expected to echo it back on each subsequent call. This is distinct from the existing
`SessionManager` in `py_interpreter_tooling/`, which reads and writes session IDs through
quickapps's `StateHolder` and is tightly coupled to the quickapps request lifecycle. The
risk of the LLM dropping the session ID is documented in Open Question #5.

### DIAL file integration

Display content (charts, Plotly figures, CSVs) produced by the sandbox must reach the user
as DIAL file attachments. The adapter needs the caller's DIAL credentials to upload them.

**Credential delivery:** The adapter is deployed as a DIAL-internal service (its URL is
rooted under the DIAL Core base URL). quickapps's MCP client already forwards the caller's
per-request DIAL API key as `Authorization: Bearer <api-key>` to any MCP server whose URL
starts with `dial_settings.url` (`_mcp_toolset_client.py`, `__build_headers`). No additional
configuration is required in the quickapps toolset config.

- **DIAL URL** — configured as the `DIAL_URL` env var on the adapter at deploy time.
- **DIAL API key** — received as the `Authorization: Bearer` header on every incoming MCP
  request; forwarded automatically by quickapps from the caller's per-request credentials.

The adapter reads the API key from the incoming `Authorization` header and passes it to
`DialStorageClient` for file operations. It must never be logged and must not be passed to
`ProviderBase` implementations.

**Upload flow (within `execute_python`):**

1. Adapter calls `provider.execute_code(...)` → `ExecutionResult` with `display` items.
2. For each display item (image bytes, Plotly JSON, CSV):
   a. Upload to the caller's DIAL appdata bucket via `DialStorageClient`.
   b. Replace raw bytes with the returned DIAL URL.
3. Return `attachments` list with DIAL attachment objects.

**Input file flow (within `execute_python` / `upload_file`):**

1. Adapter downloads the DIAL file using `DIAL_URL` + the forwarded API key.
2. Calls `provider.transfer_file(session_id, filename, content)`.

### Provider implementations

#### InternalProvider

Wraps the existing `/v1/ops/code_interpreter/*` HTTP API. Semantics are identical to the
current `_PyInterpreterClient` in quickapps. The relevant model classes
(`CodeExecutionRequest`, `CodeExecutionResponse`, `InputFileTransferDto`) are copied into
the adapter's `model/` package.

Key env vars:

| Var | Description |
|---|---|
| `INTERPRETER_INTERNAL_URL` | Base URL of the internal interpreter service |
| `INTERPRETER_INTERNAL_API_KEY` | API key (for standalone deployments) |

#### AzureProvider

Calls Azure Container Apps Dynamic Sessions REST API.

Session lifecycle:
- Session identity is a **caller-supplied string** in Azure's model. The adapter generates
  a UUID per `open_session()` call and tracks it as the session ID.
- `validate_session`: `GET .../session?identifier=<id>` — if `expiresAt` is in the past
  or returns 404, the session is considered expired.
- `execute_code`: `POST .../executions?identifier=<id>` with inline Python code
  (`executionType: synchronous`).
- `transfer_file`: `POST .../files?identifier=<id>` multipart upload.
- `list_files`: `GET .../files?identifier=<id>`.
- `close_session`: `DELETE .../session?identifier=<id>`.

Auth: `DefaultAzureCredential` from `azure-identity` with token audience
`https://dynamicsessions.io`. Token is refreshed automatically.

Key env vars:

| Var | Description |
|---|---|
| `AZURE_SESSION_POOL_URL` | Base URL of the Azure session pool |
| `AZURE_CLIENT_ID` | Service principal client ID (or use workload identity) |
| `AZURE_CLIENT_SECRET` | Service principal secret |
| `AZURE_TENANT_ID` | Azure AD tenant |

### Configuration

All adapter configuration is env-var driven (pydantic-settings, no quickapps involvement).

| Var | Default | Description |
|---|---|---|
| `INTERPRETER_BACKEND` | — | **Required.** `internal` \| `azure` |
| `DIAL_URL` | — | **Required.** Base URL of the DIAL Core instance (e.g. `https://dial.example.com`). Used by `DialStorageClient` for file uploads and downloads. |
| `INTERPRETER_CLIENT_TIMEOUT` | `120` | HTTP timeout in seconds for provider calls |
| `INTERPRETER_MAX_RETRIES` | `3` | Retry count on transient provider errors |
| `INTERPRETER_INTERNAL_URL` | — | Required when `INTERPRETER_BACKEND=internal` |
| `INTERPRETER_INTERNAL_API_KEY` | — | Required when `INTERPRETER_BACKEND=internal` (not routed through DIAL Core) |
| `AZURE_SESSION_POOL_URL` | — | Required when `INTERPRETER_BACKEND=azure` |
| `AZURE_CLIENT_ID` | — | Azure service principal (or use workload identity) |
| `AZURE_CLIENT_SECRET` | — | Azure service principal |
| `AZURE_TENANT_ID` | — | Azure AD tenant |

### quickapps integration (configuration only)

No code changes in quickapps. The adapter is deployed as a DIAL-internal service (URL
rooted under DIAL Core). quickapps automatically forwards the caller's Bearer token to
DIAL-internal MCP servers — no `authorization` field is needed in the toolset config:

```json
{
  "tool_sets": [
    {
      "type": "mcp",
      "name": "py_interpreter",
      "mcp_server_info": {
        "url": "https://dial.example.com/openai/deployments/interpreter-mcp/mcp",
        "protocol": "streamable_http"
      }
    }
  ]
}
```

The existing `internal_tooling/py_interpreter_tooling/` and its predefined toolset config
(`config/predefined/toolset/py_interpreter.json`) are untouched. Clients that want to
migrate from the built-in tool to the adapter swap one toolset entry in their app config.

---

## Out of Scope

- **AWS AgentCore provider.** Deferred to Phase 2. The provider abstraction accommodates it;
  the implementation is not in scope here.
- **E2B provider.** Deferred to Phase 2 — primarily relevant for non-enterprise use cases.
- **Google Gemini code execution.** Gemini's execution is tightly coupled to its LLM and
  does not accept raw code strings; it cannot fit the `ProviderBase` interface without a
  prompt-wrapping hack. Excluded.
- **Streaming output.** The current internal interpreter and Azure Dynamic Sessions both
  use synchronous request/response for code execution. Streaming output is not in scope for
  Phase 1.
- **Async long-running execution.** AWS AgentCore supports multi-hour async jobs; Azure and
  the internal interpreter do not. Deferred.
- **Removing `internal_tooling/py_interpreter_tooling/` from quickapps.** Existing clients
  should not be forced to migrate. The built-in tool stays indefinitely; deprecation is a
  separate decision.
- **MCP server hosting by EPAM/DIAL.** Phase 1 targets client-deployed adapters only.
  A centrally hosted, multi-tenant adapter is a separate initiative.

---

## Configuration / Usage Examples

### Example 1: Azure backend (enterprise client)

Adapter deployment env:
```
INTERPRETER_BACKEND=azure
DIAL_URL=https://dial.example.com
AZURE_SESSION_POOL_URL=https://westeurope.dynamicsessions.io/subscriptions/xxx/resourceGroups/rg/sessionPools/mypool
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=<secret>
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

quickapps app config:
```json
{
  "tool_sets": [
    {
      "type": "mcp",
      "name": "py_interpreter",
      "mcp_server_info": {
        "url": "https://dial.example.com/openai/deployments/interpreter-mcp/mcp",
        "protocol": "streamable_http"
      }
    }
  ]
}
```

### Example 2: Internal backend (existing interpreter via adapter)

```
INTERPRETER_BACKEND=internal
INTERPRETER_INTERNAL_URL=https://my-interpreter.internal
```

quickapps config: same as above, different adapter URL.

---

## Migration

### Non-breaking changes

The adapter is a net-new project. No existing quickapps code, config, or deployment is
modified. Existing clients using the built-in `py_interpreter` internal tool are unaffected.

### Migration path for existing clients

Clients wishing to migrate from the built-in tool to the adapter:
1. Deploy `ai-dial-interpreter-mcp` with `INTERPRETER_BACKEND=internal` pointing at their
   existing interpreter service URL.
2. Replace the `internal` toolset entry in their app config with the `mcp` toolset entry.
3. Remove the `PY_INTERPRETER_*` env vars from the quickapps deployment.

This migration is optional and reversible.

---

## Delivery Phases

### Phase 1 (this design)
- New project `ai-dial-interpreter-mcp` with `InternalProvider` and `AzureProvider`.
- Full DIAL file integration (display content upload, input file transfer).
- Session management with transparent recovery on expiry.

### Phase 2
- `AwsAgentCoreProvider` — AWS AgentCore backend.
- `E2BProvider` — for non-enterprise / developer use cases.
- Async execution support (AWS long-running jobs).

---

## Open Questions

1. ~~**MCP connection headers support in quickapps.**~~ **Resolved.** The `headers` field
   approach is not needed. Credential delivery uses the existing `MCPApiKeyAuthorization`
   mechanism (`authorization.type = "api_key"`) to pass `X-Dial-Api-Key`; `DIAL_URL` is an
   adapter-side env var. No quickapps code changes required; G1 holds.
2. **Azure Session Pool provisioning.** Azure Dynamic Sessions requires a Session Pool
   resource to be pre-provisioned. Should the adapter docs include a Terraform/ARM snippet,
   or is this the client's responsibility?
3. **Content size limits.** Azure Dynamic Sessions has a 220-second execution limit and
   128 MB file upload cap. The internal interpreter has its own limits. Should the adapter
   surface these as config or just propagate provider errors?
4. **Session ID namespace.** The adapter generates UUIDs as Azure session identifiers.
   Should these be namespaced per quickapps deployment (to support multiple quickapps
   instances sharing one Azure session pool without ID collision)?
5. **Session ID continuity via LLM context.** The design relies on the LLM passing
   `session_id` back on each subsequent call. In practice, well-instructed LLMs do this
   reliably when the tool description makes it clear. However, if the LLM drops the session
   ID (e.g. after a long context window), a new session is silently opened and prior
   in-session state is lost. Mitigation options: (a) quickapps extracts `session_id` from
   MCP tool results and injects it into the next call via a state hook — requires a
   quickapps-side change; (b) document the limitation and rely on LLM behavior; (c) the
   adapter accepts a stable `conversation_id` header and manages its own session-to-conversation
   mapping — adds statefulness to the adapter.

---

## Summary of Changes

| Component | Status | Change |
|---|---|---|
| `ai-dial-interpreter-mcp/` | **New project** | Standalone MCP server with provider abstraction |
| `providers/base.py` | New | `ProviderBase` abstract interface + shared models |
| `providers/internal.py` | New | `InternalProvider` — wraps existing `/v1/ops/code_interpreter/*` API |
| `providers/azure.py` | New | `AzureProvider` — Azure Container Apps Dynamic Sessions |
| `tools.py` | New | MCP tool handlers: `execute_python`, `upload_file`, `list_files` |
| `session_manager.py` | New | Session ID lifecycle, expiry detection, transparent recovery |
| `dial_storage.py` | New | DIAL bucket client for display content upload and input file download |
| `settings.py` | New | Env-var config (pydantic-settings) |
| quickapps `internal_tooling/` | **Unchanged** | No modifications |
| quickapps app config | Configuration only | Add MCP toolset entry pointing to adapter URL |

