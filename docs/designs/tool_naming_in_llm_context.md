# Design: Tool Naming in LLM Context

**Status:** Draft\
**Issue:** [#200](https://github.com/epam/ai-dial-quickapps-backend/issues/200)

## Problem Statement

Tools sent to the LLM are currently named by `OpenAiToolFunction.set_name`, a Pydantic `@model_validator` that **always** appends a 4-char SHA-256 hash suffix to every tool name (e.g. `notion-search` → `notion-search_afc9`). This was intended as a preventive measure against name collisions across toolsets, but it has two concrete problems:

1. **Unnecessary pollution.** The hash is added regardless of whether any collision exists, making tool names harder to read in logs, traces, and LLM conversations.
2. **Duplicate-toolset failure.** When a user defines two identical tools (same name, same config), both tools have the same hash (because the hash is derived from tool content, not toolset identity). The LLM call fails with:
   ```
   openai.BadRequestError: Duplicate function declaration found: notion-search_afc9
   ```

QuickApps has a clear two-level abstraction — **toolsets → tools** — that can be used to produce semantically meaningful, collision-resistant names.

## Design Goals

- Tool names seen by the LLM include the toolset name as a prefix (e.g. `notion_search`), making the agent's context clearer.
- Two same tools in different toolsets (e.g. `weather_forecast` vs `maps_forecast`) no longer cause a `BadRequestError`.
- Internal tools (no user toolset) have meaningful prefixes that give the LLM context about the tool's origin and purpose.

---

## Use Cases

### UC-1: Single toolset — clean prefix

**Trigger:** Application is configured with one MCP toolset named `notion` that exposes a `search` tool.\
**Behavior:** The toolset module prefixes the tool name with the sanitized toolset name at creation time.\
**Outcome:** The LLM sees `notion_search` instead of `search_afc9`.

### UC-2: Two toolsets, distinct names — no collision

**Trigger:** Application has two REST API toolsets: `weather` with a `forecast` tool and `maps` with a `forecast` tool.\
**Behavior:** Each tool is prefixed with its toolset name at creation time.\
**Outcome:** The LLM sees `weather_forecast` and `maps_forecast` — no collision.

---

## Proposed Design

### 1. Remove preventive hashing (`OpenAiToolFunction.set_name`)

**What:** Remove the `@model_validator(mode='after') def set_name(self)` method from `OpenAiToolFunction` in `src/quickapp/config/tools/base.py`. Also remove the now-unused imports: `sha256` from `hashlib`, `json`, and `model_validator`.

**Owner:** `OpenAiToolFunction` (config layer).

**Semantics:** After this change, `OpenAiToolFunction.name` is stored exactly as provided by the caller. No hash is ever appended at construction time.

### 2. Prefix `function.name` at tool-creation time

Each toolset module prefixes the tool's `function.name` with `{toolset_name}_` and sanitizes the result when constructing the tool config. Internal tools (no user toolset) are renamed separately — see [Secondary Fixes](#rename-internal-tools-with-meaningful-prefixes).

**Separator: underscore (`_`)**

Both `_` and `-` are permitted by all providers (see [Tool Name Constraints by LLM Provider](#tool-name-constraints-by-llm-provider)). Underscore is chosen because:
- It is the dominant convention in examples across all providers (snake_case).
- It visually separates the toolset prefix from the tool name more clearly than hyphen, which is often used *within* a name segment (e.g., `my-tool`).
- It avoids ambiguity when the toolset or tool name itself contains hyphens (e.g., toolset `rest-api` + tool `get-user` → `rest_api_get_user` after sanitization, which is unambiguous).

| Module | Location | Change |
|--------|----------|--------|
| `rest_api_tooling/rest_api_tooling_module.py` | `__create_rest_api_tools` | Prefix `function.name` with toolset name via `model_copy` |
| `mcp_tooling/_mcp_tool_initializer.py` | `_process_toolset` | Pass prefixed name to `_convert_to_openai_tool` |
| `dial_deployment_tooling/_deployment_tool_initializer.py` | `initialize` | Prefix `function.name` with toolset name via `model_copy` |

Example for MCP:
```python
# in _mcp_tool_initializer.py, _process_toolset
prefixed_name = sanitize_toolname(f"{resolved_toolset.name}_{tool.name}")
MCPTool(
    open_ai_tool=self._convert_to_openai_tool(
        prefixed_name, tool.description, tool.inputSchema
    ),
    ...
)
```

**Semantics:** Prefixing at creation time means all downstream consumers — `provide_openai_tools`, `ToolExecutor.__build_tool_dict`, `_extract_tool_history` — see the final name from the start with no mutation side effects and no DI ordering dependency.

This is the correct place for prefixing because `ToolExecutor.__build_tool_dict` runs eagerly during `ToolExecutor.__init__`, which is injected as a concrete dependency into `Orchestrator.__init__`. `AssistantInvoker` (which triggers `provide_openai_tools`) is injected as `ProviderOf[AssistantInvoker]` and resolved lazily — after `ToolExecutor` has already built its name→tool dict. Mutating names in `provide_openai_tools` would therefore cause every tool lookup to return `None`.

### 3. Remove sanitization from `provide_openai_tools` and `ToolExecutor`

**What:** Remove the `sanitize_toolname` call from `AgentModule.provide_openai_tools` and from `ToolExecutor.__build_tool_dict`. Both sites currently sanitize names at consumption time; with sanitization moved to step 2, names are already final when these functions run.

**Owners:**
- `AgentModule.provide_openai_tools` in `src/quickapp/agent/agent_module.py`
- `ToolExecutor.__build_tool_dict` in `src/quickapp/agent/tool_executor.py`

**Semantics:** Tool names are immutable after creation. No mutation side effects in the agent layer; downstream consumers (`provide_openai_tools`, `__build_tool_dict`, `_extract_tool_history`) see the final name from the start.

---

## Secondary Fixes

### Rename internal tools with meaningful prefixes

Internal tool names currently use either a verbose `quickapps_internal_` prefix or no prefix at all. All internal tools are renamed to follow the pattern `internal_{module_concept}_{tool_name}`:

| Old name | New name | Module |
|----------|----------|--------|
| `quickapps_internal_available_context` | `internal_attachments_available_context` | `attachment_processing` |
| `quickapps_internal_current_timestamp` | `internal_timeawareness_current_timestamp` | `timestamp_tooling` |
| `python_code_interpreter` | `internal_code_execution_python_interpreter` | `internal_tooling` |
| `read_skill` | `internal_skills_read_skill` | `skills` |

The `INTERNAL_TOOL_NAME_PREFIX` constant in `src/quickapp/config/tools/internal.py` is removed — each module now defines its own tool name directly.

### Replace `model_construct` with normal construction in MCP tool initializer

`_MCPToolInitializer._convert_to_openai_tool` (line 104 of `src/quickapp/mcp_tooling/_mcp_tool_initializer.py`) uses `OpenAiToolFunction.model_construct(...)` to skip the `set_name` validator. With the validator removed, this should be changed to `OpenAiToolFunction(...)` to restore full Pydantic validation of other fields.

### Update stale comments in `_tool_configs.py` files

Two files have a comment that references the now-removed validator:
- `src/quickapp/attachment_processing/_tool_configs.py` — `# Tool name after hashing by OpenAiToolFunction.set_name validator`
- `src/quickapp/timestamp_tooling/_tool_configs.py` — `# Tool name after hashing by OpenAiToolFunction.set_name validator`

Both should be updated to: `# Tool name as sent to the LLM (sanitized, no hash)`.

---

## Out of Scope

### UC-3: Two toolsets with colliding names

**Trigger:** A user accidentally configures two toolsets that produce the same prefixed tool name (e.g. two `notion` toolsets both exposing `search`).
**Not handled:** The LLM provider will reject the call with `BadRequestError: Duplicate function declaration`. No additional detection or user-facing error is added by this design — that is a configuration mistake.

### REST API naming collision (POST vs GET on the same endpoint)

Not a problem: both operations are named via `toolset.name → openai.function.name`, so they get distinct names by construction.

### Sanitization edge cases

The following are not validated by this design and are considered misconfiguration:
- Toolset name that is empty or consists entirely of characters that sanitize away (e.g. `"---"`).
- Toolset name that produces an empty prefix after sanitization.
- Prefixed tool name that exceeds the 64-character provider limit.

In all these cases the LLM provider will return an error. Defensive validation of toolset names is deferred to a future hardening pass.

---

## Configuration / Usage Examples

**Input configuration** (single toolset, cross-toolset disambiguation, internal tool without prefix):
```json
{
  "tool_sets": [
    {
      "type": "mcp",
      "name": "notion",
      "tools": [
        {"name": "search", "description": "Search Notion pages"},
        {"name": "create_page", "description": "Create a Notion page"}
      ]
    },
    {
      "type": "rest_api",
      "name": "confluence",
      "tools": [
        {"name": "search", "description": "Search Confluence spaces"}
      ]
    }
  ],
  "internal_tools": ["python_interpreter"]
}
```

**Produced OpenAI tools payload:**

| Tool | Toolset | Raw name | After prefix + sanitize |
|------|---------|----------|------------------------|
| Notion search | `notion` | `search` | `notion_search` |
| Notion create | `notion` | `create_page` | `notion_create_page` |
| Confluence search | `confluence` | `search` | `confluence_search` |
| Python interpreter | *(none)* | `python_code_interpreter` | `internal_code_execution_python_interpreter` |

---

## Migration

### Breaking changes

None — no changes to the JSON config schema or public API.

### Observable changes (no action required from users)

- Tool names visible in LLM conversations, logs, and traces will change: hash suffixes are removed and toolset-name prefixes are added.
- Internal tool names are renamed with meaningful prefixes (e.g. `python_code_interpreter_f7a8` → `internal_code_execution_python_interpreter`).

**Test changes required:**

- **Rename** `src/tests/integration_tests/test_runner/utils/tool_names_with_hash.py` → `tool_names.py` and update all 3 import sites.
- **Update all tool name constants** in that file: remove hash suffixes and add `{toolset_name}_` prefix.
- **Update JSON test config files** (`test_rest_toolset.json`, `test_tool_set_py_interpreter.json`, `test_tool_set_chat_hub.json`, `test_mcp_tool.json`) — replace `function.name` values with the new format.
- **Source-level constants** (`AVAILABLE_CONTEXT_TOOL_NAME`, `CURRENT_TIMESTAMP_TOOL_NAME`, `SKILL_READER_TOOL_NAME`) are derived from the tool config (`= TOOL_CONFIG.open_ai_tool.function.name`), so they update automatically — no manual changes needed.
- **No cache regeneration needed** — the integration test cache stores tool deployment responses (e.g. image generation, web search). Tool names appear only in orchestrator requests, which are never cached (orchestrator models are in `AGENT_MODELS` and always proxied live). Renaming tools does not affect any cached `.response` files.

---

## Summary of Changes

### `src/quickapp/config/tools/base.py`
- **Removed:** `OpenAiToolFunction.set_name` model validator (and `sha256`, `json`, `model_validator` imports).

### `src/quickapp/rest_api_tooling/rest_api_tooling_module.py`
- **Modified:** `__create_rest_api_tools` — prefixes `function.name` with the toolset name at tool-creation time.

### `src/quickapp/mcp_tooling/_mcp_tool_initializer.py`
- **Modified:** `_process_toolset` — passes prefixed name to `_convert_to_openai_tool`.
- **Modified:** `_convert_to_openai_tool` — replaces `OpenAiToolFunction.model_construct(...)` with normal `OpenAiToolFunction(...)` construction.

### `src/quickapp/dial_deployment_tooling/_deployment_tool_initializer.py`
- **Modified:** `initialize` — prefixes `function.name` with the toolset name at tool-creation time.

### `src/quickapp/agent/agent_module.py`
- **Modified:** `provide_openai_tools` — remove `sanitize_toolname` call (names are already sanitized at creation time).

### `src/quickapp/agent/tool_executor.py`
- **Modified:** `__build_tool_dict` — remove `sanitize_toolname` call (names are already sanitized at creation time).

### `src/quickapp/config/tools/internal.py`
- **Removed:** `INTERNAL_TOOL_NAME_PREFIX` constant (each module now defines its own tool name directly).

### `src/quickapp/attachment_processing/_tool_configs.py`
- **Modified:** Tool name changed to `internal_attachments_available_context`. Stale comment updated.

### `src/quickapp/timestamp_tooling/_tool_configs.py`
- **Modified:** Tool name changed to `internal_timeawareness_current_timestamp`. Stale comment updated.

### `config/predefined/tool/py_interpreter.json`
- **Modified:** Tool name changed to `internal_code_execution_python_interpreter`.

### `src/quickapp/skills/_tool_configs.py`
- **Modified:** Tool name changed to `internal_skills_read_skill`. `SKILL_READER_TOOL_NAME_PREFIX` constant updated accordingly.

### `src/tests/unit_tests/common/test_set_name_validator.py`
- **Deleted:** Tests the removed `set_name` behavior.

### `src/tests/integration_tests/test_runner/utils/tool_names_with_hash.py`
- **Renamed** to `tool_names.py`. All tool name constants updated to `{toolset_name}_{tool_name}` format (no hash). Import sites in 3 integration test files updated accordingly.

---

## Additional materials
### Tool Name Constraints by LLM Provider

Research into official documentation across major LLM providers reveals the following constraints on tool/function names:

| Provider | Allowed Pattern | Max Length | Enforcement |
|----------|----------------|------------|-------------|
| **OpenAI** | `^[a-zA-Z0-9_-]{1,64}$` | 64 | Strict (API error on violation) |
| **Anthropic Claude** | `^[a-zA-Z0-9_-]{1,64}$` | 64 | Strict; "anthropic" and "claude" are reserved |
| **AWS Bedrock** | `[a-zA-Z0-9_-]+` | 64 | Strict (API error on violation) |
| **Google Gemini** | Not formally documented | Not documented | Flexible; examples use camelCase and snake_case |
| **Mistral AI** | Not formally documented | Not documented | Snake_case recommended in examples |
| **Cohere** | Not formally documented | Not documented | Minimal constraints documented |
| **Groq** | Not formally documented | Not documented | Flexible |

The three providers with formally enforced constraints (OpenAI, Anthropic, AWS Bedrock) all converge on **`^[a-zA-Z0-9_-]{1,64}$`** — alphanumerics, underscores, and hyphens, up to 64 characters. The remaining providers use the same character set in their examples. This pattern is therefore the safe, universal target for any tool name sent to the LLM.
