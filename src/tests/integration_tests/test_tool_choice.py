import pytest

from tests.integration_tests.test_runner.config import SimilarityThreshold
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.utils.tool_names import ToolNames


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    no_cache=True,
    test_case=TstCase(
        "tool_choice_required",
        "tool_choice=required forces a calculator tool call on the first iteration",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
        tool_choice="required",
    ).add_user_message(
        user_message="Write Python code to calculate the factorial of 10 and print the result",
        tool_calls=[
            ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, min_calls=1, max_calls=3),
        ],
    ),
)
def test_tool_choice_required(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    no_cache=True,
    test_case=TstCase(
        "tool_choice_none",
        "tool_choice=none prevents tool calls even for calculation requests",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
        tool_choice="none",
    ).add_user_message(
        user_message="Use the python interpreter to calculate 2 + 2",
        tool_calls=[],
        answer=[
            "4",
            "2 + 2 = 4",
            "The answer is 4",
            "I can't run the code interpreter in this message, but the result of 2 + 2 is 4.",
            "I can't run the Python interpreter in this turn. The result is 2 + 2 = 4.",
            "I do not have access to a Python interpreter or any calculation tools at the moment. Because I am strictly required to use tools for all math, I cannot perform calculations—even simple ones like 2 + 2. ",
            "I’m sorry, but I can’t run the requested calculation tool in this turn, so I can’t provide the computed result under the current constraints.",
        ],
    ),
)
def test_tool_choice_none(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    no_cache=True,
    test_case=TstCase(
        "tool_choice_function",
        "tool_choice with specific function name forces the calculator tool",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
        tool_choice={
            "type": "function",
            "function": {"name": ToolNames.PYTHON_CODE_INTERPRETER.value},
        },
    ).add_user_message(
        user_message="What is the square root of 144?",
        tool_calls=[
            ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, min_calls=1, max_calls=3),
        ],
        answer=["12", "square root of 144 is 12", "√144 = 12"],
    ),
)
def test_tool_choice_specific_function(client):
    pass
