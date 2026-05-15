# Design: Stage Display Level

- **Status:** Approved
- **Approved:** 2026-05-15
- **Dependencies:**
  - None

## Problem Statement

`StagedBaseTool.arun()` currently has two independent mechanisms to suppress stage rendering:

1. `display.stage.show = false` in tool config — a manifest-level flag to permanently hide a stage.
2. `suppress_stage: bool = False` at the call site — a runtime flag introduced when hooks/synthetic injections were implemented, to hide stages for background tool calls that the user should never see.

Both mechanisms are blunt: they are binary (show/hide), encode no semantic reason for suppression, and offer no way to control visibility across different audiences (end user vs. manifest author debugging). There is no way to reveal system stages for debugging, no way to show only error stages for triage, and no clear model to extend if more visibility tiers are needed.

## Design Goals

- Replace `suppress_stage: bool` with a typed `StageLevel` enum that expresses *why* a call is at a given visibility tier.
- Add a per-quickapp `StageDisplayConfig` nested inside the existing `Features` config, holding a `level` field that acts as a threshold, analogous to Python's logging levels.
- Define three ordered levels — `errors`, `info`, `debug` — where each level includes all lower levels.
- In `debug` mode, all stages are shown regardless of tool config or call-site level — enabling manifest authors to see every internal tool call.
- In `info` mode (default), error stages and user-facing tool call stages are shown; system/background stages are hidden.
- In `errors` mode, only error stages (tool failures and initializer errors) are shown.
- Deprecate (but not remove) `display.stage.show` — it continues to function but is superseded by the level model.
- No breaking changes to existing manifests (default values preserve current behavior).

---

## Use Cases

### UC-1: Normal operation (default `info` mode)

**Trigger:** A quickapp with no `features.stage_display.level` set processes a user message. The agent calls a REST tool (user-facing) and a hook fires a synthetic tool call in the background.
**Behavior:** The REST tool renders its stage. The synthetic call is made with `stage_level=StageLevel.SYSTEM` and no stage is created.
**Outcome:** The user sees only the REST tool stage. Identical to current behavior.

### UC-2: Triage mode — only errors

**Trigger:** A manifest author sets `features.stage_display.level: errors` to reduce noise and see only failures.
**Behavior:** User-facing tool call stages are suppressed. Only stages emitted with `stage_level=StageLevel.ERROR` (tool failures) are rendered.
**Outcome:** The user sees only error stages, making failures immediately visible without noise from successful calls.

### UC-3: Debugging internal tool calls (`debug` mode)

**Trigger:** A manifest author sets `features.stage_display.level: debug` to investigate what a hook's tool call is doing.
**Behavior:** `StagedBaseTool` detects `DEBUG` mode and renders stages for every tool call — including synthetic/system ones.
**Outcome:** The manifest author sees all stages, including background hook invocations.

### UC-4: Tool with deprecated `display.stage.show = false` in `debug` mode

**Trigger:** Same as UC-3, but one tool has `display.stage.show: false` in its config.
**Behavior:** `debug` level overrides `display.stage.show`. The stage is shown anyway.
**Outcome:** The manifest author sees all stages. `debug` truly overrides all suppression, including the deprecated flag.

---

## Proposed Design

### 1. `StageDisplayLevel` enum and `StageDisplayConfig` class (config layer)

New types added to `src/quickapp/config/application.py`:

```python
class StageDisplayLevel(str, Enum):
    ERRORS = "errors"
    INFO = "info"
    DEBUG = "debug"


class StageDisplayConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: StageDisplayLevel = StageDisplayLevel.INFO
```

**What:** Per-quickapp display threshold. Manifest-facing (serializable to JSON).
**Owner:** `Features` (existing top-level config class).
**Semantics:**
- `errors` — only `ERROR`-level stages shown.
- `info` — `ERROR` and `USER`-level stages shown; `SYSTEM` hidden. *(default)*
- `debug` — all stages shown; all suppression bypassed.

**Change:** New field on the existing `Features` class:

```python
class Features(BaseModel):
    timestamp: TimestampConfig | None = Field(...)
    file_loading: FileLoadingConfig = Field(...)
    stage_display: StageDisplayConfig = Field(
        default_factory=StageDisplayConfig,
        description="Controls which stage levels are rendered to the user.",
    )
```

---

### 2. `StageLevel` enum (internal call-site marker)

A new string enum in `src/quickapp/common/staged_base_tool.py`:

```python
class StageLevel(str, Enum):
    ERROR = "error"   # tool failure or initializer error — shown at all display levels
    USER = "user"     # normal user-facing tool call — shown at info and debug
    SYSTEM = "system" # background/synthetic call (hooks, synthetic injections) — shown at debug only
```

**What:** Call-site marker for individual `arun()` invocations (and error-emitting paths).
**Owner:** Callers of `StagedBaseTool.arun()` and error-reporting code in initializers.
**Semantics:** `USER` is the default. `SYSTEM` marks background calls. `ERROR` marks failure stages that should surface regardless of noise level.
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
    features = app_config.features
    return features.stage_display.level if features else StageDisplayLevel.INFO
```

**What:** Exposes the resolved `StageDisplayLevel` as an injectable token.
**Owner:** `AppModule`.
**Change:** New provider method; no changes to existing providers.

---

### 4. `StagedBaseTool` — constructor and `arun()` changes

**Constructor:** `StagedBaseTool` accepts `stage_display_level: StageDisplayLevel` as a plain constructor parameter (no default). Because the `injector` library only injects into the top-level instantiated class, the DI binding cannot be placed on `StagedBaseTool` directly. Instead, each concrete subclass declares `stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO` in its own `__init__` (where `@inject` applies) and forwards it to `super().__init__()`:

```python
# StagedBaseTool — receives the value, does not inject it
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


# Concrete tool (e.g. RestApiTool) — injected here, forwarded to super
def __init__(
    self,
    ...,
    stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
    argument_transformers: list[ToolArgumentTransformer] | None = None,
):
    super().__init__(
        ...,
        stage_display_level=stage_display_level,
        argument_transformers=argument_transformers,
    )
```

Affected subclasses: `RestApiTool`, `McpTool`, `DialDeploymentTool`, `AvailableContextTool`, `SkillReaderTool`, `CurrentTimestampTool`, `PyInterpreterTool`.

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
    suppress = self.__should_suppress(stage_level)

    if suppress:
        return await self._run_in_stage_report_success(tool_call_id, None, *args, **kwargs)

    stage_wrapper = self.__stage_wrapper_builder.build(
        tool_config=self._tool_config,
        stage_name=self.stage_name_component,
    )
    ...


def __should_suppress(self, stage_level: StageLevel) -> bool:
    level = self.__stage_display_level

    if level == StageDisplayLevel.DEBUG:
        return False

    if stage_level == StageLevel.ERROR:
        return False

    if stage_level == StageLevel.SYSTEM:
        return True

    # USER stage_level from here
    if level == StageDisplayLevel.ERRORS:
        return True

    # INFO level: also check deprecated display.stage.show
    display = self._tool_config.display
    if display and display.stage and not display.stage.show:
        return True

    return False
```

**Suppression truth table:**

| `stage_display_level` | `stage_level` | `display.stage.show` | Result |
|---|---|---|---|
| `errors` | `ERROR` | any | shown |
| `errors` | `USER` | any | suppressed |
| `errors` | `SYSTEM` | any | suppressed |
| `info` | `ERROR` | any | shown |
| `info` | `USER` | `True` / unset | shown |
| `info` | `USER` | `False` (deprecated) | suppressed |
| `info` | `SYSTEM` | any | suppressed |
| `debug` | any | any | shown |

---

### 5. Call-site migration

**Synthetic injector** — the only existing `suppress_stage=True` call site:

```python
# src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py

# Before
result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, suppress_stage=True, **arguments)

# After
result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, stage_level=StageLevel.SYSTEM, **arguments)
```

---

### 6. Deprecation of `display.stage.show`

`display.stage.show = false` continues to function at the `info` level (for backward compatibility), but is superseded by the `stage_level` call-site marker. Manifest authors should migrate by:

- Removing `display.stage.show: false` from tool configs.
- Ensuring callers pass the appropriate `StageLevel` (e.g., `SYSTEM` for background calls).

A deprecation warning should be logged when `display.stage.show = false` is encountered during config parsing.

---

## Out of Scope

- **Additional levels beyond three** (`trace`, `warn`, etc.): not needed now. The three-level model covers all current use cases.
- **Per-tool-set `stage_display_level`**: granularity within a single quickapp is not a current requirement. Top-level `features` config is sufficient.
- **Env-variable override**: a global env var was considered but rejected — per-quickapp config gives manifest authors finer control without requiring ops involvement.
- **Initializer error stages**: toolset initializers write failure stages directly to a raw `Stage` object, bypassing `StagedBaseTool.arun()` entirely. These stages are unconditionally shown and are not gated by the `StageDisplayLevel` threshold.

---

## Configuration / Usage Examples

**Default (no change required for existing manifests):**
```json
{
  "orchestrator": { ... }
}
```
System stages hidden; user stages shown. Identical to current behavior.

**Errors only — surface failures without noise:**
```json
{
  "orchestrator": { ... },
  "features": {
    "stage_display": { "level": "errors" }
  }
}
```

**Debug — see all stages including hooks and synthetic injections:**
```json
{
  "orchestrator": { ... },
  "features": {
    "stage_display": { "level": "debug" }
  }
}
```

---

## Migration

### Breaking changes

None. `suppress_stage` is an internal `arun()` parameter, not part of the public manifest schema. The single call site (`StagedToolSyntheticInjector`) is updated as part of this change.

### Non-breaking changes

- `features.stage_display.level` defaults to `"info"`, preserving current behavior for all existing manifests.
- `display.stage.show = false` continues to work as before at `info` level (deprecated but not removed).

---

## Summary of Changes

| Component | Change |
|---|---|
| `src/quickapp/config/application.py` | Add `StageDisplayLevel` enum; add `StageDisplayConfig` class; add `stage_display: StageDisplayConfig` field to `Features` |
| `src/quickapp/application/app_module.py` | Add `@provider @request` for `StageDisplayLevel` |
| `src/quickapp/common/staged_base_tool.py` | Add `StageLevel` enum; accept `stage_display_level` as a constructor param (not injected — see note in §4); replace `suppress_stage: bool` with `stage_level: StageLevel` on `arun()`; rewrite suppression condition |
| Each concrete tool subclass (`RestApiTool`, `McpTool`, `DialDeploymentTool`, `AvailableContextTool`, `SkillReaderTool`, `CurrentTimestampTool`, `PyInterpreterTool`) | Add `stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO` to `__init__` (DI entry point); forward to `super().__init__()` |
| `src/quickapp/common/synthetic_injection/staged_tool_synthetic_injector.py` | Replace `suppress_stage=True` with `stage_level=StageLevel.SYSTEM` |
