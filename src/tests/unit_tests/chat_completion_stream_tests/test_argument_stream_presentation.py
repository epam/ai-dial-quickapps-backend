"""Tests for streaming tool-argument presenters."""

from quickapp.common.chat_completion_stream.argument_stream_presentation import (
    ArgumentStreamMode,
    ArgumentStreamPresentation,
    StreamingArgumentPresenter,
)
from quickapp.config.tools.display.paramenter import FormattedParameterConfig


def _collect(presentation: ArgumentStreamPresentation, chunks: list[str]) -> str:
    out: list[str] = []
    presenter = StreamingArgumentPresenter(out.append, presentation)
    for chunk in chunks:
        presenter.feed(chunk)
    presenter.finish()
    return "".join(out)


def test_config_map_ignores_title_and_streams_code_fence():
    presentation = ArgumentStreamPresentation(
        mode=ArgumentStreamMode.CONFIG_MAP,
        parameters_config_map={
            "title": FormattedParameterConfig(ignore=True, show_value_in_stage_title=True),
            "code": FormattedParameterConfig(format="python", name="**Code to execute:**"),
            "attachment_urls": FormattedParameterConfig(
                ignore_parameter_name=True, prefix="**Files:** "
            ),
        },
    )
    text = _collect(
        presentation,
        [
            '{"title": "Draw", "code": "print(1)',
            '\\npass", "attachment_urls": ["files/a.csv"]}',
        ],
    )
    assert "> #### Request:" in text
    assert "Draw" not in text
    assert "**Code to execute:**" in text
    assert "````python\n" in text
    assert "print(1)\npass" in text
    assert "**Files:** " in text
    assert "files/a.csv" in text
    assert '{"title"' not in text


def test_json_object_streams_pretty_request_block():
    presentation = ArgumentStreamPresentation(mode=ArgumentStreamMode.JSON_OBJECT)
    text = _collect(
        presentation,
        ['{"q": "hel', 'lo", "n": 2}'],
    )
    assert text.startswith("> ##### Request:\n```json\n{\n")
    assert '"q": "hello"' in text
    assert '"n": 2' in text
    assert text.endswith("\n}\n```\n\n")
