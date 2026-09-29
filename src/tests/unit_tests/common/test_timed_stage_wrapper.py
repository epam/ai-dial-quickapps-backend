import re
from time import perf_counter
from typing import Any
from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Stage
from injector import AssistedBuilder, Binder, Injector, Module, inject

from quickapp.common import TimedStageWrapper, ToolCallResult


@inject
class _StageWrapperUnderTest(TimedStageWrapper):
    """Stands in for the concrete wrappers, which are all `@inject`-decorated too."""

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return ""

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return ""

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        return ""


def _build(stage: MagicMock, **kwargs: Any) -> _StageWrapperUnderTest:
    """Build the wrapper the way production does: through the DI assisted builder."""
    builder = Injector().get(AssistedBuilder[_StageWrapperUnderTest])
    return builder.build(stage=stage, tool_config=None, stage_name="skill", **kwargs)


def _reported_duration(stage: MagicMock) -> float:
    """The seconds the wrapper appended to the stage name, e.g. ' [0.03s]' -> 0.03."""
    appended = stage.append_name.call_args_list[-1].args[0]
    match = re.fullmatch(r" \[(\d+\.\d+)s\]", appended)
    assert match is not None, f"unexpected duration suffix: {appended!r}"
    return float(match.group(1))


def test_duration_is_measured_from_stage_open_when_no_start_time_is_passed():
    """Regression for #582.

    `start_time` is omitted on the non-adopted build path, and injector used to fill the
    unbound `float | None` annotation with `float()` == 0.0. That made `__exit__` report
    `perf_counter() - 0` -- the host's uptime, thousands of seconds -- as the duration.
    """
    stage = MagicMock()

    with _build(stage):
        pass

    assert _reported_duration(stage) < 1.0


def test_adopted_start_time_is_honoured():
    """A stage opened while tool-call arguments streamed carries its own start time."""
    stage = MagicMock()

    with _build(stage, already_open=True, start_time=perf_counter() - 5.0):
        pass

    assert 5.0 <= _reported_duration(stage) < 6.0


def test_stage_is_still_resolved_from_di_when_the_caller_omits_it():
    """Omitting `stage` is how a caller asks for a fresh stage off the request `Choice`.

    Guards against over-applying `@noninjectable`: `stage` is a real dependency, unlike
    the per-call arguments beside it.
    """
    injected_stage = MagicMock()

    class _StageModule(Module):
        def configure(self, binder: Binder) -> None:
            binder.bind(Stage, to=injected_stage)

    builder = Injector([_StageModule()]).get(AssistedBuilder[_StageWrapperUnderTest])
    wrapper = builder.build(tool_config=None, stage_name="skill")

    with wrapper:
        pass

    assert _reported_duration(injected_stage) < 1.0
