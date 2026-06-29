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
- **Security:** `internal_attachments_get_content` returns an attachment only for a DIAL `files/` url (passthrough) or an external `http(s)` url (promoted to a DIAL file) whose MIME the orchestrator accepts. Authorization of the underlying fetch is enforced by the platform, not an in-app allow-set: DIAL Core gates `files/` access by the caller's bucket permissions, and the external-fetch policy (SSRF guard + host allowlist + size limit) gates `http(s)`. Unsupported url schemes never return an attachment.
- **Least privilege:** No blanket rule to forward all assistant or all tool attachments to the orchestrator; only a **narrow** exception applies to the **`internal_attachments_get_content`** tool outcome (plus existing rules such as user images).
- **Compatibility:** Native orchestrator attachments (for MIME types the deployment accepts) and RAG-based flows remain valid; this design changes **when** the file enters the thread on the native path, not whether RAG or other tools exist. Preferring RAG when it is available stays a valid product choice.
- **Verification (acceptance):** (1) Irrelevant query with a configured context file (e.g. large PDF or CSV) → lighter prompt/attachment treatment than baseline (metric: tokens, attachment count, or adapter events - agreed with ops). (2) Relevant admin-file query → list then `internal_attachments_get_content` → grounded answer when the model supports that MIME. (3) Relevant user-uploaded file query → `internal_attachments_get_content` with exact URL from `<attachments>` → grounded answer when MIME is supported. (4) Get-content with an unsupported url scheme, or a file whose MIME the orchestrator does not accept → no file attachment. (5) User image attachment policy unchanged. (6) Other tools’ attachments do not gain wholesale passthrough.

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
- **Semantics:** (1) User message may reference an admin file or a user-uploaded file. (2) Orchestrator calls list tool → JSON/text with titles, MIME types, stable paths/ids, descriptions; disclaimer remains admin-focused (user `<attachments>` are not listed there). (3) For **admin files**, orchestrator calls `internal_attachments_get_content` with `attachment_url`. For **attachments on the last USER message**, the pipeline injects synthetic `internal_attachments_get_content` ASSISTANT/TOOL pairs (one per attachment URL) before the model call. (4) The product accepts any DIAL `files/` url (passthrough) or external `http(s)` url (promoted to a DIAL file) whose MIME the orchestrator accepts — there is no in-app url allow-set, since authorization is enforced upstream (DIAL Core for `files/`, the external-fetch policy for `http(s)`); success → tool result with one file attachment; failure → error content, no attachment. (5) Later turns follow existing history semantics, subject to Concern 2 and Concern 5.
- **Change:** New tool definition, implementation, and registration follow the **same subsystem and list-adjacent patterns** as the available-context tool, but the gates are **not identical**: `internal_attachments_get_content` adds orchestrator MIME capability checks on top of the list activation rules (see Concern 3).

### Concern 2: Orchestrator attachment policy (narrow exception)

- **What:** Rules for which `custom_content.attachments` survive on messages sent to the orchestrator model-especially **tool** messages-so the **`internal_attachments_get_content`** result is visible to adapters that consume structured attachments, without opening all tool attachments.
- **Owner:** Pre-invocation message preparation (attachment filter / transformers) in the agent layer; must align with Dial adapter expectations for tool-role attachments.
- **Semantics:** User messages: remove `custom_content.attachments` after extracting metadata into XML (no direct USER attachment passthrough). Assistant messages: no blanket forward-all rule. Tool messages: default remains conservative; **exception** for results from **`internal_attachments_get_content`** when MIME is accepted by orchestrator and the url is a DIAL `files/` storage path. Defense in depth: combine internal tool identity resolution, MIME checks, and the `files/` storage-path check so deployments, MCP, interpreter, and other tools do not accidentally satisfy the exception. **Authorization** of the underlying fetch is **not** an in-app concern: DIAL Core gates `files/` access by the caller's bucket permissions and the external-fetch policy gates `http(s)` egress, so the keep policy does not consult a per-request url allow-set (urls legitimately arrive from tool outputs, pasted message text, and admin/user attachments alike).
- **Legacy compatibility:** `_LegacyUserImageKeepPolicy` (the pre-strategy default that lets USER `image/*` attachments survive verbatim) is registered **only when `OrchestratorConfig.attachment_strategy` is unset**. When any strategy is configured (currently only `lazy_on_demand`), the strategy-owned keep policy (`_GetContentKeepPolicy`) takes over USER attachment handling end-to-end and the legacy policy is unwired to avoid duplicating image bytes between the USER message and the synthetic `internal_attachments_get_content` TOOL result.
- **URL normalization:** `normalize_attachment_url_argument` strips outer whitespace **and** a single leading `/`, so DIAL-emitted `/files/...` and `files/...` forms compare equal at the two sites that consume normalized URLs: `_GetContentKeepPolicy.should_keep` and `_GetContentTool._run_in_stage_async` (both apply the `startswith("files/")` storage-path check). A leading `//` is preserved as malformed (the `files/` prefix check then rejects it).
- **External URLs (promotion):** When external URL fetching is enabled, an attachment whose url is an external `http(s)` reference (user attachment, admin context, or the model's own tool argument) is **downloaded and promoted to a durable DIAL file** before it reaches the orchestrator. The orchestrator attachment channel has no external-URL resolution of its own and only accepts DIAL `files/...` urls, so an unpromoted external url could not be fetched by the deployment. Promotion is centralised in `_AttachmentMaterializer` (wrapping `DialFilePromoter`, which enforces the two-tier external-fetch policy, the SSRF guard, the redirect cap, and the size limit) and is shared by **both** the synthetic injector and the explicit tool call. The model continues to see and pass the **original** url (in `<attachments>` metadata and the synthetic tool-call arguments); the promoted DIAL url rides only on the emitted attachment. Because the promoted url is a DIAL `files/` path, it satisfies the keep policy's storage-path check directly — no per-request registry of minted urls is needed. When promotion is blocked (policy / SSRF / size), the injector skips the attachment (so no misleading success pair is emitted) and the explicit tool call returns a retry error carrying `accepted_types`.
- **Change:** Today, non-user tool attachments may be stripped or only reflected in content XML; this design requires a **documented, minimal** relaxation for the **`internal_attachments_get_content`** path only, chosen in implementation to satisfy the safety properties above.

### Concern 3: Registration and model guidance

- **What:** When **`internal_attachments_get_content`** appears in the orchestrator tool list; what the model is told to do; and what the model learns when a call is rejected.
- **Owner:** Internal tool multiplexer (`AttachmentProcessingModule`) + orchestrator deployment prefetch (Concern 4); MIME checks use **`quickapp.common.utils.matches_type`** only (no ad-hoc wildcard logic).
- **Semantics:** The **available-context list** tool follows existing activation (`should_activate_context_tool` / admin file contexts) unless product narrows it. **`internal_attachments_get_content`** is registered (gating function: `should_enable_get_content_tool` in `_gating.py`) when the orchestrator deployment accepts input attachments (`input_attachment_types` non-empty) **and** either (a) **external URL fetching is policy-enabled** for the request — resolved via `ExternalUrlFetchPolicyResolver.resolve_reason() == "allowed"` — or (b) at least one request-visible file (admin context, expanded folder file, or user attachment) has MIME accepted by `input_attachment_types` via `matches_type`. Rationale for (a): once external fetching is on, an attachment url can reach the agent loop through **any** channel — the system prompt, a skill, the user message, or a tool result — not just a request-visible file, so the tool cannot be gated on request-visible files alone; it is always offered (and the model passes whatever url it encounters). Otherwise the tool is **absent** from the tool list so the model cannot call it. The **synthetic injector** still applies the **same per-attachment MIME gate** before emitting a pair — attachments whose MIME isn't accepted by the deployment are skipped, so the message history never references a tool the model hasn't been given. Tool descriptions still instruct: for admin files, list then fetch.
- **Transformer ordering:** The contract the model sees is the **message-list order**: get-content pair before notification pair, regardless of which transformer runs first. Two message transformers run during request setup: `_AttachmentGetContentInjector` (synthetic user-attachment get-content pairs) and `_AttachmentNotificationInjector` (context-list synthetic notification). The message-list order is preserved by each injector's choice of insertion site — the notification injector appends at the end of the message list (`InjectionFrequency.ALWAYS`), the get-content injector inserts immediately after the last USER message — so any execution order yields the same final list. The runtime execution order today happens to be *notification → get-content* because DI registration runs `AttachmentProcessingModule` before `LazyOnDemandStrategyModule` in `app_factory.py`, but this is incidental to the contract; `test_pre_transformer_pipeline_di.py` pins the message-list invariant, not the execution order.
- **Allowlist surfaced to the model:** The orchestrator's `input_attachment_types` is **published to the agent in two places** so it can plan without guessing.
  (1) The `internal_attachments_get_content` tool's function description and its `attachment_url` parameter description embed the accepted MIME patterns **verbatim** (wildcards like `image/*` preserved) as a **comma-joined human-readable string**. The static template description is appended with a sentence of the form: `Accepted MIME types: image/*, application/pdf, text/csv.` Rendering happens at registration time in `LazyOnDemandStrategyModule._provide_internal_tools` from the request-scoped `OrchestratorCapabilities.input_attachment_types`; the static `GET_CONTENT_TOOL_CONFIG` constant is treated as a template.
  (2) On rejection, `_GetContentTool._error_result` includes an `accepted_types` field as a **JSON array of raw patterns** (e.g. `"accepted_types": ["image/*", "application/pdf", "text/csv"]`) on **every** rejection path — not only the explicit "deployment does not accept this file type" branch (e.g. also the empty-argument and unsupported-scheme branches). Rationale: carrying `accepted_types` on every rejection gives the agent the same recovery signal regardless of which branch fires. When `input_attachment_types` is unset, the tool is never registered, so neither surface ever exposes an empty list to the model. Truncation: no cap is applied — `input_attachment_types` in practice contains a handful of MIME patterns; if it ever grows to dozens, the cap policy is a follow-up doc change rather than a guess made now.
- **Change:** Extend internal tool multiplexer with conditional registration for `internal_attachments_get_content`; render the live allowlist into the tool/parameter descriptions in `_provide_internal_tools`; include `accepted_types` (JSON array) in every error payload via `_GetContentTool._error_result`; sweep up the stale execution-order docstring in `test_pre_transformer_pipeline_di.py` when the rendering work lands; no change to external deployment tool contracts.

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

### Concern 6: Recovery scope for chat-completion failures

- **What:** The get-content recovery policy rewrites get-content TOOL bodies to a stable error payload and strips attachments so the orchestrator can retry without the offending file. The policy must not corrupt valid get-content data when the underlying error is unrelated (rate limit, 5xx, context-length, connection).
- **Owner:** `_GetContentRecoveryPolicy` under `quickapp.orchestrator_attachment_strategies.lazy_on_demand`.
- **Semantics:** Recovery proceeds **only** when the error is an `openai.BadRequestError` **and** the error `message` or `body` contains an attachment-related signal (`attachment`, `unsupported file`, `invalid file`, `input_attachment_types`, `image_url`, `file type`). All other errors propagate unchanged — the orchestrator's retry budget (one) is preserved for cases the policy is authorized to handle. The policy additionally returns `False` when no USER message exists in the conversation, so rehydrated histories that lack a current-turn anchor are not retroactively rewritten.
- **Change:** Narrow the gate from "any exception" to the BadRequest + signal combination; refuse recovery when no USER message is present; non-attachment errors are now re-raised by `ChatCompletionRecoveryService` for upstream handling.

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
4. Orchestrator: `internal_attachments_get_content` with that `url` → receives tool message with attachment.
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
| Internal tools | New **`internal_attachments_get_content`** when orchestrator accepts input attachments **and** either external URL fetching is policy-enabled or at least one request-visible file (admin context / expanded folder / user attachment) matches `input_attachment_types` (`matches_type` from `quickapp/common/utils.py`); list tool keeps existing admin-context gate. |
| Agent cache | New `CacheService[Deployment]` for orchestrator id under **`quickapp/core/agent/`**, independent of `DialDeploymentToolCacheService`. |
| Tool semantics | List remains admin-only; `internal_attachments_get_content` accepts any DIAL `files/` url (passthrough) or external `http(s)` url (promoted) whose MIME the orchestrator accepts — authorization is enforced upstream (DIAL Core / external-fetch policy), not by an in-app url allow-set; returns one attachment or error text. |
| Orchestrator input path | Narrow exception so **`internal_attachments_get_content`** results can retain allowed file types when the url is a DIAL `files/` storage path and its MIME passes DialCore `input_attachment_types`; USER message `custom_content.attachments` are filtered out and represented as XML metadata + synthetic get-content history for the last USER turn. |
| DialCore prefetch | Before first orchestrator completion call, load `Deployment` for orchestrator id via **agent** deployment cache; store `input_attachment_types` (request-scoped) for MIME-aware **`internal_attachments_get_content`** registration and filter behavior. |
| Config / ops | Optional: feature flag or per-app mode for lazy vs eager context surfacing. |
| Documentation | Admin and tool-description updates for list → `internal_attachments_get_content` and unsupported-MIME expectations. |
