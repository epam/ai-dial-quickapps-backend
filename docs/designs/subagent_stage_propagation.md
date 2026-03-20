# Design: Subagent Stage Propagation

**Status:** Draft

## Problem Statement

When a QuickApp invokes subagents (e.g. DIAL RAG, nested QuickApps), there is no way for the user to see what is happening inside those subagents. Subagents can produce **stages** — discrete steps or phases of work — but those stages are only visible within the subagent’s own context. The root QuickApp choice (the one the user is following) does not surface them, so users have no visibility into subagent progress without digging into each subagent call.

**Observable symptom:** A user sees the root QuickApp “calling RAG” or “calling another QuickApp” as a single step, with no indication of which sub-steps (e.g. “Access document”, “Load indexes”, “Combined search”) are running or completed inside that call.

## Design Goals

- When a QuickApp is configured to do so, stages produced by its subagents must be **propagated to the root QuickApp choice** (the choice the user is following).
- It must be **clear to the user that these stages belong to the subagent**, not to the root QuickApp. The UX must distinguish “stages of this QuickApp” from “stages of a subagent this QuickApp called” (e.g. labelling, grouping, or attribution so the source is unambiguous).
- Propagation must be **opt-in per deployment tool** via configuration; default behaviour remains no propagation.
- Handling of deployment stream deltas (including stages) must stay in a **single place** so the rest of the application stays agnostic to subagent internals.
- Propagation should **stream** subagent stage updates to the root choice as deltas arrive, so users see progress during the call and the backend avoids holding unbounded per-stage buffers until end-of-stream.

---

## Proposed Design

Subagent stages are propagated to the root QuickApp choice only when a deployment tool is explicitly configured to do so. A new setting under `content_propagation` controls whether stages from the deployment completion stream are surfaced. The application reacts to `custom_content.stages` in the deployment completion stream inside `DialCompletionService._consume_stream()`, **creating or resolving a propagated stage per subagent `index` on first touch and applying each delta immediately** (name parts, content, attachments, status) through the stage wrapper. **DIAL supplies only append semantics** for stage fields (no full replacement of content); the consumer always merges by appending where applicable.

Each propagated stage’s display name is prefixed with the deployment tool’s **deployment name** so the source is unambiguous even when `display.stage` is omitted (display remains optional). The design is backend-only; the DIAL chat completion wire format for `delta.custom_content.stages` is assumed given.

### Concern 1: Tool config (deployment)

**What:** A new boolean on deployment tool config to enable stage propagation.

**Owner:** `ContentPropagation` in `quickapp.config.tools.deployment`; `DialDeploymentTool.content_propagation`.

**Semantics:** Add `propagate_stages: bool = False` to `ContentPropagation`. When `True`, the deployment tool instructs the completion service to interpret `delta.custom_content.stages` and propagate them to the root QuickApp choice with prefixed names. Only deployment tools that set this to `True` propagate subagent stages.

**Change:** Field `propagate_stages` on `ContentPropagation` with description documenting that subagent stages from the deployment stream are propagated to the root choice with prefixed names so the source is unambiguous.

### Concern 2: Tool config (display)

**What:** Optional display configuration for the deployment tool’s **own** stage (title/body/visibility). It is **not** required for stage propagation naming.

**Owner:** `ToolDisplayConfig.stage` (`ToolStageConfig`: `name`, `body`, `show`).

**Semantics:** `display.stage` remains optional. Propagated subagent stage titles use the **deployment name** as the prefix (see Concern 6), not `display.stage.name`, so propagation works for minimal configs. When present, `display.stage` continues to apply to the tool stage chrome as today.

**Change:** None to the schema; documentation and implementation treat display as independent of the propagation prefix rule.

### Concern 3: DialCompletionService — streaming consumption and stage updates

**What:** In `_consume_stream()`, when stage propagation is enabled and `delta.custom_content` carries a `stages` field, **apply each parsed stage delta immediately** to the corresponding propagated stage (create the stage on first sight of an `index`, then append updates). Do **not** accumulate full content/attachments in memory until end-of-stream for the purpose of propagation.

**Owner:** `DialCompletionService` in `quickapp.dial_deployment_tooling.dial_completion_service`.

**Semantics:**

- **Per delta:** Parse `custom_content.stages` into `SubagentStageDelta` items (see data contracts). For each item, resolve the propagated stage for `index` (create if missing). Apply fields present in the delta:
  - **Name / title:** append name parts in order (same merge rule as before, but live on the stage).
  - **Content:** append (DIAL does not send replacement content; only append).
  - **Attachments:** extend the stage’s attachments as they appear (see Concern 7).
  - **Status:** update to the latest value from the delta so the UI can reflect running/completed as the stream progresses.
- **Ordering:** Process items in stream order. Stages for distinct indices appear as the stream introduces them; final ordering follows SDK/choice rules (e.g. creation order).
- **Separator:** Fixed constant `PROPAGATED_STAGE_NAME_SEPARATOR` (e.g. `" › "`) from `quickapp.dial_deployment_tooling.constants`, used when composing the full displayed title `{deployment_name}{separator}{concatenated name parts}`. If there are no name parts yet, use a placeholder such as `"Stage {index+1}"` until name parts arrive, or the implementation’s equivalent.

**Change:** `complete_request_async` / `_consume_stream` accept `propagate_stages` and a **deployment name** (or equivalent string) for the prefix. When `propagate_stages` is True and `stages` is present, stream-apply deltas via the stage wrapper instead of batching at end-of-stream.

### Concern 4: BaseDeploymentTool — passing propagation into completion

**What:** Derive `propagate_stages` and the **deployment name** used for propagated stage titles, and pass them into the completion service.

**Owner:** `BaseDeploymentTool` in `quickapp.dial_deployment_tooling.base_deployment_tool`.

**Semantics:** In `_run_in_stage_async`, read `content_propagation.propagate_stages` and the tool’s **deployment name** (the same identifier users/deployers associate with the deployment — e.g. configured deployment name, not optional display). Pass `propagate_stages` and that string into `complete_request_async`. When `content_propagation` is `None` or `propagate_stages` is False, pass `propagate_stages=False`; the deployment name is only required when propagation is True (if missing, treat as configuration error or use a safe fallback documented in implementation).

**Change:** Replace or supplement any prior `tool_stage_display_name`-only wiring with **deployment name** as the authoritative prefix source for propagated stages.

### Concern 5: Stage wrapper and SDK

**What:** Create propagated stages from the current tool stage and **mutate them incrementally** as stream deltas arrive.

**Owner:** `BaseStageWrapper` / deployment stage wrapper; SDK `Stage` (e.g. `append_name`, `append_content`, `add_attachment`, status updates, or child stage creation).

**Semantics:** On first delta for `index` *n*, create the propagated stage (child of the tool stage if supported, else sibling on the choice). On subsequent deltas for the same `index`, append name/content, add attachments, and set status. No end-of-stream bulk flush is required for correctness; optional finalization hooks depend on SDK capabilities.

**Change:** Implementation ensures idempotent **per-index** resolution (lazy create) and streaming writes aligned with Concern 3.

### Concern 6: Propagated stage naming (deployment name prefix)

**What:** Stable, non-optional attribution prefix for every propagated stage title.

**Owner:** `DialCompletionService` (when composing titles) together with `BaseDeploymentTool` (supplying deployment name).

**Semantics:** Display name = `{deployment_name}{PROPAGATED_STAGE_NAME_SEPARATOR}{concatenated name parts from stream}` (e.g. `my-rag-deployment › Access document '...' [0.01s]`). Name parts are appended in order as deltas arrive. If there are no name parts, use `"Stage {index+1}"` (or equivalent). **Do not rely on `display.stage.name`** for this prefix, because display is optional.

**Change:** Document and implement deployment name as the prefix; align tests and samples with deployment-named examples.

### Concern 7: Propagated attachments

**What:** Attachments may arrive incrementally across many deltas; lists can grow large; order and duplication matter for UX and resources.

**Owner:** `DialCompletionService._consume_stream()` and stage wrapper attachment APIs.

**Semantics:** Attachments are **appended** as they appear in each delta (streaming). **Risks:** unbounded attachment count or payload size per stage, duplicate references if the subagent retries or repeats deltas, and undefined ordering if the wire format is ambiguous.

**Suggested direction:** Define caps (per stage and/or per deployment call), structured logging and metrics when caps trigger (see Concern 10), and a deduplication policy if attachments carry stable identifiers; otherwise document best-effort append order with no dedup.

**Change:** Product/engineering decision on limits; implementation enforces chosen caps without failing the whole completion (degrade gracefully, e.g. skip further attachments with a log + metric).

### Concern 8: Stage index identity and cardinality

**What:** Correct grouping requires a stable **index** per logical subagent stage. Missing or inconsistent indices and high cardinality create wrong merges or resource pressure.

**Owner:** `parse_stages` / `SubagentStageDelta` validation; `DialCompletionService` propagation path.

**Semantics:** Prefer **required `index`** on each item; same index across deltas = same propagated stage. **Risks:** list-position fallbacks can mis-group if list shape varies between chunks; a buggy or hostile stream could emit huge numbers of distinct indices.

**Suggested direction:** Treat missing `index` as invalid for propagation (skip item + metric) once clients are aligned, or document a strict backward-compatibility window for position fallback. Enforce a **maximum number of propagated indices** per deployment call; beyond the cap, ignore new indices with log + metric.

**Change:** Config or constants for caps; metrics for skipped items and truncation.

### Concern 9: Flat UI and grandchild stages

**What:** When a subagent such as RAG streams **its own** internal substeps, those stages may represent work below the immediate subagent. The current product UI does **not** expose a tree of stages; propagated stages appear as a **flat** list on the choice.

**Owner:** Product/UX for presentation; backend only supplies flat propagated stages with a single prefix per deployment tool call.

**Semantics:** Users cannot distinguish “stage of RAG” from “stage of something RAG called” by structure alone — both appear as sibling-like entries with the same deployment name prefix. Attribution is therefore **by naming prefix only**, not by hierarchy.

**Suggested direction:** Accept this limitation unless the client gains hierarchical stage rendering; avoid over-promising nested attribution in copy. Future work could add multi-segment prefixes or metadata if the wire format and UI support it.

**Change:** None required beyond documentation; optional follow-up design if tree UX lands.

### Concern 10: Metrics and logging

**What:** Operators need visibility into propagation volume, truncation, and parse failures without logging sensitive stage bodies by default.

**Owner:** `DialCompletionService` / propagation helper module; application metrics registry (concrete names TBD by implementation).

**Semantics:** Emit **metrics** (counters or histograms as appropriate) for at least: stage deltas applied, propagated stages created (distinct indices), parse/skipped invalid items, attachment or index cap hits, and propagation fallback paths (e.g. stage creation failure). At **info** level, log concise, non-sensitive summaries (e.g. counts per completion, first-time propagation in a call, cap/truncation events) — **not** full concatenated content or attachment payloads unless behind a dedicated debug flag.

**Suggested direction:** Define metric names and label cardinality in the implementation PR; keep logs structured and PII-safe.

**Change:** Add metrics + info-level logging per above; align with existing observability patterns in the service.

### Data flow (summary)

```mermaid
sequenceDiagram
  participant Tool as BaseDeploymentTool
  participant Svc as DialCompletionService
  participant Stream as Deployment completion stream
  participant Wrapper as Stage wrapper

  Tool->>Svc: complete_request_async(..., propagate_stages=True, deployment_name="my-rag")
  Svc->>Stream: consume stream
  loop Each delta
    Stream-->>Svc: delta.custom_content.stages
    Svc->>Svc: parse SubagentStageDelta items
    Svc->>Wrapper: ensure stage per index; append name/content/attachments; set status
  end
  Note over Svc,Wrapper: No end-of-stream bulk flush required for propagation
```

---

## Key interfaces and data contracts

| Item | Contract |
|------|----------|
| **Propagation setting** | `ContentPropagation.propagate_stages: bool = False`. When `True`, `_consume_stream()` interprets `delta.custom_content.stages` and propagates with streaming apply and the naming rule below. |
| **Subagent stage payload** | `custom_content.stages`: list of stage delta objects. Each item identified by **index** (0-based). Same index across deltas = same logical stage (**append** merge). Fields: `index`, optional `name`/`title`, optional `content`, optional `attachments`, optional `status`. DIAL does **not** replace content; consumer **appends**. See `SubagentStageDelta` in `stage_propagation_models.py`. |
| **Propagated stage name** | One propagated stage per subagent **index** (lazy-created). Display name = `{deployment_name}{PROPAGATED_STAGE_NAME_SEPARATOR}{concatenated name parts}`. If no name parts, use `"Stage {index+1}"` (or equivalent). |
| **Separator constant** | `PROPAGATED_STAGE_NAME_SEPARATOR = " › "` in `quickapp.dial_deployment_tooling.constants`. |
| **Parsing** | `parse_stages(raw_stages)` in `stage_propagation_models`: resilient to partial/malformed payloads; only valid list items (dicts that validate as `SubagentStageDelta`) are returned. |

---

## Design patterns and rationale

- **Configuration-driven behaviour:** Whether stages are propagated is controlled by tool config (`content_propagation.propagate_stages`), not globally. Keeps the default safe (no propagation) and allows per-tool control.
- **Single place for stream reaction:** All handling of deployment stream deltas (content, attachments, state, and stages) stays in `DialCompletionService._consume_stream()`, so the deployment tool’s “internal” behaviour stays in one place and the rest of the app stays agnostic.
- **Streaming propagation:** Applying deltas immediately improves perceived progress and avoids holding large accumulators for content/attachments solely for end-of-stream flush.
- **Deployment name prefix:** Guarantees attribution when optional display config is absent; aligns prefix with the deployment identity operators configure.

---

## Secondary Fixes

### Error handling

If `custom_content.stages` is malformed or stage creation fails, fall back to not propagating or to a single stage with prefixed name and appended content; do not fail the whole completion. Log the condition. Malformed or non-dict items in `stages` are skipped by `parse_stages`.

### Auth / security

No change; stream consumption is already in a trusted backend path.

### Extensibility

The same mechanism (`custom_content.stages` + prefix rule) could later be used by other tools that call subagents (e.g. MCP or REST tools that return stages), if they adopt the same config and consumption pattern.

---

## Out of Scope

- **Frontend / UX design:** How to illustrate that propagated stages are from the subagent (beyond flat naming with a prefix) is a product/UX concern; this design specifies backend naming and streaming updates.
- **Root model stream:** The agent chunk processor’s `__process_custom_content()` (for root model stream) is for the root model only; deployment tool stream is consumed only in `DialCompletionService`. No change to ChunkProcessor for this feature.
- **DIAL content replacement:** DIAL does not support replacing stage content in deltas; only append semantics are in scope. Snapshot/replace protocols are out of scope unless the wire format changes.
- **Hierarchical stage UI:** Tree rendering of nested subagent stages is not available; see Concern 9.

---

## Configuration / Usage Examples

### Default: no propagation

```json
{
  "type": "deployment-tool",
  "deployment": { ... },
  "content_propagation": {
    "propagate_history": false,
    "propagate_stages": false
  }
}
```

Subagent stages are not propagated; user sees only the root QuickApp’s own stages.

### Enable stage propagation

```json
{
  "type": "deployment-tool",
  "deployment": { ... },
  "content_propagation": {
    "propagate_history": true,
    "propagate_stages": true
  },
  "display": {
    "stage": {
      "name": "RAG search",
      "body": "Searching knowledge base",
      "show": true
    }
  }
}
```

When the deployment returns `delta.custom_content.stages`, each subagent stage is propagated with titles like (using the configured **deployment name**, e.g. `company-rag`):

- `company-rag › Access document '...' [0.01s]`
- `company-rag › Load indexes`
- `company-rag › Combined search`

Optional `display.stage` affects the deployment tool’s own stage presentation; propagated titles still use the **deployment name** prefix.

### Config sample reference

`config-sample.json` (or deployment tool config sample) includes optional `propagate_stages` under `content_propagation` so deployers know the option exists.

---

## Migration

### Breaking changes

Renaming or removing `tool_stage_display_name`-style parameters in favour of **deployment name** for the propagation prefix is a **contract change** for internal APIs (`complete_request_async`, `_consume_stream`). External tool configs remain backward-compatible if `propagate_stages` default stays `False`.

### Non-breaking changes

- Optional field `propagate_stages` on `ContentPropagation`; default `False`.
- Callers that do not pass propagation args keep default behaviour (no propagation).
- New or adjusted metrics and info-level logs are additive for operators.

---

## Risks and constraints

- **SDK and wire format:** The exact shape of `delta.custom_content.stages` depends on the DIAL chat completion API and client/SDK. Implementation must align with the actual delta schema; semantics are **append-only** for content from DIAL.
- **Stage hierarchy:** If the SDK does not support child stages under the tool’s stage, the implementation may create sibling stages on the choice with the same prefix; UX (ordering) should still make the source clear where possible.
- **Flat list:** Grandchild or deeper substeps are not visually nested; see Concern 9.
- **Caps:** Attachment and index cardinality limits need product agreement; see Concerns 7–8.

---

## Summary of Changes

| Component | Change |
|-----------|--------|
| **ContentPropagation** (`config/tools/deployment.py`) | `propagate_stages: bool = False` with description. |
| **DialDeploymentTool** | No structural change; uses existing `content_propagation`. |
| **ToolDisplayConfig.stage** | Optional; independent of propagation prefix (Concern 2). |
| **Constants** (`dial_deployment_tooling/constants.py`) | `PROPAGATED_STAGE_NAME_SEPARATOR = " › "`. |
| **stage_propagation_models** | `SubagentStageDelta`; `parse_stages(raw_stages)`. |
| **DialCompletionService** | `complete_request_async` / `_consume_stream`: `propagate_stages`, **deployment name** for prefix; **streaming** apply of `custom_content.stages`; metrics + info logging (Concern 10). |
| **BaseDeploymentTool** | Pass `propagate_stages` and deployment name into `complete_request_async`. |
| **BaseStageWrapper / Stage (SDK)** | Lazy create per `index`; append content/name/attachments; status updates on each delta. |
| **Config sample** | Optional `propagate_stages` under `content_propagation`. |
| **Observability** | Metrics for propagation volume, skips, caps; info-level structured logs without sensitive payloads by default. |
