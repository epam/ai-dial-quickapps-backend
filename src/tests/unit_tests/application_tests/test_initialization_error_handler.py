from types import SimpleNamespace
from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Stage, Status

from quickapp.common.exceptions import (
    ConfigResolutionException,
    HookInitializationException,
    OffloadConfigurationException,
    SkillInitializationException,
)
from quickapp.core.application import _InitializationErrorHandler


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

    def test_details_with_embedded_fence_uses_longer_wrapping_fence(self):
        stage = MagicMock(spec=Stage)
        details = "trace:\n```\nboom\n```"
        exc = ConfigResolutionException(
            message="value is not a string",
            template_name="dial_rag",
            json_path="/deployment/name",
            details=details,
        )
        handler = _make_handler(stage, [exc])

        handler.handle_initialization_issues()

        rendered = _stage_content(stage)
        assert f"````\n{details}\n````" in rendered

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


class TestHookInitializationExceptionRendering:
    def test_hook_error_renders_under_hook_section(self):
        stage = MagicMock(spec=Stage)
        exc = HookInitializationException(
            message="tool 'my_tool' not found in initialized tools",
            toolset_name="hook 'my_toolset'",
        )
        handler = _make_handler(stage, [exc])

        handler.handle_initialization_issues()

        stage.open.assert_called_once()
        stage.append_name.assert_called_once_with("Initialization issues")
        rendered = _stage_content(stage)
        assert "Hook initialization" in rendered
        assert "my_toolset" in rendered
        assert "my_tool" in rendered
        assert "Tool initialization" not in rendered
        stage.close.assert_called_once_with(Status.COMPLETED)


class TestSkillInitializationWarningRendering:
    def test_warning_renders_under_warnings_subheader_and_keeps_completed(self):
        stage = MagicMock(spec=Stage)
        warning = SkillInitializationException(
            reason="exceeds 64 characters",
            url="prompts/bucket/long-name",
            severity="warning",
        )
        handler = _make_handler(stage, [warning])

        handler.handle_initialization_issues()

        rendered = _stage_content(stage)
        assert "Warnings:" in rendered
        assert "prompts/bucket/long-name" in rendered
        assert "exceeds 64 characters" in rendered
        assert "Errors:" not in rendered
        stage.close.assert_called_once_with(Status.COMPLETED)

    def test_error_and_warning_render_in_separate_subheaders(self):
        stage = MagicMock(spec=Stage)
        error = SkillInitializationException(reason="boom", url="prompts/bucket/broken")
        warning = SkillInitializationException(
            reason="bad format", url="prompts/bucket/iffy", severity="warning"
        )
        handler = _make_handler(stage, [error, warning])

        handler.handle_initialization_issues()

        rendered = _stage_content(stage)
        assert "Errors:" in rendered
        assert "Warnings:" in rendered
        assert rendered.index("Errors:") < rendered.index("Warnings:")
        assert "prompts/bucket/broken" in rendered
        assert "prompts/bucket/iffy" in rendered
        # Both entries have is_hard=False — status stays COMPLETED.
        stage.close.assert_called_once_with(Status.COMPLETED)


class TestOffloadConfigurationRendering:
    def test_renders_offload_section_as_completed_warning(self):
        stage = MagicMock(spec=Stage)
        exc = OffloadConfigurationException(missing_tools=["read_lines", "search"])
        handler = _make_handler(stage, [exc])

        handler.handle_initialization_issues()

        rendered = _stage_content(stage)
        assert "Large tool-response offload" in rendered
        assert "read_lines/search" in rendered
        # is_hard=False — a lone offload issue keeps the stage COMPLETED.
        stage.close.assert_called_once_with(Status.COMPLETED)
