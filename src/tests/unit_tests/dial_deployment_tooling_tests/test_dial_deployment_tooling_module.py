from unittest.mock import MagicMock

import pytest

from quickapp.config.tools.deployment_simple import DialDeploymentSimpleTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_deployment_tooling.dial_deployment_tooling_module import (
    DialDeploymentToolingModule,
)


def _app_config_with_simple_tool(propagate_annotations_to_choice):
    tool = DialDeploymentSimpleTool(
        deployment_id="dial-document",
        propagate_annotations_to_choice=propagate_annotations_to_choice,
    )
    return MagicMock(tool_sets=[DeploymentToolSet(name="docs", tools=[tool])])


def test_prompt_parts_registered_when_a_tool_propagates_annotations():
    module = DialDeploymentToolingModule()
    provider = MagicMock()

    parts = module._provide_prompt_parts(_app_config_with_simple_tool(True), provider)

    assert parts == [provider]


@pytest.mark.parametrize("flag", [None, False])
def test_prompt_parts_absent_when_no_tool_propagates_annotations(flag):
    module = DialDeploymentToolingModule()

    parts = module._provide_prompt_parts(_app_config_with_simple_tool(flag), MagicMock())

    assert parts == []


def test_prompt_parts_absent_when_toolset_disabled():
    module = DialDeploymentToolingModule()
    app_config = _app_config_with_simple_tool(True)
    app_config.tool_sets[0].enabled = False

    assert module._provide_prompt_parts(app_config, MagicMock()) == []


def test_prompt_parts_absent_when_tool_disabled():
    module = DialDeploymentToolingModule()
    app_config = _app_config_with_simple_tool(True)
    app_config.tool_sets[0].tools[0].enabled = False

    assert module._provide_prompt_parts(app_config, MagicMock()) == []
