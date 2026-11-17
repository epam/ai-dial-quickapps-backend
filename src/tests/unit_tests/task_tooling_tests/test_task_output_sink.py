"""Tests for rendering a task's output into the delegating agent's tool stage.

Driven through the real ``Choice``/``Stage`` API rather than by constructing chunks by
hand: the sink's whole premise is that those two classes emit nothing but queue chunks,
so the test is only meaningful if the SDK produces the chunks, not the test.
"""

from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Choice, Status

from quickapp.task_tooling._task_output_sink import TaskOutputSink
from quickapp.task_tooling._task_stage_wrapper import _TaskStageWrapper


def _wrapper() -> tuple[_TaskStageWrapper, MagicMock]:
    stage = MagicMock()
    return _TaskStageWrapper(stage=stage), stage


def _rendered(stage: MagicMock) -> str:
    return "".join(call.args[0] for call in stage.append_content.call_args_list)


def _task(wrapper) -> tuple[Choice, TaskOutputSink]:
    sink = TaskOutputSink(wrapper)
    choice = Choice(sink, 0)
    choice.open()
    return choice, sink


def test_task_content_streams_into_the_parent_stage():
    wrapper, stage = _wrapper()
    choice, _ = _task(wrapper)

    choice.append_content("Looking into it")
    choice.append_content(" now.")

    assert _rendered(stage) == "Looking into it now."


def test_task_stage_is_rendered_when_it_closes():
    wrapper, stage = _wrapper()
    choice, _ = _task(wrapper)

    with choice.create_stage("Calling ") as task_stage:
        task_stage.append_name("web_search")
        task_stage.append_content("3 results")

    rendered = _rendered(stage)
    assert "**Calling web_search**" in rendered
    assert "> 3 results" in rendered


def test_concurrent_task_stages_do_not_interleave():
    """A task gathers its tool calls, so several of its stages are open at once."""
    wrapper, stage = _wrapper()
    choice, _ = _task(wrapper)

    first = choice.create_stage("first")
    second = choice.create_stage("second")
    first.open()
    second.open()
    first.append_content("AAA")
    second.append_content("BBB")
    second.close(Status.COMPLETED)
    first.close(Status.COMPLETED)

    rendered = _rendered(stage)
    # `second` finished first, so it is rendered first — and each stage's body stays
    # contiguous rather than being spliced into the other's.
    assert rendered.index("**second**") < rendered.index("**first**")
    assert "> BBB" in rendered and "> AAA" in rendered


def test_failed_task_stage_is_marked():
    wrapper, stage = _wrapper()
    choice, _ = _task(wrapper)

    task_stage = choice.create_stage("flaky")
    task_stage.open()
    task_stage.close(Status.FAILED)

    assert "✗" in _rendered(stage)


def test_choice_attachments_are_collected_for_the_tool_result():
    """A task's chart must reach the delegating agent."""
    wrapper, _ = _wrapper()
    choice, sink = _task(wrapper)

    choice.add_attachment(type="image/png", title="chart", url="files/x/chart.png")

    assert len(sink.attachments) == 1
    assert sink.attachments[0].url == "files/x/chart.png"
    assert sink.attachments[0].type == "image/png"


def test_stage_attachments_go_to_the_parent_stage():
    wrapper, stage = _wrapper()
    choice, sink = _task(wrapper)

    with choice.create_stage("plotting") as task_stage:
        task_stage.add_attachment(type="image/png", title="fig", url="files/x/fig.png")

    stage.add_attachment.assert_called_once()
    # A stage attachment is UI for the task's step, not a result the delegating agent
    # returns, so it must not also land on the tool result.
    assert sink.attachments == []


def test_task_state_is_dropped():
    """Tasks are stateless by design; their state must not reach the delegating agent."""
    wrapper, stage = _wrapper()
    choice, sink = _task(wrapper)

    choice.set_state({"tool_execution_history": ["lots", "of", "noise"]})

    assert _rendered(stage) == ""
    assert sink.attachments == []


def test_rendering_failure_never_breaks_the_task():
    """The answer is read off the task's messages, so a UI failure must not propagate."""
    wrapper, stage = _wrapper()
    stage.append_content.side_effect = RuntimeError("stage already closed")
    choice, _ = _task(wrapper)

    choice.append_content("still fine")


def test_suppressed_stage_still_collects_attachments():
    """With stage display off there is no wrapper, but results must still come back."""
    sink = TaskOutputSink(None)
    choice = Choice(sink, 0)
    choice.open()

    choice.append_content("invisible")
    choice.add_attachment(type="image/png", url="files/x/chart.png")

    assert len(sink.attachments) == 1
