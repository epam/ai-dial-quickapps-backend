# Sub-Stage Propagation

**Status:** Draft  
**Author:** Aleksei Korota

---

## Problem

When a QuickApp calls another QuickApp as a tool, the sub-app's UI stages are silently discarded — the user sees only an empty "Calling X" stage with no indication of what the sub-app is actually doing.

---

## Root Cause

`DialCompletionService._consume_stream()` constructs `ChatStreamConfig` without a `destination` and without `propagate_stages=True`. As a result, `ChoiceUiSink` is instantiated but completely inert: it parses the sub-app's stage deltas into `ChatStreamAccumulator.stages` but never forwards them to the parent `Choice`. The accumulated stages are never read by `complete_request_async()` and are effectively thrown away.

```
BaseDeploymentTool
  └─ DialCompletionService._consume_stream()
       └─ ChatStreamConfig(stage_wrapper=...) ← no destination, no propagate_stages
            └─ ChoiceUiSink(destination=None)  ← inert, sub-app stages discarded
```

The sub-app's **text content** does reach the parent (via `StageWrapperUiSink`), so the "Calling X" stage renders the response text. Only stage deltas from the sub-app's `custom_content.stages` are lost.

---

## Approach 1 — Flat Propagation (short-term)

Sub-app stages are re-emitted into the parent's flat stage list with a name prefix that indicates their origin. No SDK or UI changes required.

### Mechanism

1. Inject `Choice` (already request-scoped) into `DialCompletionService`.
2. Pass it as `destination` and set `propagate_stages=True` in `_consume_stream`.
3. Thread a `sub_stage_prefix` string (e.g. `"[WeatherApp]"`) from `BaseDeploymentTool` through `ChatStreamConfig` to `ChoiceUiSink._stream_stage_delta()`, where it is prepended to the stage name on creation.

For deep nesting (A → B → C), C's stages reach A's stream as siblings of B's stages, all with their respective prefixes. The feature is gated by a new `PreviewField` on `ApplicationConfig` (`orchestrator.propagate_sub_stages`, default `true`) and by the existing `ENABLE_PREVIEW_FEATURES` env switch.

### Stage index safety

`ChoiceUiSink` tracks sub-app stage indices in a local `_stages_by_index` dict. Actual allocation is done through `destination.create_stage()`, which increments `Choice._last_stage_index` independently — no collision with the parent's own stages.

### Files changed

| File | Change |
|------|--------|
| `config/application.py` | `PreviewField` `orchestrator.propagate_sub_stages: bool` |
| `dial_deployment_tooling/dial_completion_service.py` | Inject `Choice`; pass `destination` + prefix to `_consume_stream` |
| `dial_deployment_tooling/base_deployment_tool.py` | Pass `application_name` as prefix to `complete_request_async` |
| `common/chat_completion_stream/handler.py` | Add `sub_stage_prefix: str | None` to `ChatStreamConfig` |
| `common/chat_completion_stream/chat_stream_sink_factory.py` | Forward `sub_stage_prefix` to `ChoiceUiSink` |
| `common/chat_completion_stream/choice_ui_stream_sink.py` | Prepend prefix in `_stream_stage_delta` |

### Trade-offs

**Pros:** No SDK bump, no UI changes, deployable today.  
**Cons:** Flat list without structural hierarchy; deep nesting produces a long undifferentiated list.

---

## Approach 2 — Nested Stages (target architecture)

Sub-app stages are re-emitted as children of the open "Calling X" stage, preserving the call hierarchy at any depth. Requires changes to `aidial_sdk` and a wire-format contract that the UI team must implement.

### Wire format change (`aidial_sdk`)

A new optional field `parent_stage_index` is added to `StartStageChunk`. When present, the UI renders the stage as a child of the referenced stage rather than a top-level sibling.

**Before:**
```json
{"custom_content": {"stages": [
  {"index": 0, "name": "Calling WeatherApp", "status": null},
  {"index": 1, "name": "Fetching forecast",  "status": null}
]}}
```

**After:**
```json
{"custom_content": {"stages": [
  {"index": 0, "name": "Calling WeatherApp", "status": null},
  {"index": 1, "name": "Fetching forecast", "parent_stage_index": 0, "status": null}
]}}
```

`parent_stage_index` is omitted for top-level stages (backwards-compatible). `FinishStageChunk`, `ContentStageChunk`, `NameStageChunk`, and `AttachmentStageChunk` are identified by `index` alone and require no changes.

### SDK API

Two additions to `aidial_sdk`:

```python
# Option A — factory method on Stage
child = parent_stage.create_child_stage("Fetching forecast")

# Option B — optional parameter on Choice.create_stage
child = choice.create_stage("Fetching forecast", parent=parent_stage)
```

`Stage._stage_index` is exposed as a read-only property `Stage.stage_index`. `StartStageChunk.__init__` accepts `parent_stage_index: int | None = None` and includes it in `to_dict()` via `remove_nones`.

### Mechanism (backend)

1. `BaseStageWrapper` adds `@property stage -> Stage` to expose its private `self.__stage`.
2. `BaseDeploymentTool._run_in_stage_async()` passes `stage_wrapper.stage` to `complete_request_async()` as a new `parent_stage: Stage | None` parameter.
3. `DialCompletionService._consume_stream()` forwards `parent_stage` in `ChatStreamConfig`.
4. `ChoiceUiSink` receives `parent_stage` and uses it when re-emitting sub-app stages:
   - Top-level sub-stages (no `parent_stage_index` in delta): created with `parent=parent_stage`.
   - Nested sub-stages (`parent_stage_index` present): remapped through the local `_stages_by_index` dict to find the `Stage` object created in the parent context, then passed as `parent=`.

The `_stages_by_index` dict (already maintained by `ChoiceUiSink`) naturally handles arbitrary recursion depth: each level's index space is remapped independently as it is processed.

The feature is gated identically to Approach 1 (`PreviewField` + `ENABLE_PREVIEW_FEATURES`).

### UI contract (for the UI team)

The UI must:
- Accept `parent_stage_index: number | undefined` on each stage object in `custom_content.stages`.
- Build a tree from stage deltas as they arrive in the stream: when `parent_stage_index` is set, attach the stage as a child of the already-opened stage at that index.
- Render nested stages as collapsible sections inside their parent stage.
- Treat absent `parent_stage_index` as a top-level stage (no behaviour change for existing flat streams).

### Files changed

**`aidial_sdk`:**

| File | Change |
|------|--------|
| `chat_completion/chunks.py` | `StartStageChunk`: add `parent_stage_index: int | None`; update `to_dict` |
| `chat_completion/stage.py` | Add `parent_stage_index` param; expose `stage_index` property |
| `chat_completion/choice.py` | `create_stage()`: add `parent: Stage | None = None` |

**`quickapps-backend`:**

| File | Change |
|------|--------|
| `config/application.py` | `PreviewField` `orchestrator.propagate_sub_stages: bool` |
| `common/_stage_delta_types.py` | Add `parent_stage_index` to `StageDeltaItem` TypedDict |
| `common/base_stage_wrapper.py` | Add `@property stage -> Stage` |
| `dial_deployment_tooling/base_deployment_tool.py` | Pass `stage_wrapper.stage` as `parent_stage` |
| `dial_deployment_tooling/dial_completion_service.py` | Add `parent_stage` param; forward to `_consume_stream` |
| `common/chat_completion_stream/handler.py` | Add `parent_stage: Stage | None` to `ChatStreamConfig` |
| `common/chat_completion_stream/chat_stream_sink_factory.py` | Forward `parent_stage` to `ChoiceUiSink` |
| `common/chat_completion_stream/choice_ui_stream_sink.py` | Index remapping + `parent=` on `create_stage` |

### Trade-offs

**Pros:** Correct structural representation; scales cleanly to arbitrary nesting depth.  
**Cons:** Requires SDK version bump and UI-team implementation of tree rendering.

---

## Scale of changes

| | `aidial_sdk` | `quickapps-backend` |
|---|---|---|
| Approach 1 | — | 6 files, ~40 lines |
| Approach 2 | 3 files, ~40 lines | 8 files, ~80 lines |
