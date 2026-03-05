# Design: Orchestrator awareness of tool conversation mode (stateless vs full history)

**Status:** Design / investigation (no implementation)

## Goal

The orchestrator agent currently has **no explicit awareness** of whether a tool is stateless or a subagent that receives **full conversation history** when `propagate_history=True`. As a result, when the agent calls the same tool again (e.g. after gathering missing data from another tool), it does not know that the **previous assistant message and tool response for that tool will be sent to the tool** along with the new query. We need to provide that context so the orchestrator can:

1. **Know** which tools support history.
2. **Understand** that on a subsequent call to such a tool, the backend will send prior turns (assistant → tool → assistant → …) to the tool via `_extract_tool_history`.

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

## Block diagram (placeholder)

<!-- TODO: Add block-scheme drawing here -->

**Text description of the block-scheme:**

1. **User** sends a message to the **Orchestrator** (e.g. “Assign badge … to John Smith”). The orchestrator’s **message context** holds the full conversation (user, assistant, tool, …).

2. **Orchestrator** (LLM) receives **tool definitions** that include, for tools with `propagate_history=True`, a **description suffix** stating that this tool supports conversation history and that on each new call the **previous** assistant message and tool response for this tool are sent to the tool together with the new input.

3. **Orchestrator** decides to call a tool (e.g. `assign_badge`). The call goes to **ToolExecutor**, which invokes the corresponding **StagedBaseTool** (e.g. **BaseDeploymentTool**) with the tool call arguments.

4. **BaseDeploymentTool**: when `propagate_history=True`, it calls **`_extract_tool_history(tool_name)`** over the current **messages** (orchestrator context) to build the list of prior [user, assistant] pairs for this tool. It then calls **DialCompletionService.complete_request_async(..., history=history)**.

5. **DIAL deployment (subagent)** receives the **history** (prior user/assistant messages for this tool) plus the **new** user content from the current tool call. It responds; the response is returned to the orchestrator as a **tool message**.

6. **Orchestrator** appends the assistant message (with tool_calls) and the tool message to its context. On the **next** iteration, if it calls the same tool again, it is **aware** (from the tool description) that the previous exchange for this tool will already be in the history sent to the tool, so it can send only the new information (e.g. “123456”).

7. **Flow summary:** Orchestrator ↔ (tool definitions with description suffix for history-supporting tools) ↔ ToolExecutor ↔ BaseDeploymentTool ↔ _extract_tool_history(messages) → history → DialCompletionService → DIAL deployment. Awareness is provided **only** via the tool description suffix that the orchestrator LLM sees.

---

## Approach: description suffix only

All tools with **`propagate_history=True`** get a **description suffix** appended to their tool description. No extra parameter. The suffix states that the tool supports conversation history and that on each new call, prior assistant and tool messages for this tool are sent automatically.

**Where:**

- **Tool description:** For each tool with `propagate_history=True`, append a short suffix, e.g. “Supports conversation history: on each new call, prior assistant and tool messages for this tool are sent automatically.”
- **BaseDeploymentTool:** When `propagate_history=True`, always call `_extract_tool_history` and pass history to the deployment (no param to read or strip).

Schema enrichment is implemented in the dial deployment tool layer (e.g. `BaseDeploymentTool.enrich_openai_tool_schema`), so the agent module stays decoupled from deployment-tool specifics.

---

## Backend behaviour

- **History extraction:** `BaseDeploymentTool._extract_tool_history(tool_name)` builds history from the **orchestrator’s** `messages` (assistant messages with tool_calls for that tool + corresponding tool messages). That history is sent **to** the DIAL deployment. No change to the extraction logic is required for “awareness”; only the **schema and optionally prompt** need to describe this behaviour to the orchestrator.
- **History from tool (subagent → orchestrator):** As in the existing design (`conversation_mode_dial_tools.md`), when a tool with `propagate_history=True` returns its own message history, that history must be **treated** when appended to the orchestrator (e.g. as tool/subagent and subtool responses). That is independent of how we inform the orchestrator about **outgoing** history (to the tool).

---

## Summary

- **Goal:** Orchestrator knows (1) which tools support history and (2) that previous assistant + tool messages for that tool are sent to the tool on the next call.
- **Approach:** Tools with `propagate_history=True` get a **description suffix** only (no extra parameter). Applied in the deployment tool layer (`enrich_openai_tool_schema`).
- **Block-scheme:** Placeholder left above; text description documents the flow from user → orchestrator → tool schema → ToolExecutor → BaseDeploymentTool → _extract_tool_history → DIAL deployment, and that awareness is provided via the tool description suffix the orchestrator sees.
