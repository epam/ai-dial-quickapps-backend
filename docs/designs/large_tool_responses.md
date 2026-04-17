# Design: Large Tool Response Processing

- **Status:** Draft
- **Dependencies:**
  - None
- **Related:** [Issue #64](https://github.com/epam/ai-dial-quickapps-backend/issues/64)

## Problem Statement

Tool responses (REST, MCP, internal, DIAL deployment) are currently appended to the canonical message history verbatim. When a tool returns a large text response (e.g., a web page dump, a log snippet, a large JSON payload), two problems emerge:

1. **Token waste** — the entire response is sent to the LLM on every subsequent iteration, consuming context window and money.
2. **Poor UX in the stage** — the full response is rendered in the DIAL stage and is effectively unreadable.

There is also **no extension point** in the current pipeline for transforming `CompletionResult.content`. `CompletionResultEnricher` exists, but it is scoped to enrichment of `result.state` (metadata), not content transformation. `MessagesTransformer` and `PreInvocationTransformer` operate on the message list before LLM calls and do not persist changes to the canonical history — wrong layer for one-time offload.

## Design Goals

- Provide a generic extension point for post-processing `CompletionResult` in `ToolExecutor`, applied **once** per tool call and persisted to canonical history.
- Implement **large response offload** as the first consumer of this extension point: detect oversized responses by size alone (no content-type filtering in v1), upload them to DIAL file storage, replace the response content with a short reference + attachment.
- Give the agent **file-reading tools** to pull content back on demand (line range, char range, substring search with optional context).
- Keep performance impact **negligible for small responses**; net-positive for large ones (trades one HTTP upload for smaller LLM context).
- Make the extension point **future-ready for a configuration hierarchy** (global → application → toolset → tool), without paying the cost of hierarchy logic today.
- **Fail-open** on upload errors: a broken DIAL file storage must not break agent iterations.

---

## Use Cases

### UC-1: Large response is offloaded

**Trigger:** Any tool (REST, MCP, DIAL deployment, internal) returns a response whose `content` length exceeds the configured threshold.\
**Behavior:** `LargeResponseProcessor` detects `len(content) ≥ threshold` and (the tool is not in the exclusion list). Content is uploaded to DIAL file storage. The `CompletionResult.content` is replaced with a short notice containing the file URL and instructions to use `read_file_lines` / `read_file_chars` / `search_in_file`. The file is attached to the result.\
**Outcome:** Canonical history contains only the short notice + attachment. The stage shows a compact, readable message. The LLM sees a small message and a file it can read on demand.

### UC-2: Agent searches inside an offloaded file

**Trigger:** The LLM calls `search_in_file(file_url=..., pattern="error", context_lines=2)`.\
**Behavior:** The tool downloads the file from DIAL storage, performs a substring search, returns matching chunks with ±2 lines of context as `CompletionResult(content=..., content_type="text/plain")`.\
**Outcome:** The LLM gets a focused snippet instead of the full file; it can iterate.

### UC-3: Agent requests too much back → recursive offload

**Trigger:** The LLM calls `read_file_lines(start=0, end=100000)` on a very large file.\
**Behavior:** The read tool returns a `CompletionResult` with the large content. Because `search_in_file` / `read_file_*` tools are in the exclusion list, `LargeResponseProcessor` **skips** them — the large content **is not re-offloaded**. The LLM sees its own oversized request filling the context.\
**Outcome:** The LLM learns (from context cost / follow-up iterations) to request smaller slices. No infinite loop; no duplicate storage of the same data.

### UC-4: DIAL file storage is unavailable during offload

**Trigger:** Upload to DIAL file storage fails with a 5xx error.\
**Behavior:** `LargeResponseProcessor` logs a warning and returns the original `CompletionResult` unchanged (fail-open).\
**Outcome:** Large content goes into the LLM context — not ideal, but the agent iteration completes. No user-visible error.

---

## Proposed Design

### Component 1: `CompletionResultProcessor` (new abstraction)

**What:** A new async interface that transforms a `CompletionResult` after tool execution.

```python
# src/quickapp/common/abstract/completion_result_processor.py

class ProcessingContext(BaseModel):
    tool_call_id: str | None
    tool_name: str
    # Future: application/toolset/tool-level config overrides

class CompletionResultProcessor(ABC):
    priority: int = 100  # lower = earlier in chain

    @abstractmethod
    async def process(
        self,
        result: CompletionResult,
        ctx: ProcessingContext,
    ) -> CompletionResult: ...
```

**Owner:** `ToolExecutor` collects all bound `CompletionResultProcessor` instances via DI and applies them in priority order after `CompletionResultEnricher`s have run.

**Semantics:**
- Each processor returns a (possibly new) `CompletionResult`. The returned value is the input for the next processor.
- Processors are sorted by `priority` at application time (lower first). Ordering is **explicit**, not dependent on module registration order.
- `ProcessingContext` carries tool identity for routing decisions. It is constructed by `ToolExecutor` from the current tool call.

**Change:** New file. `ToolExecutor.execute()` gets a new DI dependency `list[CompletionResultProcessor]` and a new step after the enricher loop.

---

### Component 2: `ToolExecutor` changes

**What:** Add processor invocation after enricher invocation.

**Current (simplified):**
```python
for tool_call in tool_calls:
    result = await tool.arun(tool_call.id, **args)
    for enricher in self._enrichers:
        enricher.enrich(result)
    results.append(result)
```

**New:**
```python
processors = sorted(self._processors, key=lambda p: p.priority)
for tool_call in tool_calls:
    result = await tool.arun(tool_call.id, **args)
    for enricher in self._enrichers:
        enricher.enrich(result)
    ctx = ProcessingContext(tool_call_id=tool_call.id, tool_name=tool_call.function.name)
    for processor in processors:
        result = await processor.process(result, ctx)
    results.append(result)
```

**Owner:** `src/quickapp/agent/tool_executor.py`

**Change:** New constructor parameter (list of processors), new sort + loop after enrichers. Sort is done once per `execute()` call (cheap; list is small).

---

### Component 3: `LargeResponseProcessor` (first consumer)

**What:** First concrete implementation of `CompletionResultProcessor`. Detects oversized responses (by size only, regardless of content type) and offloads them.

**Module:** `src/quickapp/large_response_tooling/`

**Algorithm:**
1. If processor disabled → return result unchanged.
2. If `ctx.tool_name in self._excluded_tools` → return result unchanged.
3. If `len(result.content) < self._size_threshold` → return result unchanged.
4. Upload `result.content` to DIAL file storage via `AttachmentService`, path `files/{bucket}/offloaded-responses/{tool_name}-{iso8601_timestamp}.txt` (see note on extension below).
5. On upload failure → log warning, return original result (**fail-open**).
6. On success → return a new `CompletionResult` with:
   - `content` = short notice containing file URL + usage hint (read_file_lines / read_file_chars / search_in_file)
   - `attachments` += an attachment pointing to the uploaded file (title includes tool name); attachment's media type preserves the original `result.content_type` when set, else `text/plain`
   - `state["offloaded_response"]` = `{file_url, original_size, content_type}` (metadata only)

**Note on content type / extension:** Size-only filtering is intentional for v1. The original `content_type` is preserved on the attachment so DIAL can render it. The stored file name uses a `.txt` extension as a conservative default since responses are always treated as text strings; extension-from-content-type is deferred (see Out of Scope). This does not affect the LLM's ability to read the file back — read tools operate on bytes/lines regardless of extension.

**Settings:** `LargeResponseSettings` (pydantic-settings), registered as singleton.
- `size_threshold: int` — character threshold (compared against `len(result.content)`); starting default `4000`, tuned during implementation
- `excluded_tools: set[str]` — default `{"read_file_lines", "read_file_chars", "search_in_file"}`
- `enabled: bool` — default `True`

**Priority:** `100` (default). No other processors planned today.

**Owner:** `src/quickapp/large_response_tooling/_large_response_processor.py`

---

### Component 4: `text_file_tooling` (new internal toolset)

**What:** Three new internal tools registered via `InternalToolModule`, enabled alongside the processor.

**Tools:**

| Tool | Parameters | Behavior |
|------|------------|----------|
| `read_file_lines` | `file_url: str`, `start_line: int`, `end_line: int` | Download file, split by `\n`, slice `[start_line:end_line]`. Return as `text/plain`. |
| `read_file_chars` | `file_url: str`, `start_char: int`, `end_char: int` | Download file, slice `[start_char:end_char]`. Return as `text/plain`. |
| `search_in_file` | `file_url: str`, `pattern: str`, `context_lines: int = 0`, `case_insensitive: bool = False` | Download file, substring search line-by-line, return matching lines ± `context_lines` as `text/plain`. |

**Error handling:** Invalid input (bad range, missing file, etc.) → `InvalidToolCallParameterException` → existing `FallbackProcessor` returns the error to the LLM as a tool-call error.

**Behavior under re-offload:** Their results bypass `LargeResponseProcessor` (via `excluded_tools` default). If the LLM requests a too-large slice, it pays the context cost directly — expected self-correction loop (UC-3).

**Owner:** `src/quickapp/large_response_tooling/` (same module as the processor — they are co-designed).

---

### Component 5: `LargeResponseToolingModule` (DI wiring)

**What:** New `injector.Module` that:

- Binds `LargeResponseSettings` as singleton.
- Provides `LargeResponseProcessor` into the `list[CompletionResultProcessor]` multiprovider.
- Provides the three text-file tools into the internal tool set multiprovider.
- Registers itself in `src/quickapp/app_factory.py` alongside other feature modules.

**Owner:** `src/quickapp/large_response_tooling/large_response_tooling_module.py`

**Change:** New file; one-line addition in `app_factory.py`.

---

## Data Flow

**Offload (write path):**
```
Tool.arun() → CompletionResult{content=<large>, content_type=<any>}
  → Enrichers (state metadata, as today)
  → Processors sorted by priority:
      LargeResponseProcessor:
        tool not excluded? size ≥ threshold?
          → upload to files/{bucket}/offloaded-responses/...
          → return CompletionResult{content=<short notice>, attachments=[file]}
  → ToolExecutor returns result
  → Orchestrator appends to canonical message history (short notice is what persists)
```

**Read-back (read path):**
```
LLM calls read_file_lines(...) / read_file_chars(...) / search_in_file(...)
  → Tool downloads file via DialFileService (request-scoped file download cache exists)
  → Returns CompletionResult with the requested slice
  → Enrichers run
  → Processors run — but tool name is in excluded_tools → no re-offload
  → Orchestrator appends result to canonical history
```

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Upload to DIAL storage fails | **Fail-open**: log warning, return original `CompletionResult` unchanged. |
| Invalid range / bad input to text-file tools | `InvalidToolCallParameterException` → existing `FallbackProcessor` returns tool-call error to LLM. |
| File URL missing or unreachable during read-back | Same as above — tool returns a meaningful error the LLM can act on. |
| LLM requests a huge slice | Result is not re-offloaded (tool in `excluded_tools`). Large content goes to the LLM context directly — expected self-correction. Optional: log a warning for monitoring. |

---

## Out of Scope

- **Regex search.** `search_in_file` ships with substring + `case_insensitive` only. Regex requires DoS protection (timeout, catastrophic backtracking mitigation via the `regex` library), bounds checks, and careful error surfaces. Addressed in a follow-up design when the use case becomes concrete.
- **Content-type-based routing.** v1 applies size-only filtering — any large `content` is offloaded regardless of `content_type`. Future work: allow-list / deny-list per content type, per-type processors (e.g., compress JSON differently from plain text), extension-from-content-type for stored file names.
- **Configuration hierarchy (global → app → toolset → tool).** Interface is designed to accept a richer `ProcessingContext` in the future, but today only a single global `LargeResponseSettings` applies. Next step is defining how app/toolset/tool configs compose.
- **Explicit file cleanup / retention.** Offloaded files live in the same DIAL bucket as all other attachments and inherit DIAL Core's retention policy. No QuickApps-side cleanup today.
- **Caching strategy for read-back downloads.** `DialFileService` already caches within a request; whether to extend or introduce additional caching (e.g., LRU per file URL) is deferred to implementation, based on observed behavior.
- **Additional processors** (compression, PII scrubbing, format conversion). The abstraction supports them; concrete processors are not part of this design.

---

## Configuration / Usage Examples

### Environment variables (pydantic-settings)

```
LARGE_RESPONSE__ENABLED=true
LARGE_RESPONSE__SIZE_THRESHOLD=4000
LARGE_RESPONSE__EXCLUDED_TOOLS=["read_file_lines","read_file_chars","search_in_file"]
```

### LLM-visible notice (example content the LLM sees after offload)

```
Response from 'fetch_logs' was too large (124312 chars) and
has been saved to: https://dial-storage/.../offloaded-responses/fetch_logs-2026-04-17T10:30:45.123.txt
Use one of:
  - read_file_lines(file_url, start_line, end_line)
  - read_file_chars(file_url, start_char, end_char)
  - search_in_file(file_url, pattern, context_lines=0, case_insensitive=False)
```

### Adding a new processor (future)

```python
class MyProcessor(CompletionResultProcessor):
    priority = 50  # runs before LargeResponseProcessor (100)

    async def process(self, result, ctx):
        ...
        return result

# In some_module.py:
@multiprovider
def _provide_processors(self, p: MyProcessor) -> list[CompletionResultProcessor]:
    return [p]
```

---

## Migration

### Breaking changes

None. Existing tool responses smaller than the threshold pass through unchanged. `ToolExecutor`'s constructor gains a new DI dependency but DI wiring is automatic.

### Non-breaking changes

- New optional DI binding `list[CompletionResultProcessor]`. Defaults to an empty list if no module provides processors (via existing `@multiprovider` semantics, the binding resolves to an empty list when no providers exist; confirm during implementation).
- New internal tools are only registered when `LargeResponseToolingModule` is loaded — they are not visible to the LLM otherwise.
- Feature can be disabled entirely via `LARGE_RESPONSE__ENABLED=false`.

---

## Summary of Changes

### New files

| File | Purpose |
|------|---------|
| `common/abstract/completion_result_processor.py` | `CompletionResultProcessor` ABC, `ProcessingContext` model |
| `large_response_tooling/_large_response_processor.py` | First processor implementation |
| `large_response_tooling/_read_file_lines_tool.py` | `read_file_lines` internal tool |
| `large_response_tooling/_read_file_chars_tool.py` | `read_file_chars` internal tool |
| `large_response_tooling/_search_in_file_tool.py` | `search_in_file` internal tool |
| `large_response_tooling/_settings.py` | `LargeResponseSettings` pydantic-settings |
| `large_response_tooling/large_response_tooling_module.py` | DI wiring |

### Modified files

| File | Change |
|------|--------|
| `agent/tool_executor.py` | Inject `list[CompletionResultProcessor]`, sort by priority, apply after enrichers |
| `app_factory.py` | Register `LargeResponseToolingModule` |

### New interfaces

- `CompletionResultProcessor.process(result, ctx) -> CompletionResult`
- `ProcessingContext(tool_call_id, tool_name)`

### Tests

- Unit: `src/tests/large_response_tooling/` covering threshold / content-type / exclusion / fail-open branches and each text-file tool.
- Integration: end-to-end case with a large REST response in the existing integration suite; recursive-read-back case (UC-3).
