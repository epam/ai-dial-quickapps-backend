"""Tests for CompletionRunner — the lifecycle shared by the HTTP handler and subagent spawns."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from pydantic import SecretStr

import quickapp.core.application._completion_runner as completion_runner
from quickapp.common import StagedBaseTool
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent import Orchestrator
from quickapp.core.application import CompletionInputs, CompletionRunner
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import create_app_configuration


def _inputs() -> CompletionInputs:
    return CompletionInputs(
        api_key=SecretStr("key"),
        application_config=create_app_configuration([]),
        messages=[Message(role=Role.USER, content="hi")],
    )


class _Harness:
    """Records the order in which the runner drives its collaborators."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        self.context_setup = MagicMock()
        self.context_setup.setup_context = AsyncMock(
            side_effect=lambda _: self.calls.append("setup_context")
        )
        self.context_setup.setup_messages = AsyncMock(
            side_effect=lambda _: self.calls.append("setup_messages")
        )
        self.error_handler = MagicMock()
        self.error_handler.handle_initialization_issues = MagicMock(
            side_effect=lambda: self.calls.append("initialization_issues")
        )
        self.orchestrator = MagicMock()
        self.orchestrator.invoke = AsyncMock(side_effect=lambda: self.calls.append("orchestrator"))
        skills = MagicMock(spec=AgentSkillsProvider)
        skills.get_all_skills.return_value = []
        bindings = {
            Orchestrator: self.orchestrator,
            ApplicationConfig: create_app_configuration([]),
            list[StagedBaseTool]: [],
            AgentSkillsProvider: skills,
        }
        self.injector = MagicMock()
        self.injector.get = MagicMock(side_effect=lambda key: bindings[key])
        self.timer = PerformanceTimer()

        async def _initializers(injector, itype):
            self.calls.append("initializers")

        monkeypatch.setattr(completion_runner, "invoke_initializers", _initializers)
        self.runner = CompletionRunner(
            injector=self.injector,
            context_setup=self.context_setup,
            error_handler=self.error_handler,
            perf_timer=self.timer,
        )


@pytest.mark.asyncio
async def test_run_drives_the_lifecycle_in_order(monkeypatch):
    harness = _Harness(monkeypatch)

    orchestrator = await harness.runner.run(_inputs())

    assert orchestrator is harness.orchestrator
    assert harness.calls == [
        "setup_context",
        "initializers",
        "setup_messages",
        "initialization_issues",
        "orchestrator",
    ]
    period = harness.timer.get_data()[completion_runner.TIMER_PERIOD]
    assert period["end_time"] is not None


@pytest.mark.asyncio
async def test_run_stops_at_unresolvable_config(monkeypatch):
    harness = _Harness(monkeypatch)
    harness.context_setup.setup_context = AsyncMock(
        side_effect=ConfigResolutionException(message="bad", template_name="t", json_path="/")
    )

    orchestrator = await harness.runner.run(_inputs())

    assert orchestrator is None
    # The issue is rendered; nothing downstream runs.
    assert harness.calls == ["initialization_issues"]
    assert harness.timer.get_data()[completion_runner.TIMER_PERIOD]["end_time"] is not None


@pytest.mark.asyncio
async def test_run_closes_the_timer_period_when_the_orchestrator_fails(monkeypatch):
    harness = _Harness(monkeypatch)
    harness.orchestrator.invoke = AsyncMock(side_effect=ValueError("boom"))

    with pytest.raises(ValueError):
        await harness.runner.run(_inputs())

    assert harness.timer.get_data()[completion_runner.TIMER_PERIOD]["end_time"] is not None
