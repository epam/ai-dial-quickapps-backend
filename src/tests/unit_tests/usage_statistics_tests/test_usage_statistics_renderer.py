# noinspection PyProtectedMember
from quickapp.usage_statistics._aggregated_stats import _AggregatedStats

# noinspection PyProtectedMember
from quickapp.usage_statistics._usage_statistics_renderer import _UsageStatisticsRenderer


def test_table_has_a_row_with_tokens_and_cost_for_every_model():
    table = _UsageStatisticsRenderer.render_usage_statistics_table(
        [
            _AggregatedStats("nested_app_tool", "gpt-image-1", 5, 40, 0.5),
            _AggregatedStats("Orchestrator", "gpt-5", 100, 20, 1.5),
            _AggregatedStats("nested_app_tool", "gpt-5-mini", 7, 8, 0.25),
        ]
    )

    assert table.splitlines()[2:] == [
        "| Orchestrator | gpt-5 | 100 | 20 | 1.5 |",
        "| Tool: nested_app_tool | gpt-image-1 | 5 | 40 | 0.5 |",
        "| Tool: nested_app_tool | gpt-5-mini | 7 | 8 | 0.25 |",
        "| **Total** | - | - | - | **2.25** |",
    ]


def test_total_is_omitted_when_a_cost_is_unknown():
    table = _UsageStatisticsRenderer.render_usage_statistics_table(
        [
            _AggregatedStats("Orchestrator", "gpt-5", 100, 20, 1.5),
            _AggregatedStats("document_tool", "dial-document", 11, 7, "-"),
        ]
    )

    assert "Total" not in table
    assert "| Tool: document_tool | dial-document | 11 | 7 | - |" in table
