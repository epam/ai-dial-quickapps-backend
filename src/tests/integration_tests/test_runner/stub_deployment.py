import json
from dataclasses import dataclass
from typing import Any

from fastapi import Response

STUB_DEPLOYMENT_ID = "usage-stub-tool"
STUB_TOOL_NAME = "usage_stub_tool"
STUB_ANSWER = "The stub tool says PONG-7391."
STUB_PROMPT_TOKENS = 11
STUB_COMPLETION_TOKENS = 7

NESTED_STUB_DEPLOYMENT_ID = "usage-stub-nested"
NESTED_STUB_TOOL_NAME = "usage_stub_nested_tool"
NESTED_STUB_ANSWER = "The nested stub says PONG-5528."


@dataclass(frozen=True)
class StubModelUsage:
    model: str
    prompt_tokens: int
    completion_tokens: int


# What a nested QuickApp would report: the models it and its own tools used.
NESTED_STUB_MODELS = (
    StubModelUsage("stub-inner-model-a", 100, 20),
    StubModelUsage("stub-inner-model-b", 5, 40),
)

STUB_DEPLOYMENT_IDS = (STUB_DEPLOYMENT_ID, NESTED_STUB_DEPLOYMENT_ID)


def _chunk(include_usage: bool, **fields: Any) -> dict[str, Any]:
    chunk: dict[str, Any] = {
        "id": "chatcmpl-usage-stub",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": STUB_DEPLOYMENT_ID,
        **fields,
    }
    if include_usage:
        chunk.setdefault("usage", None)
    return chunk


def _usage_chunks(deployment_id: str) -> list[dict[str, Any]]:
    if deployment_id == NESTED_STUB_DEPLOYMENT_ID:
        total_prompt = sum(m.prompt_tokens for m in NESTED_STUB_MODELS)
        total_completion = sum(m.completion_tokens for m in NESTED_STUB_MODELS)
        # The total is reported too, as a real QuickApp-compatible app may: it must not be counted twice.
        chunks = [
            _chunk(
                True,
                choices=[],
                usage={
                    "prompt_tokens": total_prompt,
                    "completion_tokens": total_completion,
                    "total_tokens": total_prompt + total_completion,
                },
            )
        ]
        chunks.extend(
            _chunk(
                True,
                choices=[],
                statistics={
                    "usage_per_model": [
                        {
                            "index": index,
                            "model": m.model,
                            "prompt_tokens": m.prompt_tokens,
                            "completion_tokens": m.completion_tokens,
                        }
                    ]
                },
            )
            for index, m in enumerate(NESTED_STUB_MODELS)
        )
        return chunks
    return [
        _chunk(
            True,
            choices=[],
            usage={
                "prompt_tokens": STUB_PROMPT_TOKENS,
                "completion_tokens": STUB_COMPLETION_TOKENS,
                "total_tokens": STUB_PROMPT_TOKENS + STUB_COMPLETION_TOKENS,
            },
        )
    ]


def build_stub_response(deployment_id: str, request_body: dict[str, Any]) -> Response:
    """Streams a fixed answer like an OpenAI-compatible deployment: usage only on `stream_options.include_usage`."""
    include_usage = bool((request_body.get("stream_options") or {}).get("include_usage"))
    answer = NESTED_STUB_ANSWER if deployment_id == NESTED_STUB_DEPLOYMENT_ID else STUB_ANSWER

    chunks = [
        _chunk(
            include_usage,
            choices=[
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": answer},
                    "finish_reason": None,
                }
            ],
        ),
        _chunk(include_usage, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]),
    ]
    if include_usage:
        chunks.extend(_usage_chunks(deployment_id))

    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return Response(content=body, media_type="text/event-stream")
