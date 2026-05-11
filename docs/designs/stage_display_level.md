# Design: Stage Display Level

- **Status:** Draft
- **Dependencies:**
  - None

## Problem Statement

`StagedBaseTool.arun()` currently has two independent mechanisms to suppress stage rendering:

1. `display.stage.show = false` in tool config — a manifest-level flag to permanently hide a stage.
2. `suppress_stage: bool = False` at the call site — a runtime flag introduced when hooks/synthetic injections were implemented, to hide stages for background tool calls that the user should never see.

The second mechanism is a crutch: it encodes a semantic concept ("this is an internal system call") as a boolean, mixed in with user-facing display config. There is no way to reveal system stages for debugging, and no clear model to extend if more visibility tiers are needed.

## Design Goals

- Replace `suppress_stage: bool` with a typed `StageLevel` enum that expresses *why* a call is hidden, not just *that* it is hidden.
- Add a per-quickapp `stage_display_level` config field that acts as a threshold, analogous to Python's logging levels.
- In `VERBOSE` mode, all stages are shown regardless of tool config or call-site level — enabling manifest authors to debug internal tool calls.
- In `DEFAULT` mode, existing behavior is preserved: system stages are hidden, user stages follow `display.stage.show`.
- No breaking changes to existing manifests (default values preserve current behavior).

---

## Use Cases

### UC-1: Normal operation (default mode)

**Trigger:** A quickapp with no `stage_display_level` set processes a user message. The agent calls a REST tool (user-facing) and a hook fires a synthetic tool call in the background.
**Behavior:** The REST tool renders its stage. The synthetic call is made with `stage_level=StageLevel.SYSTEM` and no stage is created.
**Outcome:** The user sees only the REST tool stage.

### UC-2: Debugging internal tool calls

**Trigger:** A manifest author sets `stage_display_level: verbose` to investigate what a hook's tool call is doing.
**Behavior:** `StagedBaseTool` detects `VERBOSE` mode and skips all suppression logic. Every tool call — including synthetic/system ones — gets a stage wrapper.
**Outcome:** The user sees stages for all tool calls, including background hook invocations.

### UC-3: Tool with `display.stage.show = false` in verbose mode

**Trigger:** Same as UC-2, but one tool has `display.stage.show: false` in its config.
**Behavior:** `VERBOSE` overrides `display.stage.show`. The stage is shown anyway.
**Outcome:** The manifest author sees all stages, confirming verbose truly overrides all suppression.

---

## Proposed Design

### 1. `StageDisplayLevel` enum (config layer)

A new string enum added to `src/quickapp/config/application.py`:

```python
class StageDisplayLevel(str, Enum):
    DEFAULT = "default"
    VERBOSE = "verbose"
```

**What:** Per-quickapp display threshold. Manifest-facing (serializable to JSON).
**Owner:** `OrchestratorConfig`.
**Semantics:** `DEFAULT` — system stages hidden, user stages follow `display` config. `VERBOSE` — all stages shown, all suppression bypassed.
**Change:** New field on `OrchestratorConfig`:

```python
stage_display_level: StageDisplayLevel = StageDisplayLevel.DEFAULT
```

Placed alongside the existing `propagate_stages: bool` field, which is conceptually related (both control orchestrator-level stage rendering behavior).

---

### 2. `StageLevel` enum (internal call-site marker)

A new string enum in `src/quickapp/common/staged_base_tool.py`:

```python
class StageLevel(str, Enum):
    USER = "user"     # normal user-facing tool call
    SYSTEM = "system" # background/synthetic call (hooks, synthetic injections)
```

**What:** Call-site marker for individual `arun()` invocations.
**Owner:** Callers of `StagedBaseTool.arun()`.
**Semantics:** `USER` is the default. `SYSTEM` marks calls that should be invisible to users in normal operation.
**Change:** Never appears in the manifest — purely internal.

---

### 3. DI binding for `StageDisplayLevel`

A new request-scoped provider in `src/quickapp/application/app_module.py`:

```python
@provider
@request
def __provide_stage_display_level(
    self, app_config: ApplicationConfig
) -> StageDisplayLevel:
    return app_config.orchestrator.stage_display_level
```

**What:** Exposes the resolved `StageDisplayLevel` as an injectable token.
**Owner:** `AppModule`.
**Semantics:** Follows the same pattern as `__provide_application_config`. Resolved once per request from the parsed manifest.
**Change:** New provider method; no changes to existing providers.

---

### 4. `StagedBaseTool` — constructor and `arun()` changes

**Constructor:** Add `stage_display_level: StageDisplayLevel` as an injected dependency:

```python
def __init__(
    self,
    stage_wrapper_builder: AssistedBuilder[BaseStageWrapper],
    perf_timer: PerformanceTimer,
    tool_config: _BaseToolConfig,
    stage_display_level: StageDisplayLevel,
    argument_transformers: list[ToolArgumentTransformer] | None = None,
    **kwargs,
):
    ...
    self.__stage_display_level = stage_display_level
```

Since `StagedBaseTool` is constructed via `AssistedBuilder`, `stage_display_level` is a regular injected (non-assisted) dependency — the injector resolves it automatically.

**`arun()` signature:** Replace `suppress_stage: bool = False` with `stage_level: StageLevel = StageLevel.USER`.

**`arun()` suppression logic:**

```python
async def arun(
    self,
    tool_call_id: str,
    *args: Any,
    stage_level: StageLevel = StageLevel.USER,
    **kwargs: Any,
) -> ToolCallResult:
    verbose = self.__stage_display_level == StageDisplayLevel.VERBOSE
    display = self._tool_config.display

    suppress = not verbose and (
        stage_level == StageLevel.SYSTEM
        or (display and display.stage and not display.stage.show)
    )

    if suppress:
        return await self._run_in_stage_report_success(tool_call_id, None, *args, **kwargs)

    stage_wrapper = self.__stage_wrapper_builder.build(
        tool_config=self._tool_config,
        stage_name=self.stage_name_component,
    )
    ...
```

**Suppression truth table:**

| `stage_display_level` | `stage_level` | `display.stage.show` | Result |
|---|---|---|---|
| `DEFAULT` | `SYSTEM` | any | suppressed |
| `DEFAULT` | `USER` | `False` | suppressed |
| `DEFAULT` | `USER` | `True` / unset | shown |
| `VERBOSE` | any | any | shown |

---

### 5. Call-site migration

The only existing call site of `suppress_stage=True` is `StagedToolSyntheticInjector`:

```python
# src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py

# Before
result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, suppress_stage=True, **arguments)

# After
result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, stage_level=StageLevel.SYSTEM, **arguments)
```

---

## Out of Scope

- **More than two levels** (e.g. `INFO`, `DEBUG`, `TRACE`): not needed now. The two-level model covers all current use cases. The enum is extensible if needed later.
- **Per-tool-set `stage_display_level`**: granularity within a single quickapp is not a current requirement. Top-level config is sufficient.
- **Env-variable override**: a global `STAGE_DISPLAY_LEVEL` env var was considered but rejected — per-quickapp config gives manifest authors finer control without requiring ops involvement.

---

## Configuration / Usage Examples

**Default (no change required for existing manifests):**
```json
{
  "orchestrator": {
    "deployment": { ... },
    "system_prompt": { ... }
  }
}
```
System stages are hidden; user stages follow per-tool `display` config. Identical to current behavior.

**Enable verbose mode for debugging:**
```json
{
  "orchestrator": {
    "deployment": { ... },
    "system_prompt": { ... },
    "stage_display_level": "verbose"
  }
}
```
All stages shown, including hook/synthetic calls.

---

## Migration

### Breaking changes

None. `suppress_stage` is an internal `arun()` parameter, not part of the public manifest schema. The single call site (`StagedToolSyntheticInjector`) is updated as part of this change.

### Non-breaking changes

- `stage_display_level` defaults to `"default"`, preserving current behavior for all existing manifests.
- `display.stage.show = false` continues to work as before in `DEFAULT` mode.

---

## Summary of Changes

| Component | Change |
|---|---|
| `src/quickapp/config/application.py` | Add `StageDisplayLevel` enum; add `stage_display_level: StageDisplayLevel` field to `OrchestratorConfig` |
| `src/quickapp/application/app_module.py` | Add `@provider @request` for `StageDisplayLevel` |
| `src/quickapp/common/staged_base_tool.py` | Add `StageLevel` enum; inject `stage_display_level`; replace `suppress_stage: bool` with `stage_level: StageLevel` on `arun()`; rewrite suppression condition |
| `src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py` | Replace `suppress_stage=True` with `stage_level=StageLevel.SYSTEM` |
