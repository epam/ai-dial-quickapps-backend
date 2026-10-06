import re
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


def _first_turn_context() -> RequestStartHookContext:
    return RequestStartHookContext(
        event="on_request_start", messages=[HookMessage(role="user", content="q")]
    )


class TestContainsPlaceholder:
    def test_plain_string(self) -> None:
        assert contains_placeholder("hello") is False

    def test_interpolation_in_string(self) -> None:
        assert contains_placeholder("x ${last_user_message.content} y") is True

    def test_eval_operator(self) -> None:
        assert contains_placeholder({"a": {"$eval": "iteration_count"}}) is True

    def test_nested_dict_and_list(self) -> None:
        assert contains_placeholder({"a": [{"b": "${iteration_count}"}]}) is True

    def test_escaped_interpolation_is_not_a_placeholder(self) -> None:
        assert contains_placeholder("$${nope}") is False

    def test_escaped_operator_key_is_not_a_placeholder(self) -> None:
        assert contains_placeholder({"$$eval": "x"}) is False

    def test_interpolation_in_key(self) -> None:
        assert contains_placeholder({"k${iteration_count}": 1}) is True

    def test_non_strings_are_ignored(self) -> None:
        assert contains_placeholder({"n": 3, "b": True, "z": None, "l": [1, 2.5]}) is False


class TestValidateTemplatePaths:
    @pytest.mark.parametrize(
        "template",
        [
            "${last_user_message.content}",
            "${last_assistant_message.content}",
            "${messages[-2].content}",
            "${messages[0].tool_calls[0].arguments.file_path}",
            "${messages[0]['content']}",
            "${messages}",
            "${event}",
            "${lowercase(last_user_message.content)}",
            "${len(messages)}",
            "prefix ${last_user_message.content} suffix ${event}",
        ],
    )
    def test_valid_interpolations_on_request_start(self, template: str) -> None:
        validate_template_paths({"q": template}, RequestStartHookContext)

    @pytest.mark.parametrize(
        "expression",
        [
            "last_user_message.content",
            "messages[-4:]",
            "messages[:2]",
            "messages[1:]",
            "messages[0].tool_calls[0].name",
            "last_user_message.content + '!'",
            "messages[len(messages) - 1].content",
            "now",
            "{a: messages[0].role}",
        ],
    )
    def test_valid_eval_expressions(self, expression: str) -> None:
        validate_template_paths({"q": {"$eval": expression}}, RequestStartHookContext)

    def test_completion_only_fields_valid_on_completion(self) -> None:
        validate_template_paths(
            {"a": "${iteration_count}", "b": {"$eval": "total_tool_calls"}}, CompletionHookContext
        )

    def test_nested_dict_and_list_arguments_are_walked(self) -> None:
        validate_template_paths(
            {"a": {"b": ["${last_user_message.content}", "ok"]}}, RequestStartHookContext
        )

    def test_if_expression_is_validated(self) -> None:
        validate_template_paths(
            {"$if": "last_user_message", "then": "a", "else": "b"}, RequestStartHookContext
        )
        with pytest.raises(TemplateError, match="unknown field 'nope'"):
            validate_template_paths(
                {"$if": "nope", "then": "a", "else": "b"}, RequestStartHookContext
            )

    def test_names_bound_in_the_template_are_allowed(self) -> None:
        validate_template_paths(
            {
                "roles": {"$map": {"$eval": "messages"}, "each(m)": {"$eval": "m.role"}},
                "greeting": {"$let": {"who": "x"}, "in": "${who}"},
            },
            RequestStartHookContext,
        )

    def test_dynamic_index_names_are_checked(self) -> None:
        validate_template_paths(
            {"q": {"$eval": "messages[iteration_count].content"}}, CompletionHookContext
        )
        with pytest.raises(TemplateError, match="unknown field 'nope'"):
            validate_template_paths(
                {"q": {"$eval": "messages[nope].content"}}, CompletionHookContext
            )

    def test_unknown_root_rejected(self) -> None:
        with pytest.raises(TemplateError, match=r"unknown field 'tool_input' on CompletionHook"):
            validate_template_paths({"q": "${tool_input}"}, CompletionHookContext)

    def test_unknown_root_in_eval_rejected(self) -> None:
        with pytest.raises(TemplateError, match=r"unknown field 'tool_input'"):
            validate_template_paths({"q": {"$eval": "tool_input.path"}}, CompletionHookContext)

    def test_typo_rejected_and_message_names_expression(self) -> None:
        with pytest.raises(TemplateError, match=r"last_user_message\.contnet.*'contnet'"):
            validate_template_paths({"q": "${last_user_message.contnet}"}, RequestStartHookContext)

    def test_index_on_non_list_rejected(self) -> None:
        with pytest.raises(TemplateError, match="non-list"):
            validate_template_paths({"q": "${iteration_count[0]}"}, CompletionHookContext)

    def test_field_access_on_slice_rejected(self) -> None:
        with pytest.raises(TemplateError, match="cannot read field 'content' of list"):
            validate_template_paths(
                {"q": {"$eval": "messages[-4:].content"}}, RequestStartHookContext
            )

    def test_completion_field_rejected_on_request_start(self) -> None:
        with pytest.raises(TemplateError, match="unknown field 'iteration_count'"):
            validate_template_paths({"q": "${iteration_count}"}, RequestStartHookContext)

    @pytest.mark.parametrize(
        "template",
        ["${}", "${messages[}", "${abc", "${a | b}", "${1 +}", "${a..b}", "${a b}"],
    )
    def test_syntax_errors_in_interpolation_rejected(self, template: str) -> None:
        with pytest.raises(TemplateError):
            validate_template_paths({"q": template}, RequestStartHookContext)

    @pytest.mark.parametrize("expression", ["", "   ", "messages[", "a b", "1 +"])
    def test_syntax_errors_in_eval_rejected(self, expression: str) -> None:
        with pytest.raises(TemplateError):
            validate_template_paths({"q": {"$eval": expression}}, RequestStartHookContext)

    def test_eval_requires_string(self) -> None:
        with pytest.raises(TemplateError, match="string expression"):
            validate_template_paths({"q": {"$eval": 3}}, RequestStartHookContext)

    def test_escaped_interpolation_not_validated(self) -> None:
        validate_template_paths({"q": "$${nope}"}, RequestStartHookContext)

    @pytest.mark.parametrize("key", ["$schema", "$ref", "$notAnOperator"])
    def test_reserved_key_rejected(self, key: str) -> None:
        pattern = f"key '{re.escape(key)}' is reserved.*'{re.escape('$' + key)}'"
        with pytest.raises(TemplateError, match=pattern):
            validate_template_paths({"q": {key: "x"}}, RequestStartHookContext)

    def test_reserved_key_rejected_when_nested_in_list(self) -> None:
        with pytest.raises(TemplateError, match="reserved"):
            validate_template_paths({"q": [{"$schema": "x"}]}, RequestStartHookContext)

    def test_escaped_reserved_key_accepted(self) -> None:
        validate_template_paths({"q": {"$$schema": "x"}}, RequestStartHookContext)

    def test_operator_parameter_keys_accepted(self) -> None:
        validate_template_paths(
            {"q": {"$if": "event == 'on_request_start'", "$then": "a", "$else": "b"}},
            RequestStartHookContext,
        )

    def test_walk_stops_at_free_form_dict(self) -> None:
        validate_template_paths(
            {"q": "${messages[0].tool_calls[0].arguments.anything.goes.here}"},
            RequestStartHookContext,
        )

    def test_optional_fields_are_traversed(self) -> None:
        validate_template_paths({"q": "${last_user_message.tool_calls}"}, RequestStartHookContext)

    def test_literal_arguments_pass(self) -> None:
        validate_template_paths(
            {"a": 1, "b": ["x", {"c": "$"}], "d": None}, RequestStartHookContext
        )


class TestRenderArguments:
    def test_no_templates_returns_equal_copy(self) -> None:
        args: dict[str, Any] = {"a": 1, "b": ["x", {"c": "y"}]}
        rendered = render_arguments(args, _completion_context())
        assert rendered == args
        assert rendered is not args
        assert rendered["b"] is not args["b"]

    def test_eval_keeps_raw_type(self) -> None:
        rendered = render_arguments(
            {"n": {"$eval": "iteration_count"}, "m": {"$eval": "messages"}}, _completion_context()
        )
        assert rendered["n"] == 2
        assert isinstance(rendered["m"], list)
        assert rendered["m"][0]["content"] == "first question"

    def test_slice_of_messages(self) -> None:
        rendered = render_arguments({"recent": {"$eval": "messages[-2:]"}}, _completion_context())
        assert [m["content"] for m in rendered["recent"]] == ["file body", "the answer"]

    def test_interpolation_inserts_text(self) -> None:
        rendered = render_arguments(
            {"q": "Q: ${last_user_message.content}! n=${iteration_count}"}, _completion_context()
        )
        assert rendered["q"] == "Q: first question! n=2"

    def test_interpolation_of_object_is_rejected(self) -> None:
        with pytest.raises(TemplateResolutionError, match="array or object"):
            render_arguments({"q": "x ${messages[0]}"}, _completion_context())

    def test_whole_string_interpolation_is_text(self) -> None:
        rendered = render_arguments({"n": "${iteration_count}"}, _completion_context())
        assert rendered["n"] == "2"

    def test_non_ascii_is_preserved(self) -> None:
        ctx = CompletionHookContext(
            event="on_completion",
            messages=[HookMessage(role="user", content="привет")],
            iteration_count=1,
            total_tool_calls=0,
        )
        rendered = render_arguments({"q": "x ${messages[0].content}"}, ctx)
        assert rendered["q"] == "x привет"

    def test_recurses_into_dicts_and_lists(self) -> None:
        rendered = render_arguments(
            {"a": {"b": ["${last_assistant_message.content}", 7]}}, _completion_context()
        )
        assert rendered == {"a": {"b": ["the answer", 7]}}

    def test_escape_renders_literal_dollar_brace(self) -> None:
        rendered = render_arguments(
            {"q": "$${literal} and ${last_user_message.content}"}, _completion_context()
        )
        assert rendered["q"] == "${literal} and first question"

    def test_lone_escape_is_unescaped(self) -> None:
        rendered = render_arguments({"q": "$${literal}"}, _completion_context())
        assert rendered == {"q": "${literal}"}

    def test_lone_escaped_key_is_unescaped(self) -> None:
        rendered = render_arguments({"$$schema": "x"}, _completion_context())
        assert rendered == {"$schema": "x"}

    def test_negative_index(self) -> None:
        rendered = render_arguments({"q": "${messages[-2].content}"}, _completion_context())
        assert rendered["q"] == "file body"

    def test_keys_are_interpolated(self) -> None:
        rendered = render_arguments({"k${iteration_count}": "v"}, _completion_context())
        assert rendered == {"k2": "v"}

    def test_builtin_functions(self) -> None:
        rendered = render_arguments(
            {
                "upper": {"$eval": "uppercase(last_assistant_message.content)"},
                "count": {"$eval": "len(messages)"},
            },
            _completion_context(),
        )
        assert rendered == {"upper": "THE ANSWER", "count": 4}

    def test_map_operator(self) -> None:
        rendered = render_arguments(
            {"roles": {"$map": {"$eval": "messages"}, "each(m)": {"$eval": "m.role"}}},
            _completion_context(),
        )
        assert rendered["roles"] == ["user", "assistant", "tool", "assistant"]

    def test_if_operator(self) -> None:
        rendered = render_arguments(
            {"q": {"$if": "iteration_count > 1", "then": "many", "else": "few"}},
            _completion_context(),
        )
        assert rendered["q"] == "many"

    def test_none_before_the_end_of_the_path_raises(self) -> None:
        with pytest.raises(TemplateResolutionError, match="template.q"):
            render_arguments(
                {"q": {"$eval": "last_assistant_message.content"}}, _first_turn_context()
            )

    def test_missing_property_raises(self) -> None:
        with pytest.raises(TemplateResolutionError, match="nope"):
            render_arguments(
                {"q": {"$eval": "messages[1].tool_calls[0].arguments.nope"}}, _completion_context()
            )

    def test_terminal_none_is_passed_through(self) -> None:
        rendered = render_arguments(
            {"q": {"$eval": "last_assistant_message.tool_call_id"}}, _completion_context()
        )
        assert rendered == {"q": None}

    def test_terminal_none_interpolates_as_empty(self) -> None:
        rendered = render_arguments(
            {"q": "[${last_assistant_message.tool_call_id}]"}, _completion_context()
        )
        assert rendered == {"q": "[]"}

    def test_top_level_operator_must_render_to_object(self) -> None:
        with pytest.raises(TemplateResolutionError, match="object"):
            render_arguments({"$eval": "messages"}, _completion_context())

    def test_error_text_never_contains_context_values(self) -> None:
        ctx = CompletionHookContext(
            event="on_completion",
            messages=[HookMessage(role="user", content="SECRET-TOKEN-123")],
            iteration_count=1,
            total_tool_calls=0,
        )
        with pytest.raises(TemplateResolutionError) as exc_info:
            render_arguments({"q": {"$eval": "messages[0].content.missing"}}, ctx)
        assert "SECRET-TOKEN-123" not in str(exc_info.value)
