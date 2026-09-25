"""Propagation of sub-app stages as children of the calling tool stage."""

from aidial_sdk.chat_completion import Attachment, Stage
from aidial_sdk.chat_completion.chunks import FinishStageChunk, StartStageChunk

from quickapp.common.chat_completion_stream.choice_ui_stream_sink import ChoiceUiSink
from quickapp.common.chat_completion_stream.models import (
    NormalizedChoiceDelta,
    NormalizedCustomContent,
)
from quickapp.common.chat_completion_stream.stream_result import ChatStreamAccumulator
from tests.unit_tests.stream_test_doubles import SpyChoice


def _make_sink(choice: SpyChoice, parent_stage: Stage | None) -> ChoiceUiSink:
    return ChoiceUiSink(
        ChatStreamAccumulator(),
        destination=choice,
        propagate_stages=True,
        stream_content=False,
        parent_stage=parent_stage,
    )


def _delta_with_stages(stage_items: list[dict]) -> NormalizedChoiceDelta:
    return NormalizedChoiceDelta(
        content=None,
        custom=NormalizedCustomContent(
            attachments=[],
            stage_entries=list(enumerate(stage_items)),
            state=None,
        ),
    )


def _start_stages(chunks: list) -> list[dict]:
    return [
        chunk.to_dict()["choices"][0]["delta"]["custom_content"]["stages"][0]
        for chunk in chunks
        if isinstance(chunk, StartStageChunk)
    ]


def _open_stage(choice: SpyChoice, stage: Stage) -> int:
    stage.open()
    chunks = choice.drain_queue()
    return next(
        chunk.stage_index
        for chunk in chunks
        if isinstance(chunk, StartStageChunk)
    )


def test_sub_app_stages_are_nested_under_the_calling_stage():
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")
    calling_index = _open_stage(choice, calling)

    sink = _make_sink(choice, calling)
    sink.on_delta(_delta_with_stages([{"index": 0, "name": "Fetching forecast"}]))

    stages = _start_stages(choice.drain_queue())
    assert len(stages) == 1
    assert stages[0]["name"] == "Fetching forecast"
    assert stages[0]["parent_stage_index"] == calling_index


def test_nested_sub_app_stages_are_remapped_to_their_propagated_parent():
    """A sub-app index space is remapped onto the stages created in the caller."""
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")
    calling_index = _open_stage(choice, calling)

    sink = _make_sink(choice, calling)
    sink.on_delta(
        _delta_with_stages(
            [
                {"index": 0, "name": "Calling Geocoder"},
                {"index": 1, "name": "Resolving city", "parent_stage_index": 0},
            ]
        )
    )

    stages = _start_stages(choice.drain_queue())
    assert [stage["name"] for stage in stages] == ["Calling Geocoder", "Resolving city"]
    assert stages[0]["parent_stage_index"] == calling_index
    assert stages[1]["parent_stage_index"] == stages[0]["index"]


def test_unknown_parent_stage_index_falls_back_to_the_calling_stage():
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")
    calling_index = _open_stage(choice, calling)

    sink = _make_sink(choice, calling)
    sink.on_delta(_delta_with_stages([{"index": 1, "name": "Orphan", "parent_stage_index": 42}]))

    stages = _start_stages(choice.drain_queue())
    assert stages[0]["parent_stage_index"] == calling_index


def test_sub_stages_are_emitted_before_the_calling_stage_closes():
    """Guards the invariant the SDK relies on: children never outlive their parent.

    Sub-app chunks are consumed inside the ``with`` block that owns the calling
    stage. If that consumption ever escapes the block, opening a child of an
    already closed stage becomes a runtime error instead of a nesting glitch.
    """
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")

    with calling:
        sink = _make_sink(choice, calling)
        sink.on_delta(_delta_with_stages([{"index": 0, "name": "Fetching forecast"}]))
        sink.on_stream_success()

    chunks = choice.drain_queue()
    calling_index = next(
        chunk.stage_index
        for chunk in chunks
        if isinstance(chunk, StartStageChunk)
        and chunk.parent_stage_index is None
    )
    child_starts = [
        position
        for position, chunk in enumerate(chunks)
        if isinstance(chunk, StartStageChunk) and chunk.parent_stage_index is not None
    ]
    calling_finish = next(
        position
        for position, chunk in enumerate(chunks)
        if isinstance(chunk, FinishStageChunk) and chunk.stage_index == calling_index
    )

    assert child_starts
    assert max(child_starts) < calling_finish


def test_sub_stage_is_dropped_when_the_calling_stage_is_already_closed():
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")
    calling.open()
    calling.close()
    choice.drain_queue()

    sink = _make_sink(choice, calling)
    sink.on_delta(_delta_with_stages([{"index": 0, "name": "Late stage"}]))

    assert _start_stages(choice.drain_queue()) == []


def test_attachments_are_not_promoted_to_the_choice_while_nesting():
    choice = SpyChoice()
    calling = choice.create_stage("Calling WeatherApp")
    calling.open()
    choice.drain_queue()

    sink = _make_sink(choice, calling)
    sink.on_delta(
        NormalizedChoiceDelta(
            content=None,
            custom=NormalizedCustomContent(
                attachments=[
                    Attachment(type="image/png", url="files/bucket/plot.png", title="plot")
                ],
                stage_entries=[],
                state=None,
            ),
        )
    )

    assert choice.add_attachment_kwargs == []
