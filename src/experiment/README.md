# Experiment: shared chat stream chunk pipeline

This folder is a **sandbox copy** of the orchestrator + deployment stream refactor. It does not change `src/quickapp`. When you are happy with it, move modules into `quickapp.common` (or similar) and wire callers.

## Layout

| Module | Role |
|--------|------|
| `chat_stream_shared/models.py` | Pydantic models: `NormalizedCustomContent`, `NormalizedChoiceDelta`, `ChunkUsageFootprint`; `StreamChunkVisitor` protocol |
| `chat_stream_shared/driver.py` | `consume_chat_completion_chunks` async loop |
| `chat_stream_shared/openai_custom.py` | Attachment dict normalization (mirror of `quickapp.agent._stage_delta_types` helpers) |
| `chat_stream_shared/openai_parse.py` | `parse_openai_chat_completion_chunk` (footprint is `None` unless `chunk.usage` is present — avoids allocating a model on every token chunk) |
| `chat_stream_shared/dial_parse.py` | `parse_dial_chat_completion_chunk` |

## Run tests

From repo root (with project venv active):

```powershell
poetry run pytest experiment/tests -q
```

`experiment/tests/conftest.py` prepends `experiment/` to `sys.path` so `import chat_stream_shared` resolves.

## Integration (after move)

- **ChunkProcessor**: visitor + `parse_openai_chat_completion_chunk`; apply `NormalizedCustomContent` to `AssistantCallResult` and `Choice` (stage propagation stays in the processor).
- **DialCompletionService**: visitor + `parse_dial_chat_completion_chunk`; `_fix_attachment` / `_to_sdk_attachment` stay on the service when forwarding to `BaseStageWrapper`.

Replace `openai_custom.py` with imports from `quickapp.agent._stage_delta_types` once merged to avoid duplication.
