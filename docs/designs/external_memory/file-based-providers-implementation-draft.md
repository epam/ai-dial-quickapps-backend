# File-Based Providers — Implementation Draft

- **Status:** Draft
- **Related:** [File-Based Providers](file-based-providers.md) | [Memory Provider Classification](memory-provider-classification.md)

---

## Scope

This document translates the conceptual design in `file-based-providers.md` into concrete code
changes. It describes every file that needs to be created or modified, with implementation sketches
for each.

---

## Prerequisites

`file-based-providers.md` has one open question that must be resolved first:

> **DIAL bucket as local path:** Is the DIAL bucket accessible as a local filesystem path, or does
> QuickApps sync files to/from DIAL storage?

The answer determines the value of `{{dial_bucket_path}}`:

- If DIAL storage is **mounted as a local volume** (e.g. via DIAL Files or a sidecar), `bucket_path`
  is a real filesystem path and all providers work as-is.
- If DIAL storage is **remote only** (HTTP API), a local scratch directory must be used and files
  synced to/from DIAL around the subprocess session. This is a more involved design and is **out of
  scope for this draft** — assume local-path access below.

`bucket_path` is resolved at request time:

```python
bucket_resp = await self.__dial_client.bucket.get_raw()
bucket_path = bucket_resp.appdata or bucket_resp.bucket
```

---

## Changes Required

The table below lists every file affected, whether it is new or modified, and the nature of the
change.

| File | New / Modified | Change |
|---|---|---|
| `config/toolsets/subprocess_mcp.py` | **New** | `SubprocessMCPToolSet` config model |
| `config/toolsets/__init__.py` or union type | **Modified** | Add `SubprocessMCPToolSet` to the toolset union |
| `mcp_tooling/_abstract_mcp_connection_manager.py` | **New** | Protocol / ABC shared by both connection manager types |
| `mcp_tooling/_stdio_mcp_connection_manager.py` | **New** | Long-lived stdio connection manager |
| `mcp_tooling/_subprocess_pool.py` | **New** | Per-user subprocess pool with TTL eviction |
| `mcp_tooling/_mcp_tool.py` | **Modified** | `connection_manager` type annotation → Protocol |
| `mcp_tooling/_mcp_tool_initializer.py` | **Modified** | New `SubprocessMCPToolSet` branch in `_process_toolset()` |
| `mcp_tooling/mcp_module.py` | **Modified** | Bind `SubprocessPool` as singleton in DI |

No changes to `StagedBaseTool`, the orchestrator, or any HTTP connection code.

---

## 1. Config Model — `SubprocessMCPToolSet`

**File:** `src/quickapp/config/toolsets/subprocess_mcp.py`

```python
from pydantic import BaseModel, ConfigDict


class SubprocessMCPToolSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["subprocess-mcp"]
    name: str
    command: str                        # CLI command installed in the image
    args: list[str] = []
    env: dict[str, str] = {}            # supports {{dial_bucket_path}} template
    enabled: bool = True
    pool_ttl_minutes: int = 10          # ignored in container model (single-entry pool)
    allowed_tools: list[str] | None = None
```

The `{{dial_bucket_path}}` substitution is performed in the initializer before the subprocess is
spawned — it is a plain string replacement, not a Jinja template.

---

## 2. Connection Manager Protocol

**File:** `src/quickapp/mcp_tooling/_abstract_mcp_connection_manager.py`

`_MCPTool` currently has a concrete `_MCPConnectionManager` type annotation. To support both
HTTP and stdio managers without changing `_MCPTool`'s logic, extract a minimal Protocol:

```python
from typing import Protocol
from mcp import Tool
from mcp.types import CallToolResult


class MCPConnectionManagerProtocol(Protocol):
    async def get_tools_list(self) -> list[Tool]: ...
    async def call_mcp_tool(self, tool_name: str, **kwargs) -> CallToolResult: ...
```

Both `_MCPConnectionManager` (HTTP) and `_StdioMCPConnectionManager` (stdio) satisfy this protocol
structurally — no changes to the existing class are needed.

**Modification in `_mcp_tool.py`:** change the `connection_manager` constructor parameter type
from `_MCPConnectionManager` to `MCPConnectionManagerProtocol`.

---

## 3. Stdio Connection Manager

**File:** `src/quickapp/mcp_tooling/_stdio_mcp_connection_manager.py`

The key difference from `_MCPConnectionManager`: the session must stay open across calls.
HTTP transports are stateless; stdio is a live process — closing the session kills it.

```python
import logging
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession, Tool
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

logger = logging.getLogger(__name__)


class _StdioMCPConnectionManager:
    """MCP connection manager for stdio subprocess providers (file-based memory servers).

    Holds a single long-lived ClientSession for the lifetime of this manager instance.
    Call start() before use; call stop() to cleanly terminate the subprocess.
    """

    def __init__(self, params: StdioServerParameters, timeout_seconds: float = 30.0):
        self._params = params
        self._timeout = timeout_seconds
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def start(self) -> None:
        """Spawn the subprocess and initialize the MCP session."""
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(stdio_client(self._params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        logger.debug("Stdio MCP session started: %s", self._params.command)

    async def stop(self) -> None:
        """Close the session and terminate the subprocess."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            logger.debug("Stdio MCP session stopped: %s", self._params.command)

    async def get_tools_list(self) -> list[Tool]:
        assert self._session is not None, "start() must be called before get_tools_list()"
        result = await self._session.list_tools()
        return result.tools

    async def call_mcp_tool(self, tool_name: str, **kwargs) -> CallToolResult:
        assert self._session is not None, "start() must be called before call_mcp_tool()"
        timeout = timedelta(seconds=self._timeout)
        return await self._session.call_tool(
            tool_name, kwargs or None, read_timeout_seconds=timeout
        )
```

---

## 4. Subprocess Pool

**File:** `src/quickapp/mcp_tooling/_subprocess_pool.py`

One pool instance lives as a DI singleton for the QuickApps process. It maps
`(user_id, toolset_name)` → `_StdioMCPConnectionManager` with TTL eviction.

```python
import asyncio
import logging
import time
from dataclasses import dataclass, field

from mcp.client.stdio import StdioServerParameters

from ._stdio_mcp_connection_manager import _StdioMCPConnectionManager

logger = logging.getLogger(__name__)

_PoolKey = tuple[str, str]  # (user_id, toolset_name)


@dataclass
class _PoolEntry:
    manager: _StdioMCPConnectionManager
    expires_at: float                   # monotonic time
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SubprocessPool:
    """Per-user subprocess pool for stdio MCP memory providers.

    In the shared-service model, one pool instance is shared across all requests.
    In the container model (one container = one user), the pool will always have
    exactly one entry that never expires — pool_ttl_minutes can be set to a very
    large value or the entry simply never evicts.
    """

    def __init__(self) -> None:
        self._entries: dict[_PoolKey, _PoolEntry] = {}
        self._global_lock = asyncio.Lock()

    async def get_or_create(
        self,
        user_id: str,
        toolset_name: str,
        params: StdioServerParameters,
        ttl_seconds: float,
        timeout_seconds: float = 30.0,
    ) -> _StdioMCPConnectionManager:
        key: _PoolKey = (user_id, toolset_name)
        now = time.monotonic()

        async with self._global_lock:
            entry = self._entries.get(key)
            if entry and time.monotonic() < entry.expires_at:
                entry.expires_at = now + ttl_seconds  # reset TTL on access
                return entry.manager

            # Evict stale entry if present
            if entry:
                await self._evict(key, entry)

            manager = _StdioMCPConnectionManager(params, timeout_seconds=timeout_seconds)
            await manager.start()
            self._entries[key] = _PoolEntry(
                manager=manager,
                expires_at=now + ttl_seconds,
            )
            return manager

    async def _evict(self, key: _PoolKey, entry: _PoolEntry) -> None:
        try:
            await entry.manager.stop()
        except Exception:
            logger.warning("Error stopping subprocess for key %s", key, exc_info=True)
        self._entries.pop(key, None)

    async def evict_expired(self) -> None:
        """Evict all expired entries. Call periodically from a background task."""
        now = time.monotonic()
        async with self._global_lock:
            expired = [k for k, e in self._entries.items() if now >= e.expires_at]
            for key in expired:
                await self._evict(key, self._entries[key])
```

> **Background eviction:** A periodic task should call `pool.evict_expired()` every few minutes.
> This can be wired in `app.py` as a background asyncio task or a FastAPI `lifespan` handler.

---

## 5. Initializer Branch

**File:** `src/quickapp/mcp_tooling/_mcp_tool_initializer.py`

Add a new branch in `_process_toolset()` for `SubprocessMCPToolSet`. The branch sits alongside
the existing `DialMCPToolSet` check. All downstream logic (tool listing → `_MCPTool` creation →
`mcp_context.extend_tools`) is identical.

```python
# New import at top of file
from quickapp.config.toolsets.subprocess_mcp import SubprocessMCPToolSet
from mcp.client.stdio import StdioServerParameters
from ._subprocess_pool import SubprocessPool

# In __init__, inject the pool:
#   subprocess_pool: SubprocessPool

async def _process_toolset(self, toolset_info: MCPToolSet | DialMCPToolSet | SubprocessMCPToolSet) -> None:
    if not toolset_info.enabled:
        return

    # --- existing DialMCPToolSet branch (unchanged) ---
    if isinstance(toolset_info, DialMCPToolSet):
        ...  # existing code

    # --- new SubprocessMCPToolSet branch ---
    elif isinstance(toolset_info, SubprocessMCPToolSet):
        bucket_path = await self._resolve_bucket_path()
        env = {
            k: v.replace("{{dial_bucket_path}}", bucket_path)
            for k, v in toolset_info.env.items()
        }
        params = StdioServerParameters(
            command=toolset_info.command,
            args=toolset_info.args,
            env=env,
        )
        connection_manager = await self.__subprocess_pool.get_or_create(
            user_id=self._current_user_id(),
            toolset_name=toolset_info.name,
            params=params,
            ttl_seconds=toolset_info.pool_ttl_minutes * 60,
        )
        tools = await connection_manager.get_tools_list()

    # --- existing MCPToolSet branch (unchanged) ---
    else:
        connection_manager = self.__connection_manager_builder.build(toolset_info=toolset_info)
        tools = await connection_manager.get_tools_list()

    # --- common tail: filter + build _MCPTool instances (unchanged) ---
    if toolset_info.allowed_tools:
        tools = [t for t in tools if t.name in toolset_info.allowed_tools]
    ...
```

`_resolve_bucket_path()` and `_current_user_id()` need access to the DIAL client and the
request-scoped user identity — both are already injectable via the existing DI graph.

---

## 6. DI Wiring

**File:** `src/quickapp/mcp_tooling/mcp_module.py`

Bind `SubprocessPool` as a singleton so the pool survives across requests:

```python
binder.bind(SubprocessPool, to=SubprocessPool, scope=singleton)
```

Add `SubprocessPool` as a constructor parameter of `_MCPToolInitializer`.

---

## What Does NOT Change

| Component | Why unchanged |
|---|---|
| `_MCPConnectionManager` (HTTP) | No modification — existing HTTP transports are unaffected |
| `_MCPTool` logic | Only the type annotation on `connection_manager` changes |
| `StagedBaseTool` | No modification — tool execution path is transport-agnostic |
| Orchestrator / hooks | No modification |
| Existing config models (`MCPToolSet`, `DialMCPToolSet`) | No modification |

---

## Data Flow Summary

```
Request arrives (user A, toolset: basic-memory)
  │
  ├─ _MCPToolInitializer._process_toolset(SubprocessMCPToolSet)
  │    ├─ resolve bucket_path  ← dial_client.bucket.get_raw()
  │    ├─ substitute {{dial_bucket_path}} in env
  │    ├─ SubprocessPool.get_or_create(user_id="A", toolset_name="memory", ...)
  │    │    ├─ pool hit  → return existing _StdioMCPConnectionManager (TTL reset)
  │    │    └─ pool miss → spawn "basic-memory mcp", initialize session, store in pool
  │    ├─ connection_manager.get_tools_list()  → list[Tool]
  │    └─ build _MCPTool per tool  → mcp_context.extend_tools(...)
  │
  ├─ Orchestrator loop: LLM calls e.g. "memory_search"
  │    └─ _MCPTool._run_in_stage_async()
  │         └─ connection_manager.call_mcp_tool("search", query="...")
  │              └─ _StdioMCPConnectionManager: session.call_tool(...)  ← reuses live session
  │
  └─ Response returned; subprocess stays alive in pool until TTL expires
```

---

## Open Questions (Remaining)

1. **DIAL bucket local path:** Confirmed assumption above — needs verification with the DIAL Files
   team that `bucket_resp.appdata` / `bucket_resp.bucket` is a local filesystem path accessible
   from within the QuickApps process/container.

2. **`_current_user_id()` in initializer:** The initializer needs the request-scoped user identity
   to key the pool. Confirm how user identity is currently surfaced in the DI graph at request scope
   (likely via `DIAL_API_KEY` or a dedicated request-scoped binding).

3. **Background eviction task:** How should `pool.evict_expired()` be wired? Options:
   - FastAPI `lifespan` background task (periodic `asyncio.sleep` loop)
   - Triggered on every `get_or_create` call (lazy eviction, simpler)

4. **mem0 local mode:** Still needs a custom `~100-line` MCP wrapper. Defer until there is
   operator demand — basic-memory covers most use cases without the LLM write dependency.

5. **Obsidian vault:** CLI arg instead of env var for the vault path. The `SubprocessMCPToolSet`
   `args` field supports this — `{{dial_bucket_path}}` substitution in `args` needs the same
   template logic applied to `env`. Minor extension.
