from quickapp.tool_discovery._toolset_summary_format import format_toolset_summaries


def test_formats_summary_with_description():
    result = format_toolset_summaries(
        [{"name": "salesforce", "description": "Query Salesforce records", "tool_count": 12}]
    )

    assert result == "- salesforce. Available tools: 12. Query Salesforce records"


def test_formats_summary_without_description():
    result = format_toolset_summaries(
        [{"name": "internal-utils", "description": None, "tool_count": 1}]
    )

    assert result == "- internal-utils. Available tools: 1."


def test_formats_multiple_summaries_in_order():
    result = format_toolset_summaries(
        [
            {"name": "toolset_a", "description": "Does A", "tool_count": 3},
            {"name": "toolset_b", "description": None, "tool_count": 7},
        ]
    )

    assert result == "- toolset_a. Available tools: 3. Does A\n- toolset_b. Available tools: 7."


def test_formats_empty_list():
    assert format_toolset_summaries([]) == ""
