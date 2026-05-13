# Design: Pass attachments to orchestrator

- **Status:** Implemented

## Problem Statement

Admin-configured context files (documents, spreadsheets, images, archives, etc.) are part of QuickApp configuration. Many orchestrator deployments already support **those MIME types as input attachments** via DialCore (`input_attachment_types`), but QuickApps does **not** consistently use that capability for configured admin files: the bytes may never reach the orchestrator on the native attachment path the model is meant to use.

Observable symptoms:

- **Underused orchestrator capability:** Attachment-capable orchestrators still lack admin context on the structured attachment channel, so the stack behaves as if “file in the app config” and “file the orchestrator can read this turn” are unrelated.
- **Misleading refusals:** The model may say it **cannot** answer questions about a configured file when that is not fundamentally true for a deployment that accepts that MIME type - often the wiring and prompt shape are wrong, not the model. When **RAG** (or similar) is configured, it is frequently the **better** choice for huge corpora or retrieval-heavy questions; the defect is that **native attachments are unused** and the assistant sounds blocked instead of choosing RAG deliberately or calling `internal_attachments_get_content` when appropriate.
- **Wasted work when eager:** If the product pushes full attachment treatment every turn, the adapter may download and send content even when the user’s question does not need the file (e.g. a factual or web question).
- **Semantic mismatch:** “Always present” file context encourages the stack to treat the asset as part of the default prompt, rather than as an opt-in resource tied to the user’s intent.

The gap is a **defer-by-default** model that still **materializes on demand** through the orchestrator’s supported attachment path: listing metadata is cheap; attaching the needed file (admin-configured or user-uploaded in the current request) should happen only when the user’s intent requires it, so **native attachments** (for supported types), RAG, and other tools are used **intentionally**, not as accidental workarounds.

## Design Goals

Each goal should be independently verifiable.

- **Deferral:** For a typical message that does not reference admin context files, the orchestrator path does not apply full document attachment treatment to those admin files by default.
- **Discoverability:** The orchestrator can obtain an authoritative **list** of admin-configured context files (name, type, stable reference), consistent with available-context semantics (admin files only-not user attachments or other tools’ outputs).
- **Explicit load (`internal_attachments_get_content`):** When the user asks about a specific file, the orchestrator can request **that** file via this **dedicated internal** tool and receive it through the same channel the stack uses for tool-supplied attachments.
- **Security:** Arguments to `internal_attachments_get_content` resolve only against request-allowed files: admin-configured contexts plus user attachments present in the current message history and accepted by orchestrator MIME policy. Paths outside that set never return an attachment.
- **Least privilege:** No blanket rule to forward all assistant or all tool attachments to the orchestrator; only a **narrow** exception applies to the **`internal_attachments_get_content`** tool outcome (plus existing rules such as user images).
- **Compatibility:** Native orchestrator attachments (for MIME types the deployment accepts) and RAG-based flows remain valid; this design changes **when** the file enters the thread on the native path, not whether RAG or other tools exist. Preferring RAG when it is available stays a valid product choice.
- **Verification (acceptance):** (1) Irrelevant query with a configured context file (e.g. large PDF or CSV) → lighter prompt/attachment treatment than baseline (metric: tokens, attachment count, or adapter events - agreed with ops). (2) Relevant admin-file query → list then `internal_attachments_get_content` → grounded answer when the model supports that MIME. (3) Relevant user-uploaded file query → `internal_attachments_get_content` with exact URL from `<attachments>` → grounded answer when MIME is supported. (4) Get-content with URL outside allowed admin/user set → no file attachment. (5) User image attachment policy unchanged. (6) Other tools’ attachments do not gain wholesale passthrough.

---

## Use Cases

### UC-1: Irrelevant question, context file exists

**Trigger:** QuickApp has an admin context file (e.g. a large PDF, a CSV export, or a diagram image); user asks something unrelated (e.g. current weather in a city).

**Behavior:** Orchestrator answers without needing that file; no `internal_attachments_get_content` step is required.

**Outcome:** Lower attachment and prompt cost than always pushing the file on the orchestrator path.

---

### UC-2: User asks about a named admin file

**Trigger:** User refers to a file that matches an admin-configured context entry (e.g. “What does section 3 say in `handbook.pdf`?” or “What is the Q3 total in `sales.csv`?”).

**Behavior:** Orchestrator calls the **list** tool, then **`internal_attachments_get_content`** with the **exact `url`** string from the list response. The product returns that single file as the tool result attachment.

**Outcome:** The file is available for the next reasoning step; ambiguous filenames are mitigated by stable identifiers in tool design.

---

### UC-3: User asks about their own attached file

**Trigger:** User uploads a file in message `<attachments>` and asks a question about that file.

**Behavior:** The file is not returned by `internal_attachments_available_context` (admin-only by contract). Before orchestrator invocation, the pipeline injects synthetic `internal_attachments_get_content` ASSISTANT/TOOL message pairs for each attachment on the **last USER message** (for supported MIME), so the model receives equivalent tool history without manually calling the tool for that initial user attachment set.

**Outcome:** User-uploaded files are materialized lazily on the same path as admin files without broadening list-tool scope, and the current-turn history remains tool-call consistent.

---

### UC-4: Orchestrator deployment does not accept the file’s MIME (Dial gate)

**Trigger:** Same file-oriented user intent as UC-2, but DialCore **`input_attachment_types`** for the orchestrator deployment does not accept the configured file’s MIME type (e.g. neither `application/pdf` nor `text/csv` nor `image/png` - per `matches_type`). RAG or other tools may or may not be configured.

**Behavior:** **`internal_attachments_get_content`** is **not** registered - the MIME/orchestrator gating rule does not pass - so there is **no** lazy materialization on this path. The **list** tool may still expose file metadata per existing rules. Any answer must come from other configured tools (e.g. RAG) or general knowledge, not from a native attachment delivered by this internal tool for that MIME.

**Outcome:** Predictable limitation; no false expectation that the orchestrator received that file via native attachment here; product/docs avoid implying “call get-content anyway” when the tool is absent.

---

### UC-5: Deployment accepts the file’s MIME type

**Trigger:** User question targets a configured file; orchestrator `input_attachment_types` accepts that MIME (e.g. PDF, CSV, or image - per product allowlist and Dial).

**Behavior:** After a successful `internal_attachments_get_content` result, existing downstream behavior applies (native reading where the stack supports it).

**Outcome:** Same quality target as today once the file is in-thread, with better deferral before that point.

---

### UC-6: RAG exists alongside native attachments

**Trigger:** User file question; both native attachment handling (for an accepted MIME) and RAG tools exist.

**Behavior:** Orchestrator may answer from a native attachment or call RAG with a link, per model policy; lazy materialization via `internal_attachments_get_content` does not remove RAG.

**Outcome:** Flexibility preserved; deferral only affects default presence of the file.

---

## Proposed Design

### Concern 1: Two-step internal flow (list, then `internal_attachments_get_content`)

- **What:** Keep the existing **available context** internal tool as the discovery step for admin files. Add **`internal_attachments_get_content`** (OpenAI function name; avoids colliding in prose with MCP **fetch** tools) that returns **one** allowed file as a tool result attachment when the argument uniquely identifies an allowed admin context URL or allowed user attachment URL.
- **Owner:** Attachment processing / internal tooling (alongside existing available-context tool registration and execution).
- **Semantics:** (1) User message may reference an admin file or a user-uploaded file. (2) Orchestrator calls list tool → JSON/text with titles, MIME types, stable paths/ids, descriptions; disclaimer remains admin-focused (user `<attachments>` are not listed there). (3) For **admin files**, orchestrator calls `internal_attachments_get_content` with `attachment_url` (legacy alias `context_url` still accepted). For **attachments on the last USER message**, the pipeline injects synthetic `internal_attachments_get_content` ASSISTANT/TOOL pairs (one per attachment URL) before the model call. (4) Product validates URL against request-allowed set (admin contexts + user attachments, each gated by orchestrator MIME support); success → tool result with one file attachment; failure → error content, no attachment. (5) Later turns follow existing history semantics, subject to Concern 2 and Concern 5.
- **Change:** New tool definition, implementation, and registration follow the **same subsystem and list-adjacent patterns** as the available-context tool, but the gates are **not identical**: `internal_attachments_get_content` adds orchestrator MIME capability checks on top of the list activation rules (see Concern 3).

### Concern 2: Orchestrator attachment policy (narrow exception)

- **What:** Rules for which `custom_content.attachments` survive on messages sent to the orchestrator model-especially **tool** messages-so the **`internal_attachments_get_content`** result is visible to adapters that consume structured attachments, without opening all tool attachments.
- **Owner:** Pre-invocation message preparation (attachment filter / transformers) in the agent layer; must align with Dial adapter expectations for tool-role attachments.
- **Semantics:** User messages: remove `custom_content.attachments` after extracting metadata into XML (no direct USER attachment passthrough). Assistant messages: no blanket forward-all rule. Tool messages: default remains conservative; **exception** for results from **`internal_attachments_get_content`** when MIME is accepted by orchestrator and URL belongs to the same allowed admin/user set used by tool execution. Defense in depth: combine internal tool identity resolution, MIME checks, and URL membership in request-allowed set so deployments, MCP, interpreter, and other tools do not accidentally satisfy the exception.
- **Change:** Today, non-user tool attachments may be stripped or only reflected in content XML; this design requires a **documented, minimal** relaxation for the **`internal_attachments_get_content`** path only, chosen in implementation to satisfy the safety properties above.

### Concern 3: Registration and model guidance

- **What:** When **`internal_attachments_get_content`** appears in the orchestrator tool list; what the model is told to do.
- **Owner:** Internal tool multiplexer (`AttachmentProcessingModule`) + orchestrator deployment prefetch (Concern 4); MIME checks use **`quickapp.common.utils.matches_type`** only (no ad-hoc wildcard logic).
- **Semantics:** The **available-context list** tool follows existing activation (`should_activate_context_tool` / admin file contexts) unless product narrows it. **`internal_attachments_get_content`** is registered when at least one request-visible file (admin context or user attachment) has MIME accepted by orchestrator deployment `input_attachment_types` via `matches_type`. Otherwise the tool is **absent** from the tool list so the model cannot call it. Transformer order is: synthetic user-attachment get-content injector first, then context-notification injector. Tool descriptions still instruct: for admin files, list then fetch.
- **Change:** Extend internal tool multiplexer with conditional registration for `internal_attachments_get_content`; no change to external deployment tool contracts.

### Concern 4: Orchestrator model capabilities from DialCore (prefetch)

- **What:** Before the **first** chat-completion call to the orchestrator deployment in a request, QuickApp should load deployment metadata from DialCore and retain **`input_attachment_types`** (list of MIME patterns the model accepts as input attachments), using the same retrieval approach as simple deployment tools (`ToolConfigCoreService` + `AsyncDial.deployments.get`, with application fallback as today). The authoritative response shape is the Dial SDK’s **`Deployment`** / **`DeploymentBase`** (includes `id`, `object`, `model`, `input_attachment_types`, `features`, etc.).
- **Owner:** Dial core services + completion initialization in the **agent** area; request-scoped holder for `input_attachment_types` / optional full `Deployment`.
- **Semantics:** (1) Resolve `ApplicationConfig.orchestrator.deployment.name` against DialCore; cache through a **dedicated** `CacheService[Deployment]` subclass colocated with the **agent** package (same *pattern* as `DialDeploymentToolCacheService`, but **not** that cache instance-separate singleton and keys). (2) Expose `input_attachment_types` to **`internal_attachments_get_content`** registration, tool execution, and `_AttachmentFilter` logic; use **`quickapp.common.utils.matches_type`** for every comparison of a concrete file MIME to `input_attachment_types`. (3) When Dial omits or returns an empty list, follow an explicit product rule (e.g. match existing tool-schema behavior for “no attachment types” vs “all types”) and document it.
- **Change:** New initializer + agent-scoped orchestrator deployment cache + request-scoped capability holder; duplicate Dial `get` versus deployment-as-tool cache is acceptable for isolation.

### Concern 5: Long conversations after content is loaded

- **What:** After **`internal_attachments_get_content`** succeeds, the tool message normally carries **structured attachments** (`custom_content.attachments`) for the current orchestrator loop. That payload is still needed for **later tool calls and LLM hops within the same completion** (same user message, multi-iteration orchestration). Once the run ends and history is **persisted for the next HTTP request**, carrying the same file attachment forward indefinitely bloats `tool_execution_history`, re-surfaces bytes/metadata on every future turn, and undermines the **lazy** contract: a new user message should rely on **list** metadata and call **`internal_attachments_get_content` again** only when the document is needed again.

- **Owner:** Orchestrator persistence path (`Orchestrator._build_tool_execution_history` and related state packing); `PreInvocationTransformer` path (`_AttachmentFilter`) for in-flight behavior; DIAL adapter behavior for stable `files/...` URLs.

- **Semantics:** (1) **Within one completion:** QuickApps does **not** auto-reinvoke `internal_attachments_get_content`; another attachment appears only if the model issues **another** tool call. Tool messages retain attachments in memory for the rest of that orchestration as today. (2) **Across completions (persisted history):** When building **`tool_execution_history`** for `state` (the tail of ASSISTANT + TOOL messages since the last user message), **strip `custom_content.attachments` from `TOOL` messages whose tool call resolves to `internal_attachments_get_content`**, while **keeping** the tool message’s textual **`content`** (e.g. JSON success or error) so the transcript stays coherent. Correlate `TOOL.tool_call_id` → preceding assistant `tool_calls[].function.name`; apply only to that tool name - **do not** strip other tools’ attachments. Prefer operating on a **copy** for serialization so in-memory messages for the current response are unchanged. (3) **Gating:** Apply stripping when persisting history **after a terminal assistant message** for that orchestration (no further tool calls expected for that user turn) - not necessarily on every partial save path (e.g. interrupt mid-loop) unless product explicitly wants smaller partial state at the cost of losing replay attachment for resume. (4) Pre-invocation may still mirror attachment XML per hop; if duplicate XML or redundant downloads appear despite stripping persisted attachments, treat as **implementation or adapter follow-up**.

- **Change:** Implement attachment removal in the orchestrator’s history-serialization step (or a small helper used from `_build_tool_execution_history`); add tests that rehydrated messages from `TOOL_EXECUTION_HISTORY` contain get-content **text** but **no** attachment rows, and that other tools are untouched; optional metric: history blob size before/after strip.

---

## Secondary Fixes

- **Tool copy and admin documentation:** Align descriptions with list vs `internal_attachments_get_content` and with unsupported-MIME / missing-tool expectations (UC-4).
- **Stable URL parameter:** Prefer canonical storage path from configuration in list responses and exact URL echo from user `<attachments>` metadata so the model passes one unambiguous string into `internal_attachments_get_content`.

---

## Out of Scope

| Item | Why deferred |
|------|----------------|
| Replacing or re-implementing RAG deployments | Different product surface; lazy materialization via `internal_attachments_get_content` does not subsume retrieval. |
| Automatic semantic “document relevance” without model tool use | Higher complexity; could be a future optimization after lazy path is proven. |
| Replacing synthetic user-attachment get-content injection with eager passthrough of all user attachments | Higher coupling and cost; current design keeps USER attachments as metadata XML plus synthetic get-content history for the last USER turn. |

---

## Configuration / Usage Examples

| Scenario | Expected tool usage |
|----------|---------------------|
| Weather question, admin `inventory.csv` in config | No `internal_attachments_get_content`; list optional and may be unused |
| `report.pdf` in config but orchestrator does not accept that MIME in `input_attachment_types` | `internal_attachments_get_content` **not** in tool list (for that MIME); list may still show metadata per existing rules |
| “Plot trend from `sales.csv`” when `sales.csv` is in config | List → `internal_attachments_get_content` using stable URL from configuration (when CSV is lazy-materializable and accepted) |
| “Describe `diagram.png`” when `diagram.png` is admin context | Same two-step pattern for images when product + Dial allow that MIME |
| User attaches their own file (e.g. their own PDF or photo) | Not listed by admin context tool; pipeline injects synthetic `internal_attachments_get_content` ASSISTANT/TOOL pair(s) for the last USER attachments when MIME is supported |

Step-by-step (happy path, CSV example):

1. Admin configures file contexts including e.g. `files/bucket/folder/sales.csv`.
2. User: “What is the Q3 revenue column total in sales.csv?”
3. Orchestrator: `internal_attachments_available_context` → sees `sales.csv` and path.
4. Orchestrator: `internal_attachments_get_content` with the whitelisted `url` → receives tool message with attachment.
5. Orchestrator continues with normal completion loop.

Step-by-step (happy path, user attachment example):

1. User attaches `files/bucket/uploads/customer-report.pdf` and asks a question about it.
2. Message `<attachments>` metadata contains that exact URL and MIME; USER `custom_content.attachments` is filtered out before orchestrator call.
3. Attachment-processing transformer injects synthetic ASSISTANT/TOOL `internal_attachments_get_content` pair with `attachment_url=files/bucket/uploads/customer-report.pdf`.
4. Backend validates URL against user attachments in current messages + MIME gate; TOOL message carries the attachment.
5. Orchestrator continues with normal completion loop using consistent tool history.

---

## Migration

### Breaking changes

The new tool is additive and gated, so no breaking change is required to ship **`internal_attachments_get_content`**.

### Non-breaking changes

Adding a **new** internal tool next to the list tool is **additive** if default prompt injection is unchanged. Further token savings from changing how often synthetic context notifications are injected are **out of scope for this document** (see attachment-notification path and product flags if revisited).

---

## Summary of Changes

| Component / area | Addition or change |
|------------------|---------------------|
| Internal tools | New **`internal_attachments_get_content`** when orchestrator `input_attachment_types` supports at least one request-visible MIME among admin contexts or user attachments (`matches_type` from `quickapp/common/utils.py`); list tool keeps existing admin-context gate. |
| Agent cache | New `CacheService[Deployment]` for orchestrator id under **`quickapp/agent/`**, independent of `DialDeploymentToolCacheService`. |
| Tool semantics | List remains admin-only; `internal_attachments_get_content` validates `attachment_url` (legacy `context_url` alias) against request-allowed admin/user URLs; returns one attachment or error text. |
| Orchestrator input path | Narrow exception so **`internal_attachments_get_content`** results can retain allowed file types only when URL/MIME pass request-level admin/user checks and DialCore `input_attachment_types`; USER message `custom_content.attachments` are filtered out and represented as XML metadata + synthetic get-content history for the last USER turn. |
| DialCore prefetch | Before first orchestrator completion call, load `Deployment` for orchestrator id via **agent** deployment cache; store `input_attachment_types` (request-scoped) for MIME-aware **`internal_attachments_get_content`** registration and filter behavior. |
| Config / ops | Optional: feature flag or per-app mode for lazy vs eager context surfacing. |
| Documentation | Admin and tool-description updates for list → `internal_attachments_get_content` and unsupported-MIME expectations. |
