from unittest.mock import MagicMock

import httpx

# noinspection PyProtectedMember
from quickapp.rest_api_tooling._rest_api_stage_wrapper import _RestApiStageWrapper


def test_error_reference_starts_after_the_response_fence_closes():
    stage = MagicMock()
    wrapper = _RestApiStageWrapper(stage=stage, tool_config=None, stage_name="rest")
    request = httpx.Request("GET", "http://api.example.com/items")
    response = httpx.Response(503, request=request, text="upstream down")
    error = httpx.HTTPStatusError("503", request=request, response=response)

    wrapper.add_exception(error, "ab12cd34")

    rendered = stage.append_content.call_args.args[0]
    assert rendered.endswith("upstream down\n```\n> ##### Error reference:\nab12cd34\n")
