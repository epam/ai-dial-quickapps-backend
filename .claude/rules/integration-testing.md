---
paths:
  - "src/tests/integration_tests/**"
---

# Integration & E2E Testing

## Location

`src/tests/integration_tests/`

## Running

```bash
make integration_test MODEL=<model>                  # from cache
REFRESH=TRUE make integration_test MODEL=<model>     # build cache against live DIAL Core(only if it is absence)
make e2e_test                                         # happy-path e2e (always live)
```

Prerequisites in `.env`:
```
REMOTE_DIAL_URL=...
REMOTE_DIAL_API_KEY=...
```

## Test Files

| File | What it tests |
|------|--------------|
| `test_simple_tool.py` | Single-tool scenarios (image gen, web search, RAG, PyInterpreter, REST API, MCP) |
| `test_multi_tool.py` | Multi-tool chaining and multi-turn conversations |
| `test_e2e.py` | Happy-path smoke tests (always live, no cache) |

## Writing a New Test

### Basic Pattern

```python
@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        name="Image generation",
        description="Generate image",
        similarity_threshold=0.8,
    ).add_user_message(
        user_message="Draw an elephant",
        tool_calls=[
            ToolCall(ToolNames.IMAGE_GENERATION_TOOL.value)
            .add_soft_argument_check("query", ["elephant"])
            .add_strict_argument_check("size", "512x512")
        ],
        answer=["Here is the image", "Your image is ready"],
    ),
)
def test_image(client):
    pass
```

The test function body is almost always empty — assertions happen in the decorator via `TstCase`.

### `@e2e_test` Decorator Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `test_case` | required | `TstCase` defining the scenario |
| `config_file_set` | `"e2e"` | Which toolsets to load (see below) |
| `model` | None | Override model for this specific test |
| `models_applicable_for_test` | None | Whitelist of models this test applies to |
| `runs` | `3` | Number of times to repeat the test |
| `no_cache` | `False` | Bypass cache for this test |
| `refresh` | env `REFRESH` | Override cache refresh for this test |
| `app_config_path` | None | Custom app config path |

### `config_file_set` Values

| Value | Toolsets loaded |
|-------|----------------|
| `"integration"` | chat_hub (RAG, image gen, web search) + py_interpreter + MCP + REST API |
| `"integration_simple"` | chat_hub only |
| `"e2e"` | chat_hub + py_interpreter |

### `TstCase` Construction (Builder Pattern)

```python
TstCase(name="...", description="...", similarity_threshold=0.9, response_format=None)
    .add_user_message(
        user_message="...",
        tool_calls=[...],            # expected tool invocations
        answer=["alt1", "alt2"],     # acceptable response alternatives
        attachments=[Path(...)],     # files to upload
        attachment_checks=[...],     # expected attachments in response
    )
    .add_mock_date(date_obj)         # for date-dependent tests
    .add_py_interpreter_session_flow()  # reuse interpreter session across turns
```

Multi-turn: chain multiple `.add_user_message()` calls. Each message gets its own tool call and answer expectations.

### Argument Check Types

| Method | Behaviour |
|--------|-----------|
| `.add_strict_argument_check(key, value)` | Exact string equality |
| `.add_soft_argument_check(key, [alternatives], threshold=0.9)` | Cosine similarity (BAAI/bge-small-en-v1.5) against any alternative |
| `.add_custom_function_argument_check(key, [values], func)` | Custom predicate (`CustomFunction.contains` or `CustomFunction.not_contains`) |

### Similarity Thresholds

| Constant | Value | Use for |
|----------|-------|---------|
| `SimilarityThreshold.DEFAULT` | 0.9 | Most tests |
| `SimilarityThreshold.STRICT` | 0.95 | Exact wording matters |
| `SimilarityThreshold.LENIENT` | 0.8 | Creative / variable outputs |

Test-level threshold cascades to all child `ToolCall` and `Argument` objects unless overridden.

### Tool Names

Available in `ToolNames` enum (`tool_names.py`):
- `IMAGE_GENERATION_TOOL`, `WEB_SEARCH_TOOL`, `RAG_SEARCH_TOOL`
- `PYTHON_CODE_INTERPRETER`
- `CREATE_SHAPE_BOX`, `ADD_SHAPE_TO_BOX`, `REMOVE_SHAPES_FROM_BOX`, `GET_SHAPES_FROM_BOX`
- `INVERT_STRING`, `LIST_FROM_WORD` (MCP tools)

### Response Format Validation

For JSON-schema output tests:
```python
TstCase(
    name="JSON output",
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
)
```

### Python Interpreter Session Tests

```python
@pytest.mark.requires_session  # injects session_fixture
@e2e_test(
    test_case=TstCase(...).add_py_interpreter_session_flow(),
    ...
)
def test_session_reuse(client):
    pass
```

Requires `PY_INTERPRETER_URL` and `PY_INTERPRETER_API_KEY` in `.env`.

### Attachments (File Uploads)

```python
.add_user_message(
    user_message="Analyze this document",
    attachments=[Path("src/tests/integration_tests/test_documents/weo.pdf")],
    ...
)
```

Test documents: `src/tests/integration_tests/test_documents/` (PDFs, images, CSVs).

### Attachment Checks (Response Attachments)

```python
from test_runner.models import AttachmentCheck

.add_user_message(
    ...,
    attachment_checks=[
        AttachmentCheck(title_strict="chart.png", type="image/png"),
        AttachmentCheck(title_soft="analysis", similarity_threshold=0.8),
    ],
)
```

## Cache System

### How It Works

A local `CacheMiddlewareApp` (FastAPI proxy) sits between the QuickApp under test and DIAL Core:
- **Tool/deployment calls** (RAG, image gen, web search) → served from cache
- **Orchestrator/agent model calls** (`AGENT_MODELS` list) → always proxied live to DIAL Core

### Cache Files

```
test_runner/cache/{model}/{test_file}/{test_case_name}/{md5_hash}.response
```

Each `.response` is a JSON snapshot: request fields + full HTTP response.

### Cache Matching

| Field | Match type |
|-------|-----------|
| `system_message`, `model`, `temperature` | Exact (fail on mismatch) |
| User messages, assistant messages | Fuzzy (>= 0.7 cosine similarity) |

Highest-scoring match is returned.

### `AGENT_MODELS` List

In `cache_middleware.py` — models that are **never cached** (always proxied live). When adding a new orchestrator model, add its deployment name here.

### Refreshing the Cache

```bash
REFRESH=TRUE make integration_test MODEL=<model>
```

- Rebuilds cache against live DIAL Core
- Deletes `.response` files not accessed during the run (stale cleanup)
- **Commit** generated `.response` files alongside your test

When to refresh:
- First run (no cache exists)
- After changing system prompts or tool definitions
- After adding new test cases

## Failure Reasons

`FailureReason` enum categories tracked per test:
- `ARGUMENTS` — tool argument mismatch
- `ANSWER` — response content mismatch
- `TOOL_CALL_COUNT` — wrong number of tool calls
- `TOOL_CALL_MISMATCH` — unexpected tool called
- `ATTACHMENT` / `CITATION` — missing expected attachments
- `ROLE` / `HTTP_STATUS` — response structure errors
- `LLM_CACHE_MISSING` — no cached response found

## ResponseValidator Behavior

- `read_skill` tool calls are auto-allowed in all tests (internal tool retrieval)
- Failed `internal_code_execution_python_interpreter` calls (result contains "FAILURE" or "session closed") are filtered out before validation
- `ToolCall(name, min_calls=1, max_calls=1)` — control expected call count range

## Environment Variables

```bash
# Required for live/refresh runs:
REMOTE_DIAL_URL=http://...
REMOTE_DIAL_API_KEY=...

# Optional:
REFRESH=TRUE                    # Rebuild cache
MODEL=gpt-4.1-2025-04-14       # Default model
MOCK_DIAL_CORE_PORT=8081        # Cache middleware port (auto-offset for xdist workers)
PY_INTERPRETER_URL=...          # For interpreter tests
PY_INTERPRETER_API_KEY=...
PY_INTERPRETER_LOCAL_RUN=true
QUICKAPP_LOG_LEVEL=DEBUG        # Extra logging
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "no response found in cache" | Run with `REFRESH=TRUE`, commit new `.response` files |
| Nondeterministic failures | Inspect cached response vs orchestrator output; lower similarity threshold or refresh cache |
| Missing model errors | Add model to `AGENT_MODELS` in `cache_middleware.py` |
| Need to debug without cache | Pass `no_cache=True` to `@e2e_test` or use `--no-cache` CLI flag |
| Tests fail on new DIAL Core instance | Update `AGENT_MODELS` list and refresh cache for available models |
