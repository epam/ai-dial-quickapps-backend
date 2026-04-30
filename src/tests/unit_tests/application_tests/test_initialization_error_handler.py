from types import SimpleNamespace
from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Stage, Status

from quickapp.application._initialization_error_handler import _InitializationErrorHandler
from quickapp.common.exceptions import ConfigResolutionException


def _make_handler(stage: MagicMock, exceptions: list) -> _InitializationErrorHandler:
    return _InitializationErrorHandler(
        stage_provider=SimpleNamespace(get=lambda: stage),
        initialization_exceptions_provider=SimpleNamespace(get=lambda: exceptions),
    )


def _stage_content(stage: MagicMock) -> str:
    return "\n\n".join(call.args[0] for call in stage.append_content.call_args_list)


class TestConfigResolutionExceptionRendering:
    def test_renders_initialization_issues_stage_with_template_and_details(self):
        stage = MagicMock(spec=Stage)
        exc = ConfigResolutionException(
            message="value is not a string",
            template_name="dial_rag",
            json_path="/deployment/name",
            details="/deployment/name: must be string",
        )
        handler = _make_handler(stage, [exc])

        handler.handle_initialization_issues()

        stage.open.assert_called_once()
        stage.append_name.assert_called_once_with("Initialization issues")
        rendered = _stage_content(stage)
        assert "template 'dial_rag'" in rendered
        assert "value is not a string" in rendered
        assert "/deployment/name: must be string" in rendered
        stage.close.assert_called_once_with(Status.FAILED)

    def test_no_exceptions_does_not_render_stage(self):
        stage = MagicMock(spec=Stage)
        handler = _make_handler(stage, [])

        handler.handle_initialization_issues()

        stage.open.assert_not_called()
        stage.append_name.assert_not_called()

    def test_provider_failure_is_swallowed(self):
        stage = MagicMock(spec=Stage)
        provider = MagicMock()
        provider.get.side_effect = RuntimeError("provider exploded")

        handler = _InitializationErrorHandler(
            stage_provider=SimpleNamespace(get=lambda: stage),
            initialization_exceptions_provider=provider,
        )
        handler.handle_initialization_issues()
        stage.open.assert_not_called()
