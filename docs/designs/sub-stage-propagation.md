# Sub-Stage Propagation

**Status:** Draft  
**Author:** Aleksei Korota

---

## Problem

When a QuickApp calls another QuickApp as a tool, the sub-app's UI stages are silently discarded — the user sees only an empty "Calling X" stage with no indication of what the sub-app is actually doing.

---

## Root Cause

`DialCompletionService._consume_stream()` constructs `ChatStreamConfig` without a `destination` and without `propagate_stages=True`. As a result, `ChoiceUiSink` is instantiated but completely inert — its `on_delta()` returns immediately when `destination is None`. The sub-app's stage deltas are accumulated into `ChatStreamAccumulator.stages` by `AccumulationSink`, but `complete_request_async()` never reads that field, so the stages are effectively thrown away.

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

---

## Review Notes — Round 1

- **Reviewer:** Claude (quickapps-design-review skill)
- **Date:** 2026-09-04

### Verdict

Blocking issues must be addressed.

The root cause description contains a factual inaccuracy that would mislead implementors, and the document presents two competing approaches without declaring which is the proposal. Structurally, the doc is missing five required sections from the template. Once a single approach is chosen and the structural gaps are filled, this should be straightforward to bring to approval.

### Blocking issues

1. **Root Cause** — The doc states: "ChoiceUiSink is instantiated but completely inert: it parses the sub-app's stage deltas into `ChatStreamAccumulator.stages` but never forwards them to the parent `Choice`." Both claims are wrong. `ChoiceUiSink.on_delta()` returns immediately when `destination is None` (`choice_ui_stream_sink.py`, line 80) — it does not parse or accumulate anything in the deployment path. The accumulation of stage deltas into `ChatStreamAccumulator.stages` is performed by `AccumulationSink.on_delta()` (`common/chat_completion_stream/accumulation_stream_sink.py`, lines 23–24), a separate sink that always runs. An implementor reading the doc and then the code will not find accumulation logic in `ChoiceUiSink` and may look in the wrong place for the fix.
   **Suggestion:** Revise the root cause to attribute stage accumulation to `AccumulationSink`. Describe `ChoiceUiSink` as inert in the deployment path because `on_delta` short-circuits at `destination is None` before it ever reaches `_apply_custom` — the pipeline runs, stages are accumulated by `AccumulationSink`, but `ChoiceUiSink` never forwards them to the parent `Choice`.

2. **No clear proposed approach** — The doc presents Approach 1 and Approach 2 as parallel options without indicating which is the proposal and which is deferred. A design document must converge on one approach. As written, it reads as a comparison study, not a design ready for approval and implementation.
   **Suggestion:** Nominate one approach as the proposal (the doc's own framing of Approach 1 as "short-term" and Approach 2 as "target architecture" suggests a natural split). Move the deferred approach — most likely Approach 2, which requires an `aidial_sdk` bump and UI-team coordination — into an "Out of Scope" section with a note explaining its prerequisites.

### Suggestions

1. **Missing Design Goals section** — The doc has no "Design Goals" section. Per `docs/designs/README.md`, goals must be concrete and independently verifiable. Consider: "Sub-app stage names appear in the parent stream for any A→B call when `ENABLE_PREVIEW_FEATURES=true`"; "Nesting depth > 1 produces distinct prefixes per level without index collision"; "Disabling the feature (`orchestrator.propagate_sub_stages: false`) produces byte-identical output to today."

2. **Missing Use Cases section** — No trigger/behavior/outcome scenarios are given. Even a single use case — QuickApp A calling QuickApp B as a tool — anchored with what a user sees in the UI before and after, would ground both approaches and make the trade-off between them concrete.

3. **Missing Out of Scope section** — Nothing is explicitly deferred. At minimum: stage content/attachments from sub-apps; non-deployment tools (REST, MCP, internal); error stages from the sub-app; and the Approach 1 → Approach 2 migration path. Without explicit deferrals, reviewers and implementors will ask about these themselves.

4. **Missing Migration section** — (a) Existing manifests without `orchestrator.propagate_sub_stages` will silently opt in to sub-stage propagation when `ENABLE_PREVIEW_FEATURES=true` because the proposed default is `true`. This is a behavioral change for anyone relying on the current (silent) behavior; state it explicitly and justify the choice of an opt-in default. (b) For Approach 2: the `parent_stage_index` backward-compatibility guarantee (absent field = top-level stage) lives only in the wire-format section; it must also appear in a Migration section for UI and SDK consumers.

5. **Missing Configuration / Usage Examples section** — The doc introduces `orchestrator.propagate_sub_stages` but never shows what the field looks like in a manifest, how to disable it, or what the observable difference is between `true` and `false`. A one- or two-entry manifest snippet would suffice.

6. **"Scale of changes" is not a Summary of Changes** — The closing table lists file counts, not the fields, classes, and interfaces added or modified. Per `docs/designs/README.md`, a Summary of Changes should be "a scannable reference of all additions, removals, and modifications, grouped by component." Replace the table with a grouped list (e.g., new `PreviewField orchestrator.propagate_sub_stages`, new `ChatStreamConfig.sub_stage_prefix`, changed `ChoiceUiSink.__init__` signature, new `Stage.stage_index` property, etc.).

7. **Approach 1 / Approach 2 DI asymmetry** — Approach 1 says "Inject `Choice` into `DialCompletionService`" while Approach 2 threads `parent_stage: Stage | None` as a new method parameter to `complete_request_async`. No rationale is given for the asymmetry. Since `stage_wrapper` is already passed as a method parameter today, parameter-threading is the established pattern and introduces less coupling. Consider making Approach 1 use the same pattern.

### Nits

1. **Header metadata format** — The doc uses `**Status:** Draft` as inline bold text rather than the list format `- **Status:** Draft` that `docs/designs/template.md` specifies. Other docs in this directory follow the list form. Also, there is no `- **Dependencies:**` entry.

2. **Gating description in Approach 2** — "The feature is gated identically to Approach 1" assumes the reader read Approach 1 first. Readers who start from Approach 2 or read non-linearly won't have the context. Consider restating the gating in one sentence.
