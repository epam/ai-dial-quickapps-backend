from unittest.mock import MagicMock

from quickapp.dial_deployment_tooling.deployment_stage_wrapper import DeploymentStageWrapper


def _make_wrapper() -> DeploymentStageWrapper:
    return DeploymentStageWrapper(stage=MagicMock(), tool_config=None, stage_name="deployment")


def test_static_tools_are_not_rendered_in_the_stage():
    """Tools come from the app config, not the model, and their JSON would flood the stage."""
    wrapper = _make_wrapper()

    rendered = wrapper._get_formatted_parameters(
        {
            "query": "who won?",
            "tools": [{"type": "static_function", "static_function": {"name": "web_search"}}],
        }
    )

    assert "who won?" in rendered
    assert "web_search" not in rendered


def test_reasoning_effort_stays_visible():
    wrapper = _make_wrapper()

    rendered = wrapper._get_formatted_parameters({"query": "think", "reasoning_effort": "high"})

    assert "high" in rendered
