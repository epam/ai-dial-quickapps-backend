# Design: Orchestrator awareness of tool conversation mode (stateless vs full history)

**Status:** Design / investigation (no implementation)

## Goal

The orchestrator agent currently has **no explicit awareness** of whether a tool is stateless or a subagent that receives **full conversation history** when `propagate_history=True`. As a result, when the agent calls the same tool again (e.g. after gathering missing data from another tool), it does not know that the **previous assistant message and tool response for that tool will be sent to the tool** along with the new query. We need to provide that context so the orchestrator can:

1. **Know** which tools support history (conversation mode).
2. **Understand** that on a subsequent call to such a tool, the backend will send prior turns (assistant → tool → assistant → …) to the tool via `_extract_tool_history`.
3. **Choose** per call whether to use stateless or full_history when the tool supports both (via a `conversation_mode` enum).

---

## Context: Where history comes from

- **History is sent FROM the orchestrator’s conversation TO the tool (subagent).**
- When the orchestrator calls a DIAL tool that has `content_propagation.propagate_history=True`, `BaseDeploymentTool._run_in_stage_async` calls `_extract_tool_history(tool_name)`.
- `_extract_tool_history` (in `base_deployment_tool.py`) walks the current `messages` (orchestrator’s conversation), finds all **completed** (assistant + tool) pairs for **that tool name**, and builds a list of `[UserMessageParam, AssistantMessageParam, ...]` that is sent to the DIAL deployment as prior context.
- So for the **next** call to the same tool, the tool receives: previous user content (from the assistant’s tool call arguments), previous assistant content (from the tool’s response), then the new user content (from the current tool call arguments), and so on.

**Example (from requirements):**

- Tools: `get_employee_id_by_name`, `assign_badge` (subagent, full history).
- User: “Assign the badge ‘Happy 5th anniversary’ to John Smith.”
- Orchestrator → `assign_badge` with content “Assign the badge … to John Smith.”
- Tool → “Insufficient information, please enter EmployeeID.”
- Orchestrator → `get_employee_id_by_name` “Return employee id for John Smith.”
- Tool → “123456.”
- Orchestrator → `assign_badge` again with content “123456”.

On this **second** `assign_badge` call, the backend sends **3 messages** to the tool:

1. **User:** “Assign the badge Happy 5th anniversary to John Smith” (from first assistant tool call).
2. **Assistant:** “Insufficient information, please enter EmployeeID” (from first tool response).
3. **User:** “123456” (from second assistant tool call).

So the orchestrator should **know** that the second call only needs to send “123456” (or similar), because the first exchange is already part of the context the tool will receive. This requires **orchestrator awareness** of: (1) this tool supports history, and (2) previous history for this tool is pushed automatically with the new query.

---

## Proposed convention: `conversation_mode` enum

- **`stateless`** — single request; no prior context is sent to the tool.
- **`full_history`** — prior conversation for this tool (previous assistant + tool turns) is sent to the tool; default when the tool supports history and the param is omitted.

Only tools that support history (e.g. `propagate_history=True`) expose this parameter; others are implicitly stateless. The enum can be extended later (e.g. `conversation_summary`).

---

## Block diagram (placeholder)

<!-- TODO: Add block-scheme drawing here -->

**Text description of the block-scheme:**

1. **User** sends a message to the **Orchestrator** (e.g. “Assign badge … to John Smith”). The orchestrator’s **message context** holds the full conversation (user, assistant, tool, …).

2. **Orchestrator** (LLM) receives **tool definitions** that include, for tools with `propagate_history=True`, the optional parameter **`conversation_mode`** and a **description** stating that this tool supports conversation history and that on each new call the **previous** assistant message and tool response for this tool are sent to the tool together with the new input.

3. **Orchestrator** decides to call a tool (e.g. `assign_badge`) and may set `conversation_mode` to `"stateless"` or `"full_history"`. The call goes to **ToolExecutor**, which invokes the corresponding **StagedBaseTool** (e.g. **BaseDeploymentTool**) with the tool call arguments.

4. **BaseDeploymentTool** resolves the effective mode (from `conversation_mode` argument or config default). If effective mode is full_history and `propagate_history=True`, it calls **`_extract_tool_history(tool_name)`** over the current **messages** (orchestrator context) to build the list of prior [user, assistant] pairs for this tool. It then calls **DialCompletionService.complete_request_async(..., history=history)**. The **`conversation_mode`** parameter is stripped and not sent to the DIAL deployment.

5. **DIAL deployment (subagent)** receives the **history** (prior user/assistant messages for this tool) plus the **new** user content from the current tool call. It responds; the response is returned to the orchestrator as a **tool message**.

6. **Orchestrator** appends the assistant message (with tool_calls) and the tool message to its context. On the **next** iteration, if it calls the same tool again, it is **aware** (from the tool description) that the previous exchange for this tool will already be in the history sent to the tool, so it can send only the new information (e.g. “123456”).

7. **Flow summary:** Orchestrator ↔ (tool definitions with conversation_mode + description) ↔ ToolExecutor ↔ BaseDeploymentTool ↔ _extract_tool_history(messages) → history → DialCompletionService → DIAL deployment. Awareness is provided **only** via the tool schema (description + optional `conversation_mode` parameter) that the orchestrator LLM sees.

---

## Approaches to achieve orchestrator awareness

We consider two **schema-only** approaches: all awareness is encoded in the OpenAI tool schema (description + optional `conversation_mode` parameter). They differ in the **length and style** of the tool description.

---

### Approach 1: Tool schema only (full description + `conversation_mode` parameter)

**Idea:** Encode all awareness in the **OpenAI tool schema** that the orchestrator receives: extend the tool **description** and add an optional **`conversation_mode`** parameter only for tools with `propagate_history=True`.

**Where:**

- **Tool schema construction:** In the path that builds the list of tools for the orchestrator (e.g. `AgentModule.provide_openai_tools` or a dedicated deployment-tool schema builder). For each tool whose config has `content_propagation.propagate_history is True`:
  - Append (or merge) a description block that states:
    - This tool is a **subagent** / supports **conversation history**.
    - When you call it again, the **previous** assistant message and tool response for this tool are **automatically sent to the tool** along with your new input; you do not need to repeat the full conversation.
    - Use **`conversation_mode`**: `"stateless"` for a single request without prior context, or `"full_history"` (default) to continue the conversation with prior context.
  - Add optional parameter: `conversation_mode` with enum `["stateless", "full_history"]`, with a short description (e.g. “Use stateless for one-off request; full_history to send prior conversation for this tool.”).
- **BaseDeploymentTool:** Read `conversation_mode` from `kwargs`; resolve effective mode (param or default full_history when propagate_history); if stateless, pass `history=None`; if full_history, call `_extract_tool_history` as today; strip `conversation_mode` from params before calling the deployment.

**Pros:**

- Single source of truth (tool schema).
- No duplication with system prompt.
- Works with any orchestrator model that respects tool descriptions and parameters.
- Maximum clarity: every concept (subagent, automatic history, when to use each mode) is spelled out.

**Cons:**

- Relies on the LLM faithfully reading long descriptions; some models may underuse or skip them.
- Higher token usage per tool (description is repeated in every request that includes tools).

---

### Approach 2: Structured description + minimal parameter (schema-only, compact)

**Idea:** Same as Approach 1 but with a **short, standardized** phrase in the tool description and a **minimal** `conversation_mode` parameter description, to reduce token usage and keep behaviour consistent.

**Where:**

- **Tool description:** Append a single sentence or two, e.g. “Supports conversation history: on each new call, prior assistant and tool messages for this tool are sent to the tool. Use conversation_mode: stateless (no context) or full_history (default).”
- **Parameter:** `conversation_mode` enum with a one-line description.
- **BaseDeploymentTool:** Same as Approach 1.

**Pros:**

- Lower token count than a long paragraph; still self-contained in the schema.
- Predictable wording across tools; easier to tune once and reuse.
- Same implementation surface as Approach 1 (only the text constants differ).

**Cons:**

- Slightly less room for nuance than a longer description (e.g. "subagent" or "do not repeat the full conversation" may be implied rather than stated).
- Denser text may be overlooked by models that tend to skim.

---

## Detailed comparison: Approach 1 vs Approach 2

| Criterion | Approach 1 (full description) | Approach 2 (compact description)                                                                                                                                                       |
|-----------|-------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Single source of truth** | Yes: all semantics in the tool schema. | Yes: same as Approach 1.                                                                                                                                                               |
| **Token usage** | **Higher.** Multi-sentence description (subagent, automatic history, when to use each mode) per tool with `propagate_history=True`. With many such tools, the total tool-definition size grows. | **Lower.** One or two sentences per tool. Fixed, reusable template keeps total size smaller and more predictable.                                                                      |
| **Clarity for the orchestrator** | **Higher.** Explicit mention of "subagent", "you do not need to repeat the full conversation", and separate bullets for behaviour vs parameter. Best for models that read full descriptions. | **Good but denser.** All key facts are present (history is sent, stateless vs full_history) but in compact form. May be sufficient for models that pay attention to tool descriptions. |
| **Risk of LLM underuse** | Long text may be skimmed or truncated in context; critical sentence might be at the end. | Shorter text is more likely to be read in full; critical info is in one place.                                                                                                         |
| **Maintenance and consistency** | Descriptions can drift if edited per tool (e.g. different wording for "prior context"). | Single template or constant; wording is identical across tools, so behaviour is easier to reason about and to test.                                                                    |
| **Implementation scope** | Same: AgentModule (or schema builder) + BaseDeploymentTool. Only the **content** of the appended description and the parameter description string differ. | Same as Approach 1. Easier to keep description in a constant or small template.                                                                                                        |
| **Extensibility** | Adding a new enum value (e.g. `conversation_summary`) requires updating the description text and the parameter schema in one place per approach. | Same; compact template may need one extra line for the new mode.                                                                                                                       |
| **Localisation / A/B testing** | Longer text gives more room to rephrase for different locales or to run experiments (e.g. "subagent" vs "conversational tool"). | Less room; changes are minimal and global.                                                                                                                                             |
| **When to prefer** | Prefer when orchestrator models are known to use long tool descriptions and when maximum explicitness is desired (e.g. complex multi-tool flows). | Prefer when token budget matters (many tools or long conversations) or when a single, consistent phrase is enough and easier to maintain.                                              |

**Summary:** Both approaches keep awareness entirely in the tool schema and share the same backend behaviour. The trade-off is **explicitness and token cost (Approach 1)** vs **brevity and consistency (Approach 2)**. Choice can be driven by observed model behaviour (how well they follow compact vs full descriptions) and by total tool-definition size in production.

---

## Backend behaviour (unchanged by approach choice)

- **History extraction:** `BaseDeploymentTool._extract_tool_history(tool_name)` continues to build history from the **orchestrator’s** `messages` (assistant messages with tool_calls for that tool + corresponding tool messages). That history is sent **to** the DIAL deployment. No change to the extraction logic is required for “awareness”; only the **schema and optionally prompt** need to describe this behaviour to the orchestrator.
- **Resolve and strip:** When the orchestrator sends `conversation_mode`, BaseDeploymentTool resolves effective mode (stateless vs full_history), passes or omits `history`, and strips `conversation_mode` from the params sent to the deployment.
- **History from tool (subagent → orchestrator):** As in the existing design (`conversation_mode_dial_tools.md`), when a tool with `propagate_history=True` returns its own message history, that history must be **treated** when appended to the orchestrator (e.g. as tool/subagent and subtool responses). That is independent of how we inform the orchestrator about **outgoing** history (to the tool).

---

## Summary

- **Goal:** Orchestrator knows (1) which tools support history, (2) that previous assistant + tool messages for that tool are sent to the tool on the next call, and (3) can choose stateless vs full_history via `conversation_mode`.
- **Convention:** `conversation_mode` enum: `stateless` | `full_history`; only for tools with `propagate_history=True`.
- **Approaches:** Two schema-only options: (1) full description + `conversation_mode` parameter, (3) compact description + same parameter. See detailed comparison above.
- **Recommendation:** Implement **Approach 1 or 2** (tool schema: description + `conversation_mode` parameter); choose based on token budget and desired explicitness (see comparison table).
- **Block-scheme:** Placeholder left above; text description documents the flow from user → orchestrator → tool schema → ToolExecutor → BaseDeploymentTool → _extract_tool_history → DIAL deployment, and that awareness is provided via the tool schema the orchestrator sees.
