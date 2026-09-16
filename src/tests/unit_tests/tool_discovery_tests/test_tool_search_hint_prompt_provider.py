import pytest

from quickapp.tool_discovery._tool_search_hint_prompt_provider import _ToolSearchHintPromptProvider


def _make_provider(
    toolset_summaries: list[dict[str, str | int | None]],
) -> _ToolSearchHintPromptProvider:
    return _ToolSearchHintPromptProvider(toolset_summaries)


@pytest.mark.asyncio
async def test_get_prompt_part_mentions_internal_tool_search():
    provider = _make_provider([])

    part = await provider.get_prompt_part()

    assert "internal_tool_search" in part


@pytest.mark.asyncio
async def test_get_prompt_part_omits_toolset_list_when_nothing_deferred():
    provider = _make_provider([])

    part = await provider.get_prompt_part()

    assert "Additional toolsets available for discovery" not in part


@pytest.mark.asyncio
async def test_get_prompt_part_appends_deferred_toolset_summaries():
    provider = _make_provider(
        [
            {"name": "salesforce", "description": "Query Salesforce records", "tool_count": 12},
            {"name": "internal-utils", "description": None, "tool_count": 1},
        ]
    )

    part = await provider.get_prompt_part()

    assert "Additional toolsets available for discovery:" in part
    assert "- salesforce. Available tools: 12. Query Salesforce records" in part
    assert "- internal-utils. Available tools: 1." in part
