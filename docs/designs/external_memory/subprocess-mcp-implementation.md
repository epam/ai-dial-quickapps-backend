# subprocess-mcp: Implementation and Container Model Considerations

- **Status:** Implemented (hypothesis validated)
- **Related:** [File-Based Providers](file-based-providers.md) | [Implementation Draft](file-based-providers-implementation-draft.md)

---

## Scope

This document covers:

1. What was actually built — the concrete code implementing the `subprocess-mcp` toolset type.
2. What was validated — two providers tested end-to-end, confirming the generic approach.
3. What must be addressed when QuickApps adopts a per-user container deployment model.

The implementation draft in `file-based-providers-implementation-draft.md` describes the full
production design (per-user subprocess pool with TTL eviction). This document describes the
**simplified version built to validate the hypothesis**, and flags what changes when containers ship.

---

## What Was Built

### Goal

Validate the hypothesis: *running a file-based MCP memory server as a subprocess is a viable generic
mechanism for plugging in different memory providers — no HTTP server, no DIAL deployment, no adapter.*

### Design Simplification (vs. Draft)

The draft proposed a `SubprocessPool` keyed by `(user_id, toolset_name)` with TTL eviction, designed
for the shared-service model where many users share one QuickApps process. The implementation instead
uses a simpler `_StdioConnectionRegistry` keyed by `toolset_name` only:

| | Draft | Implemented |
|---|---|---|
| Pool key | `(user_id, toolset_name)` | `toolset_name` |
| TTL eviction | Yes — idle subprocesses cleaned up | No — subprocess lives for the process lifetime |
| Multi-user isolation | Per-user subprocess instances | Container-level (one container = one user) |

This simplification is **correct for the container model** where one QuickApps process serves exactly
one user. It would break in the shared-service model — that path requires the full pool design from
the draft.

### New Files

#### `src/quickapp/config/toolsets/subprocess_mcp.py`

Config model for the `"type": "subprocess-mcp"` toolset:

```python
class SubprocessMCPToolSet(BaseToolSet):
    type: Literal["subprocess-mcp"] = Field(default="subprocess-mcp", ...)
    name: str
    command: str               # CLI command installed in the Docker image
    args: list[str] = []
    env: dict[str, str] = {}   # supports {{dial_bucket_path}} template variable
    allowed_tools: list[str] | None = None
    attachment: AttachmentConfig
    fallback_configuration: ToolFallbackConfig
```

Both `env` values and `args` entries support `{{dial_bucket_path}}` substitution, performed at
request time before the subprocess is spawned.

#### `src/quickapp/mcp_tooling/_abstract_mcp_connection_manager.py`

Structural Protocol shared by HTTP (`_MCPConnectionManager`) and stdio (`_StdioMCPConnectionManager`):

```python
class MCPConnectionManagerProtocol(Protocol):
    async def get_tools_list(self) -> list[Tool]: ...
    async def call_mcp_tool(self, tool_name: str, **kwargs) -> CallToolResult: ...
```

#### `src/quickapp/mcp_tooling/_stdio_mcp_connection_manager.py`

Long-lived stdio session manager. Unlike the HTTP manager (stateless, reconnects per call), this
holds a single open `ClientSession` for the lifetime of the manager — closing it terminates the
subprocess.

Key implementation detail: `call_mcp_tool` passes `kwargs` directly (not `kwargs or None`). An
empty dict `{}` is falsy in Python, so the `or None` pattern would send `None` to the subprocess for
zero-argument tools, which is rejected by Node.js/Zod as `undefined`. See regression test
`test_call_mcp_tool_no_args_passes_empty_dict`.

#### `src/quickapp/mcp_tooling/_stdio_connection_registry.py`

Process-level singleton registry: `toolset_name` → `_StdioMCPConnectionManager`. On first access
for a given toolset name, spawns the subprocess and stores the manager. Subsequent requests reuse
the live session.

### Modified Files

**`mcp_tooling/_mcp_tool.py`** — `connection_manager` type annotation changed from
`_MCPConnectionManager` to `MCPConnectionManagerProtocol`. No logic changes.

**`mcp_tooling/_mcp_tool_initializer.py`** — new `_process_subprocess_toolset()` method:

```python
async def _process_subprocess_toolset(self, toolset_info: SubprocessMCPToolSet) -> None:
    bucket_path = os.environ.get("DIAL_BUCKET_PATH", "")
    def _sub(value: str) -> str:
        return value.replace("{{dial_bucket_path}}", bucket_path)
    env = {k: _sub(v) for k, v in toolset_info.env.items()}
    args = [_sub(a) for a in toolset_info.args]
    params = StdioServerParameters(command=toolset_info.command, args=args, env=env)
    connection_manager = await self.__stdio_registry.get_or_create(label, params)
    tools = await connection_manager.get_tools_list()
    # filter by allowed_tools, build _MCPTool instances, extend context
```

`DIAL_BUCKET_PATH` is resolved from the process environment, not from the DIAL API. This means the
bucket path is the same for all requests in the process — correct for per-user containers, wrong for
shared-service. In the production shared-service implementation the draft describes resolving
bucket_path via `dial_client.bucket.get_raw()` per request.

**`mcp_tooling/mcp_tooling_module.py`** — `_StdioConnectionRegistry` bound as singleton.

**`Dockerfile`** — Node.js, npm, and MCP servers installed in the runtime stage:

```dockerfile
RUN apk add --no-cache nodejs npm && \
    npm install -g @modelcontextprotocol/server-memory@2026.1.26 @modelcontextprotocol/server-filesystem && \
    npm cache clean --force && \
    rm -rf /root/.npm && \
    which mcp-server-memory && which mcp-server-filesystem
```

### `{{dial_bucket_path}}` Substitution

The template variable is substituted in both `env` and `args` before the subprocess is spawned:

| Config location | Example |
|---|---|
| `env` | `"MEMORY_FILE_PATH": "{{dial_bucket_path}}/memory.jsonl"` |
| `args` | `["{{dial_bucket_path}}/files"]` |

---

## Hypothesis Validation

Two structurally different providers were tested end-to-end in the local docker-compose environment.

### Provider 1: `mcp-server-memory`

```json
{
  "type": "subprocess-mcp",
  "name": "memory",
  "command": "mcp-server-memory",
  "args": [],
  "env": { "MEMORY_FILE_PATH": "{{dial_bucket_path}}/memory.jsonl" }
}
```

Result: subprocess spawned, session initialized, knowledge graph tools (`create_entities`,
`search_nodes`, `read_graph`, etc.) registered and callable. `memory.jsonl` written to the user's
bucket volume at `/data/bucket/memory.jsonl`.

Bug encountered: `read_graph` (a zero-argument tool) returned `isError=true` with `expected object,
received undefined`. Root cause: `kwargs or None` in `call_mcp_tool` — `{}` is falsy, so the server
received `null` instead of `{}`. Fixed by removing `or None`.

### Provider 2: `mcp-server-filesystem`

```json
{
  "type": "subprocess-mcp",
  "name": "filesystem",
  "command": "mcp-server-filesystem",
  "args": ["{{dial_bucket_path}}/files"],
  "env": {}
}
```

Result: subprocess spawned, session initialized, filesystem tools (`list_directory`, `read_file`,
`write_file`, etc.) registered and callable. `write_file` successfully wrote
`/data/bucket/files/user_profile.json`.

Issue encountered: `mcp-server-filesystem` validates all declared paths at startup and exits if any
do not exist. The `/data/bucket/files` directory must be created before the first request. See
[Pre-existing Directory Requirement](#pre-existing-directory-requirement) below.

### Conclusion

The same `subprocess-mcp` mechanism works for any stdio MCP server regardless of:
- What language it is implemented in (both tested providers are Node.js)
- How the data path is passed — `env` variable or positional CLI argument
- What tools it exposes — the tool list is fetched via `list_tools()` at initialization

---

## Container Model: What Must Be Addressed

### Current Assumption

The implementation assumes one QuickApps container per user. The `_StdioConnectionRegistry` is a
process-level singleton keyed by toolset name only. This is correct in the container model and wrong
in the shared-service model.

### Mounting the User's Bucket

The DIAL bucket must be mounted as a volume into the QuickApps container. The container sees it as a
local filesystem path, which is passed to the MCP server via `DIAL_BUCKET_PATH`.

Example docker-compose fragment (used in validation):

```yaml
quick-apps:
  environment:
    DIAL_BUCKET_PATH: /data/bucket
  volumes:
    - ./docker_compose_files/quick-apps/bucket:/data/bucket
```

In production container orchestration, each user's container gets their own DIAL bucket mounted at
the same well-known path. The MCP server writes to subdirectories inside the bucket; data persists
across container restarts because the backing storage is the user's DIAL file storage.

### Pre-existing Directory Requirement

Some MCP servers validate their data paths at startup and refuse to start if the path does not exist.
`mcp-server-filesystem` exhibits this behaviour — passing a non-existent directory as a CLI argument
causes it to exit immediately, which results in `McpError: Connection closed` in QuickApps.

Two options to handle this:

**Option A — Pre-create directories in the image entrypoint.**  
The container entrypoint script creates standard subdirectories under `$DIAL_BUCKET_PATH` before
starting uvicorn:

```sh
# docker_entrypoint.sh (addition)
mkdir -p "${DIAL_BUCKET_PATH}/files"
```

This is the simplest fix. The downside is that the Dockerfile must know which subdirectories each
provider requires.

**Option B — Catch `McpError: Connection closed` and retry after mkdir.**  
In `_StdioConnectionRegistry.get_or_create`, if `start()` raises `McpError` whose message contains
`Connection closed`, inspect the `args` for paths and attempt to create them:

```python
try:
    await manager.start()
except McpError:
    _ensure_arg_paths_exist(params.args)
    await manager.start()
```

This is self-healing but requires the registry to know which arguments are filesystem paths — fragile
for the general case.

**Recommendation:** Option A. The set of providers baked into the image is fixed at build time; the
required directories are known. Document the convention: providers that accept a data path via args
must declare the default subdirectory name in their Dockerfile comment.

### Adding New Providers to the Image

The set of available MCP servers is determined at image build time. To add a new provider:

1. Install it in the `runtime` stage of the Dockerfile:

```dockerfile
# Node.js package
npm install -g @scope/mcp-server-name

# Python package (uv)
uv tool install basic-memory
```

2. Add a `which <command>` check to verify it landed in `PATH`.
3. If the provider requires a pre-existing directory, add `mkdir -p` to the entrypoint.
4. Add a sample app config entry to `docker_compose_files/core/configuration/applications.json`.

Providers are never fetched at runtime — the image is the contract. An operator cannot configure
a provider that is not installed in the image without a new image build. This is intentional:
providers are vetted and pinned, not pulled from the internet on demand.

### Alternative: Installing Providers Without Modifying the Dockerfile

If modifying the Dockerfile is not possible (e.g. the image is owned by another team or released
separately), there are three approaches for delivering MCP server binaries to the container.

#### Option A — Init container (Kubernetes)

A dedicated init container installs providers into a shared `emptyDir` volume before the main
container starts. The main container adds the volume's `bin/` directory to `PATH` via an env var.

```yaml
initContainers:
  - name: install-mcp-providers
    image: node:20-alpine
    command: ["npm", "install", "-g", "--prefix", "/mcp-tools",
              "@modelcontextprotocol/server-memory@2026.1.26"]
    volumeMounts:
      - name: mcp-tools
        mountPath: /mcp-tools
containers:
  - name: quick-apps
    env:
      - name: PATH
        value: "/mcp-tools/bin:/usr/local/bin:/usr/bin:/bin"
    volumeMounts:
      - name: mcp-tools
        mountPath: /mcp-tools
```

**Pros:** QuickApps image stays clean; provider versions are declared in the deployment manifest,
not baked into the image; no Dockerfile changes required.  
**Cons:** Requires Node.js (or uv) in the init container image; `PATH` must be explicitly forwarded
to the main container.

#### Option B — `npx` / `uvx` on first spawn

Instead of pre-installing, run providers through `npx -y` (Node.js) or `uvx` (Python), which
download and cache the package on first invocation:

```json
{
  "type": "subprocess-mcp",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-memory@2026.1.26"]
}
```

**Pros:** Zero changes to the image (only Node.js or uv must be present); the provider version is
declared directly in the app config.  
**Cons:** First start incurs a network request and download latency; does not work in air-gapped
environments; the npm cache lives inside the container and is lost on restart.

#### Option C — Pre-populated volume mount

The operator maintains a host path or persistent volume with pre-installed npm packages and mounts
it into the container. The container adds the volume's `bin/` to `PATH`.

**Pros:** Fully offline after initial setup; providers can be updated without rebuilding or
redeploying the image.  
**Cons:** Requires an out-of-band process to populate and update the volume; adds operational
complexity for the platform team.

#### Recommendation

| Scenario | Recommended option |
|---|---|
| Kubernetes, image not owned by this team | **A** — init container |
| Development / quick validation | **B** — `npx -y` / `uvx` |
| Air-gapped production, no Dockerfile access | **C** — pre-populated volume |
| Full control over image | Dockerfile (original approach) |

### Graceful Subprocess Shutdown

Currently, subprocesses spawned by `_StdioConnectionRegistry` are not explicitly stopped when the
QuickApps process shuts down. The OS terminates child processes when the parent exits, so there is
no data loss risk — but subprocess cleanup is not controlled.

For production, add a FastAPI `lifespan` shutdown hook:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await stdio_registry.stop_all()
```

### Subprocess Crash Recovery

If a spawned subprocess crashes after initialization, the registry holds a dead
`_StdioMCPConnectionManager`. The next tool call will fail with a `McpError`. There is currently no
reconnect logic.

For production, detect `McpError` in `_MCPTool._run_in_stage_async` and evict + restart the manager
via the registry on the next request. In the container model a crashed subprocess is likely a fatal
error (provider misconfiguration or corrupt data); crashing the container and letting the orchestrator
restart it may be the correct response rather than silent retry.

---

## Summary: What Works Today vs. What Needs Work

| Concern | Status | Notes |
|---|---|---|
| Generic subprocess-mcp toolset type | ✅ Done | `env` and `args` substitution both work |
| Provider installed via npm in Dockerfile | ✅ Done | `mcp-server-memory`, `mcp-server-filesystem` |
| Bucket volume mount | ✅ Done (in docker-compose) | Convention: `DIAL_BUCKET_PATH=/data/bucket` |
| Per-user isolation | ✅ By container boundary | Works because one container = one user |
| Pre-existing directory creation | ⚠️ Manual today | See Option A — add to entrypoint |
| Graceful subprocess shutdown | ⚠️ Missing | Add lifespan hook |
| Subprocess crash recovery | ⚠️ Missing | No reconnect; crash = dead registry entry |
| Shared-service model (multiple users, one process) | ❌ Not implemented | Requires full `SubprocessPool` from the draft |
