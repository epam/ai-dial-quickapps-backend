# History Compaction Investigation

This note investigates how long conversation history is stored and compacted in coding agents, provider APIs, and agent
libraries, then maps those approaches to QuickApps. It is a companion to
[`history_compaction_strategy.md`](history_compaction_strategy.md), not a formal design document.

## Executive Summary

QuickApps' main constraint is that the frontend currently sends the full visible `messages` array to the backend on every
new user turn. The backend then restores assistant `custom_content.state.tool_execution_history` into assistant/tool
message pairs and sends an expanded effective history to the orchestrator model.

The most practical first step is backend-owned effective-history compaction:

1. The UI keeps sending the full visible transcript.
1. QuickApps stores a compacted checkpoint on the next assistant message under `custom_content.state`.
1. On later requests, the backend uses the latest valid checkpoint to ignore older messages for model input.
1. The model receives protected setup context, a synthetic compacted-history message, recent raw episodes, and the new
   user message.

This solves the model context-window problem without requiring a UI contract rewrite. UI-side transcript canonicalization
is still valuable, but it should be treated as a later performance and payload-size optimization.

No reviewed library is a clean drop-in for QuickApps. The best path is to copy proven reducer patterns from
LangChain/LangGraph and Semantic Kernel while keeping QuickApps-specific episode grouping, attachment handling,
`custom_content.state` checkpointing, and DIAL Chat Completions compatibility.

## Current UI to QuickApp Communication

Today's communication model is stateless from the backend's perspective:

1. The UI sends a full `messages` array for each turn.
1. `_MessagesSetup.extract_tool_calls` expands `custom_content.state.tool_execution_history` from assistant rows into
   assistant/tool message pairs.
1. Request-level message transformers run.
1. The orchestrator invokes the model and executes tools in a loop.
1. `Orchestrator._persisting_state` writes new `tool_execution_history` to the final assistant state via
   `choice.set_state(...)`.
1. The UI persists the assistant row and sends it back on the next turn.

This means the browser-visible transcript and backend-effective transcript are currently close to the same logical
history after restoration. History compaction introduces a useful distinction:

- **Visible transcript:** what the user sees and expects in the browser.
- **Effective model history:** what QuickApps sends to the orchestrator model after restoration, checkpoint selection,
  compaction, and recent-suffix selection.

Keeping those separate is the key to shipping useful compaction without forcing the UI to stop sending full history.

## Provider and Product Approaches

### Claude Code and Claude API

Claude Code and the Claude API use server-side or product-level compaction when conversations approach the context
window. Older conversation content is summarized into a structured compaction block. Later requests can continue from
that block instead of replaying every prior message.

Important traits:

- Compaction is lossy.
- The compacted representation is provider-native.
- Claude Code can manually compact with `/compact` and can automatically compact under context pressure.
- Durable instructions are safer on disk, for example in root `CLAUDE.md`, because pure chat history can be summarized
  away.
- The user-visible transcript may exist separately from the model's active compacted context.

Applicability to QuickApps:

- Strong conceptual fit: checkpoint plus recent suffix is the same core idea.
- Not directly portable unless QuickApps is using Anthropic APIs with their native `context_management` surface.
- The durable-instructions lesson applies: app configuration, system prompt, tool definitions, and required setup context
  should be regenerated or protected, not summarized as ordinary chat.

### Cursor

Cursor automatically summarizes long chats near the context limit and exposes manual summarization through `/summarize`.
Public details are less precise than Claude/OpenAI documentation, but the observed pattern is conventional prompt-based
conversation summarization.

Important traits:

- Summary becomes the seed for continued work.
- The process is lossy and can omit old rules, exact errors, or nuanced decisions.
- Cursor keeps the product chat experience separate from the model's compacted working context.

Applicability to QuickApps:

- Useful as product precedent: users can tolerate backend-effective compaction while the visible chat remains intact.
- Also a warning: generic prose summaries are not enough for tool-heavy agents. QuickApps needs structured tool outcomes,
  attachments, artifacts, decisions, and open questions.

### OpenAI Responses and Codex

OpenAI Responses supports native compaction in two ways:

- Server-side auto-compaction using `context_management` with a compact threshold.
- Explicit stateless compaction using `/responses/compact`.

The compacted output includes an opaque `type=compaction` item with encrypted content. That item must be round-tripped in
future Responses requests. It is not meant to be human-readable.

Important traits:

- Strongest provider-native support among the reviewed APIs.
- Designed for Responses API input/output items, not classic Chat Completions `messages`.
- Can preserve hidden reasoning state in provider-specific opaque form.
- The latest compaction item becomes the anchor; prior items can be omitted in stateless item-array chaining.

Applicability to QuickApps:

- Not a direct fit for the current DIAL Chat Completions path.
- Not portable across DIAL deployments, Anthropic, Gemini, or arbitrary model adapters.
- Useful as an optional future provider capability for OpenAI Responses deployments if DIAL exposes that surface.
- Very useful as a pattern: "opaque or structured checkpoint plus suffix" beats replaying full history.

### Common Agent Pattern

Most practical agents converge on this model:

1. Persist the full transcript for audit, UI, and recovery.
1. Build a smaller model-facing context per turn.
1. Protect system/setup context.
1. Keep the newest turns raw.
1. Summarize or structure older turns.
1. Treat tool-call groups as atomic units.

This matches the direction in `history_compaction_strategy.md`.

## Library Overview and QuickApps Applicability

### OpenAI Agents SDK

What it provides:

- `OpenAIResponsesCompactionSession` wraps a session backend and calls `responses.compact`.
- Supports automatic or forced compaction.
- Can compact based on a decision hook.
- Rewrites the underlying session with the compacted Responses item list.

Covered strategy areas:

- Checkpointing and latest-compaction-anchor behavior.
- Provider-native opaque compaction.
- Session storage rewrite after compaction.

Applicability to QuickApps:

- **Direct reuse:** Low for current QuickApps, because it targets OpenAI Responses items.
- **Adaptable ideas:** High. The session wrapper pattern is useful: an outer compaction layer can decorate an underlying
  history store and replace the effective history while preserving raw session data elsewhere.
- **Risk:** Pulling in the SDK would introduce a provider-specific model/runtime layer that conflicts with QuickApps'
  DIAL multi-provider abstraction.

### Pydantic AI

What it provides:

- `OpenAICompaction` for OpenAI Responses compaction.
- `AnthropicCompaction` for Anthropic context management.
- Provider-specific `CompactionPart` handling.
- Capability routing that chooses provider-native behavior where available.

Covered strategy areas:

- Provider capability abstraction.
- Native compaction blocks/items.
- Token-threshold-driven server-side compaction.

Applicability to QuickApps:

- **Direct reuse:** Low. Pydantic AI is an agent framework and model abstraction, while QuickApps already has its own DI,
  config, DIAL client, orchestrator, tools, and message pipeline.
- **Adaptable ideas:** Medium to high. The "capability" framing is useful if QuickApps later supports provider-native
  compaction for selected deployments while falling back to generic backend summaries for others.
- **Risk:** Provider-native compaction output may not be compatible with DIAL Chat Completions messages or the UI
  `custom_content.state` contract.

### LangChain and LangGraph

What they provide:

- Token-aware trimming utilities such as `trim_messages`.
- Running-summary memory patterns.
- Graph state with full checkpoints plus reduced LLM input.
- Summarization nodes that maintain a separate summary and keep recent messages raw.

Covered strategy areas:

- Sliding-window recent suffix.
- Token-budget trimming.
- Running summary plus recent raw tail.
- Full state persistence separated from model-facing state.

Applicability to QuickApps:

- **Direct reuse:** Low to medium. Individual utilities may be reusable only after adapting message types, but bringing in
  LangChain/LangGraph as a runtime would be excessive.
- **Adaptable ideas:** Very high. QuickApps should copy the pattern: full history remains available, while each model call
  receives a managed subset. The summary-plus-recent-suffix shape maps directly to `HistoryCompactionService`.
- **Gap:** Generic LangChain messages do not know about QuickApps `custom_content.attachments`,
  `custom_content.state.tool_execution_history`, DIAL files, artifacts, or tool-result propagation rules.

### Semantic Kernel

What it provides:

- Chat history reducers for truncation, token count, and summarization.
- A reducer abstraction that can sit in front of chat completion.
- Options to include function-call/function-result content in summaries.

Covered strategy areas:

- Reducer abstraction.
- Message-count and token-count thresholds.
- Summary message insertion.

Applicability to QuickApps:

- **Direct reuse:** Low. It is another framework with different message and tool abstractions.
- **Adaptable ideas:** High. A QuickApps-native `HistoryCompactionService` can act like a reducer over restored messages.
- **Important caution:** Tool-call pair preservation is a known sharp edge in reducer-style implementations. QuickApps
  must make assistant tool-call messages plus matching tool results an atomic episode boundary.

### LlamaIndex

What it provides:

- Token-limited short-term memory.
- Optional long-term memory blocks.
- Fact extraction and vector-memory blocks.
- Chat history flushing from short-term to long-term storage.

Covered strategy areas:

- Recent raw suffix.
- Long-term fact extraction.
- Retrieval-backed memory.

Applicability to QuickApps:

- **Direct reuse:** Low for MVP history compaction.
- **Adaptable ideas:** Medium for future memory features. Fact extraction or vector recall may help cross-session memory
  later, but they do not solve the immediate "UI sends full transcript and model context overflows" problem.
- **Risk:** Retrieval memory is not deterministic enough to replace an explicit compaction checkpoint for ongoing tasks.

## Strategy Coverage from `history_compaction_strategy.md`

The existing strategy has several QuickApps-specific concerns. Library coverage is partial:

| Strategy concern | Library support | QuickApps-specific work still needed |
|------------------|-----------------|--------------------------------------|
| Protected prefix | Common in trimmers; preserve system message | Decide which setup, skill, context-enrichment, and synthetic messages are protected or regenerated |
| Episode grouping | Some frameworks warn about tool pairs | Build a QuickApps `HistoryEpisodeBuilder` that understands assistant/tool pairs, attachments, stages, and checkpoints |
| Content-aware reducers | Generic summary memories exist | Implement reducers for tool outcomes, attachments, audio/transcripts, stage noise, and artifacts |
| Attachment/artifact registry | Mostly not covered | Store DIAL file URLs, generated artifacts, observed facts, and "referenced but not read" status |
| Compacted checkpoint state | Provider-native for OpenAI/Anthropic; summary state in frameworks | Define `custom_content.state.history_compaction` schema and validation |
| Recursive shrink | Usually not turnkey | Token-count compacted payload and retry shrink with ordered pruning |
| UI round-trip | Framework sessions handle their own stores | Fit the checkpoint into the existing assistant-message state the UI already preserves |

The conclusion is that libraries can inform the implementation but should not own it.

## Approaches Without UI Changes

### Option A: Backend-Only Effective-History Compaction

How it works:

- UI keeps sending full visible history.
- Backend finds the latest valid `history_compaction` checkpoint on an assistant message.
- Backend ignores messages before that anchor for model input.
- Backend injects a synthetic compacted-history assistant message and keeps recent raw episodes.
- Backend writes an updated checkpoint to the next assistant state.

Benefits:

- Minimal UI work.
- Solves the model context-window problem.
- Keeps browser transcript behavior unchanged.
- Fits current `custom_content.state` persistence.
- Allows QuickApps-specific structured compaction.

Effort:

- Medium to high backend effort.
- Requires token-count preflight, episode grouping, reducers, checkpoint schema, and tests.

Limitations:

- Browser still uploads full history.
- Backend still receives and parses full JSON.
- Old assistant rows can still carry large `tool_execution_history` until backend chooses to ignore them.
- UI cannot show a user-facing "this range was compacted" state unless we add UI work later.

Library fit:

- Best served by custom QuickApps code borrowing patterns from LangChain/LangGraph and Semantic Kernel.

### Option B: Backend Trim-Only Safety Valve

How it works:

- When context is too large, backend drops old messages or old tool bodies without summarizing.
- It preserves system/setup messages and recent episodes.

Benefits:

- Lower implementation effort than full summarization.
- Can prevent some over-limit calls quickly.

Effort:

- Low to medium.

Limitations:

- Loses important decisions and tool outcomes.
- Weak fit for long task continuity.
- Dangerous unless episode boundaries are exact.
- Does not satisfy attachment/artifact preservation goals.

Library fit:

- Similar to `trim_messages` or chat history truncation reducers.
- Still needs QuickApps message adaptation and tool-pair safety.

### Option C: Provider-Native Compaction Where Available

How it works:

- If a deployment supports native compaction, QuickApps enables it in provider-specific request settings or calls a
  provider-specific compact endpoint.
- Generic backend compaction remains the fallback.

Benefits:

- High quality for providers with first-class compaction.
- Can preserve provider-specific hidden reasoning state.
- Less custom summarization logic for supported providers.

Effort:

- Medium to high because DIAL must expose the provider capability and compaction items in a compatible way.

Limitations:

- Not portable across all DIAL deployments.
- Opaque compaction items do not map cleanly to Chat Completions `messages`.
- Harder to render, inspect, validate, or migrate.

Library fit:

- OpenAI Agents SDK and Pydantic AI are useful references, but direct use is unlikely.

### Option D: Long-Term Memory or Retrieval as a Complement

How it works:

- Old history is flushed into facts, vector memory, or a session store.
- Relevant memories are retrieved on later turns.

Benefits:

- Useful across long-lived sessions.
- Can preserve reusable user preferences, facts, or workflow lessons.

Effort:

- High if done well.

Limitations:

- Does not replace per-turn compaction.
- Retrieval can miss important context.
- Harder to prove correctness for ongoing tool-heavy tasks.

Library fit:

- LlamaIndex is the strongest inspiration here.
- Better suited for a later memory feature than MVP compaction.

## Suggested UI Changes

UI changes are best treated as phases. The first backend-only implementation should define the checkpoint shape so later
UI improvements can build on it.

### Less Invasive: Preserve and Surface Checkpoint State

What changes:

- UI keeps sending full history.
- UI guarantees unknown `custom_content.state` keys are persisted and resent.
- UI may display a small "history compacted" marker based on assistant state.

Benefits:

- Minimal contract change.
- Makes backend-only compaction reliable across reloads.
- Gives users some visibility without changing payload semantics.

Effort:

- Low to medium, depending on current serializer fidelity.

Library impact:

- Does not make provider libraries easier to use, but it preserves the backend's custom checkpoint.

### Moderately Invasive: Backend-Returned Compacted Effective Transcript

What changes:

- Backend returns a canonical compacted effective transcript or patch.
- UI stores both the visible transcript and a backend-sendable transcript.
- Future requests send the compacted effective transcript instead of the full visible transcript.

Benefits:

- Reduces upload size and backend parsing cost.
- Avoids repeatedly resending huge old `tool_execution_history`.
- Makes backend behavior more explicit and testable with before/after golden files.

Effort:

- Medium to high.

Risks:

- UI must avoid confusing "what user sees" with "what backend receives".
- Debugging needs tools to inspect both tracks.
- Message IDs and anchor validation become important.

Library impact:

- Makes OpenAI-style stateless compaction patterns easier to imitate because the compacted transcript can become the
  canonical next request payload.
- Still does not make OpenAI Responses compaction directly portable unless the model path also changes to Responses
  items.

### More Invasive: Dual Transcript Model

What changes:

- UI explicitly stores:
  - visible transcript for rendering;
  - model transcript for backend requests.
- Backend can send replacement model transcript chunks after compaction.
- UI may keep visible old messages while sending only checkpoint plus suffix.

Benefits:

- Best balance of UX and backend efficiency.
- Preserves user-visible history while reducing model and transport context.
- Enables clean UI markers for compacted ranges.

Effort:

- High.

Risks:

- Requires careful reconciliation when users branch, edit, retry, or resume conversations.
- Requires strong message identity and migration rules.

Library impact:

- Makes reducer/session-library concepts easier to apply because the UI has an explicit model-history store.
- Provider-native opaque compaction still needs provider-specific transport support.

### Most Invasive: Server-Owned Session History

What changes:

- UI sends a `session_id` plus new user input instead of the full message array.
- Backend owns the transcript, compaction, checkpointing, and replay.

Benefits:

- Eliminates repeated full-history upload.
- Allows robust backend-managed compaction and storage.
- Aligns with framework session models like OpenAI Agents SDK sessions or LangGraph checkpointers.

Effort:

- Very high.

Risks:

- Major API and product change.
- Requires session lifecycle, storage, retention, auth, replay, branching, and export semantics.
- Harder for stateless deployments.

Library impact:

- This is the path where session libraries become most applicable.
- It is likely too large for the first QuickApps history compaction milestone.

## Recommended Direction

Recommended path:

1. **Track 1: Backend-only effective-history compaction.**
   - Keep the UI contract unchanged.
   - Store a structured checkpoint in assistant `custom_content.state.history_compaction`.
   - Reconstruct effective history from checkpoint plus recent suffix.
   - Preserve tool-call episodes, attachments, artifacts, decisions, and open questions.

1. **Track 2: UI checkpoint fidelity and visibility.**
   - Confirm the UI preserves unknown state keys.
   - Optionally show compacted-history markers.

1. **Track 3: Optional UI canonicalization.**
   - Add a backend-returned compacted effective transcript or patch.
   - Let UI send the compacted model transcript while rendering full visible transcript.

1. **Track 4: Provider-native compaction and long-term memory.**
   - Add optional provider-native compaction when DIAL exposes compatible capabilities.
   - Consider LlamaIndex-like fact/vector memory only after MVP compaction is stable.

The investigation points toward a QuickApps-native implementation. Libraries provide useful vocabulary and algorithms,
but QuickApps' cross-provider DIAL surface, `aidial_sdk` message shape, `custom_content.state`, restored tool history,
and attachment/artifact semantics require a custom reducer and checkpoint service.

## Follow-Up Decisions

- **Feature placement:** Move history compaction under `features.history_compaction`. Enabling history compaction should also
  enable the backend context-usage measurement path, since compaction depends on provider-native token-count preflight.
  This fits the expected direction that `features.context_usage.enabled` may become enabled by default soon.
- **Checkpoint location:** `custom_content.state` is the practical place to round-trip compaction checkpoints in the
  current protocol, but it is a workaround rather than a clean long-term session-history model.
- **UI visibility:** Whether the UI should expose a visible "history compacted" marker needs discussion with Core, UI,
  and adapter teams.
- **Provider-native compaction:** A provider-neutral DIAL compaction capability may be possible, but it pulls in adapter
  team work and increases solution complexity. Treat it as a later optimization, not the MVP dependency.
