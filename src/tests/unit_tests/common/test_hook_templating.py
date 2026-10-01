from typing import Any

import pytest

from quickapp.common.hook_context.context import (
    CompletionHookContext,
    HookMessage,
    HookToolCall,
    RequestStartHookContext,
)
from quickapp.common.hook_context.templating import (
    TemplateError,
    TemplateResolutionError,
    contains_placeholder,
    render_arguments,
    validate_template_paths,
)


def _completion_context() -> CompletionHookContext:
    return CompletionHookContext(
        event="on_completion",
        messages=[
            HookMessage(role="user", content="first question"),
            HookMessage(
                role="assistant",
                content="",
                tool_calls=[HookToolCall(id="c1", name="read", arguments={"file_path": "/a.txt"})],
            ),
            HookMessage(role="tool", content="file body", tool_call_id="c1"),
            HookMessage(role="assistant", content="the answer"),
        ],
        iteration_count=2,
        total_tool_calls=1,
    )


class TestContainsPlaceholder:
    def test_plain_string(self) -> None:
        assert contains_placeholder("hello") is False

    def test_placeholder_in_string(self) -> None:
        assert contains_placeholder("x ${last_user_message.content} y") is True

    def test_nested_dict_and_list(self) -> None:
        assert contains_placeholder({"a": [{"b": "${iteration_count}"}]}) is True

    def test_escaped_is_not_a_placeholder(self) -> None:
        assert contains_placeholder("\\${nope}") is False

    def test_non_strings_and_keys_are_ignored(self) -> None:
        assert contains_placeholder({"${k}": 1, "n": 3, "b": True, "z": None}) is False

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(TemplateError):
            contains_placeholder("${messages[}")


class TestValidateTemplatePaths:
    @pytest.mark.parametrize(
        "template",
        [
            "${last_user_message.content}",
            "${last_assistant_message.content}",
            "${messages[-2].content}",
            "${messages[0].tool_calls[0].arguments.file_path}",
            "${messages}",
            "${event}",
            "prefix ${last_user_message.content} suffix",
        ],
    )
    def test_valid_paths_on_request_start(self, template: str) -> None:
        validate_template_paths({"q": template}, RequestStartHookContext)

    def test_completion_only_fields_valid_on_completion(self) -> None:
        validate_template_paths(
            {"a": "${iteration_count}", "b": "${total_tool_calls}"}, CompletionHookContext
        )

    def test_nested_dict_and_list_arguments_are_walked(self) -> None:
        validate_template_paths(
            {"a": {"b": ["${last_user_message.content}", "ok"]}}, RequestStartHookContext
        )

    def test_unknown_root_rejected(self) -> None:
        with pytest.raises(TemplateError, match=r"unknown field 'tool_input' on CompletionHook"):
            validate_template_paths({"q": "${tool_input}"}, CompletionHookContext)

    def test_typo_rejected_and_message_names_placeholder(self) -> None:
        with pytest.raises(TemplateError, match=r"\$\{last_user_message\.contnet\}.*'contnet'"):
            validate_template_paths({"q": "${last_user_message.contnet}"}, RequestStartHookContext)

    def test_index_on_non_list_rejected(self) -> None:
        with pytest.raises(TemplateError, match="non-list"):
            validate_template_paths({"q": "${iteration_count[0]}"}, CompletionHookContext)

    def test_completion_field_rejected_on_request_start(self) -> None:
        with pytest.raises(TemplateError, match="unknown field 'iteration_count'"):
            validate_template_paths({"q": "${iteration_count}"}, RequestStartHookContext)

    @pytest.mark.parametrize(
        "template",
        ["${}", "${1abc}", "${messages[}", "${abc", "${a | b}", "${a:b}", "${a..b}", "${a[x]}"],
    )
    def test_syntax_errors_rejected(self, template: str) -> None:
        with pytest.raises(TemplateError):
            validate_template_paths({"q": template}, RequestStartHookContext)

    def test_escaped_placeholder_not_validated(self) -> None:
        validate_template_paths({"q": "\\${nope}"}, RequestStartHookContext)

    def test_keys_are_not_templated(self) -> None:
        validate_template_paths({"${nope}": "literal"}, RequestStartHookContext)

    def test_walk_stops_at_free_form_dict(self) -> None:
        validate_template_paths(
            {"q": "${messages[0].tool_calls[0].arguments.anything.goes.here}"},
            RequestStartHookContext,
        )

    def test_optional_fields_are_traversed(self) -> None:
        validate_template_paths({"q": "${last_user_message.tool_calls}"}, RequestStartHookContext)


class TestRenderArguments:
    def test_no_placeholders_returns_equal_copy(self) -> None:
        args: dict[str, Any] = {"a": 1, "b": ["x", {"c": "y"}]}
        rendered = render_arguments(args, _completion_context())
        assert rendered == args
        assert rendered is not args
        assert rendered["b"] is not args["b"]

    def test_whole_string_placeholder_keeps_raw_type(self) -> None:
        rendered = render_arguments(
            {"n": "${iteration_count}", "m": "${messages}"}, _completion_context()
        )
        assert rendered["n"] == 2
        assert isinstance(rendered["m"], list)
        assert rendered["m"][0]["content"] == "first question"

    def test_embedded_string_placeholder_is_inserted_as_is(self) -> None:
        rendered = render_arguments(
            {"q": "Q: ${last_user_message.content}!"}, _completion_context()
        )
        assert rendered["q"] == "Q: first question!"

    def test_embedded_non_string_is_compact_json(self) -> None:
        rendered = render_arguments(
            {"q": "calls=${messages[1].tool_calls[0].arguments} n=${iteration_count}"},
            _completion_context(),
        )
        assert rendered["q"] == 'calls={"file_path":"/a.txt"} n=2'

    def test_non_ascii_is_not_escaped(self) -> None:
        ctx = CompletionHookContext(
            event="on_completion",
            messages=[HookMessage(role="user", content="привет")],
            iteration_count=1,
            total_tool_calls=0,
        )
        rendered = render_arguments({"q": "x ${messages[0]}"}, ctx)
        assert '"content":"привет"' in rendered["q"]

    def test_recurses_into_dicts_and_lists(self) -> None:
        rendered = render_arguments(
            {"a": {"b": ["${last_assistant_message.content}", 7]}}, _completion_context()
        )
        assert rendered == {"a": {"b": ["the answer", 7]}}

    def test_escape_renders_literal_dollar_brace(self) -> None:
        rendered = render_arguments(
            {"q": "\\${literal} and ${last_user_message.content}"}, _completion_context()
        )
        assert rendered["q"] == "${literal} and first question"

    def test_negative_index(self) -> None:
        rendered = render_arguments({"q": "${messages[-2].content}"}, _completion_context())
        assert rendered["q"] == "file body"

    def test_keys_are_not_templated(self) -> None:
        rendered = render_arguments(
            {"${iteration_count}": "${iteration_count}"}, _completion_context()
        )
        assert rendered == {"${iteration_count}": 2}

    def test_none_on_path_raises_resolution_error(self) -> None:
        ctx = RequestStartHookContext(
            event="on_request_start", messages=[HookMessage(role="user", content="q")]
        )
        with pytest.raises(TemplateResolutionError, match="last_assistant_message"):
            render_arguments({"q": "${last_assistant_message.content}"}, ctx)

    def test_terminal_none_raises_resolution_error(self) -> None:
        with pytest.raises(TemplateResolutionError, match="tool_call_id"):
            render_arguments({"q": "${last_assistant_message.tool_call_id}"}, _completion_context())

    def test_index_out_of_range_raises_resolution_error(self) -> None:
        with pytest.raises(TemplateResolutionError, match=r"index \[9\]"):
            render_arguments({"q": "${messages[9].content}"}, _completion_context())

    def test_missing_free_form_key_raises_resolution_error(self) -> None:
        with pytest.raises(TemplateResolutionError, match="nope"):
            render_arguments(
                {"q": "${messages[1].tool_calls[0].arguments.nope}"}, _completion_context()
            )

    def test_error_text_never_contains_context_values(self) -> None:
        ctx = CompletionHookContext(
            event="on_completion",
            messages=[HookMessage(role="user", content="SECRET-TOKEN-123")],
            iteration_count=1,
            total_tool_calls=0,
        )
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_arguments({"q": "${messages[0].content.missing}"}, ctx)
        assert "SECRET-TOKEN-123" not in str(exc_info.value)
