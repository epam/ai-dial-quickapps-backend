import pytest

from tests.integration_tests.test_runner.config import SimilarityThreshold
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    no_cache=True,
    test_case=TstCase(
        "external_tool_surfaced",
        "agent surfaces a client-provided tool call when the model selects it",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_account_balance",
                    "description": "Get the current balance for a bank account",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {
                                "type": "string",
                                "description": "The unique account identifier",
                            }
                        },
                        "required": ["account_id"],
                    },
                },
            }
        ],
    ).add_user_message(
        user_message="What is the current balance for account ACC-9876?",
        external_tool_calls=[
            ToolCall("get_account_balance", min_calls=1, max_calls=1).add_soft_argument_check(
                "account_id", ["ACC-9876"]
            ),
        ],
    ),
)
def test_external_tool_surfaced(client):
    pass
