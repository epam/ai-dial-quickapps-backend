from pathlib import Path

import pytest
from tests.integration_tests.test_runner.config import SimilarityThreshold
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.utils.tool_names_with_hash import ToolNames

E2E_TEST_CASE = TstCase(
    "E2E Set",
    "Test e2e conversation, that involves all tools",
    similarity_threshold=SimilarityThreshold.LENIENT.value,
).add_user_message(
    user_message="What is Trinitrotoluene? use web search. After that, draw a cartoon-like image of TNT with burning fuse",
    tool_calls=[
        ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=3).add_soft_argument_check(
            "query",
            [
                "What is Trinitrotoluene?",
                "What is Trinitrotoluene (TNT) chemical compound properties uses",
            ],
        ),
        ToolCall(ToolNames.IMAGE_GENERATION_TOOL.value, max_calls=5).add_soft_argument_check(
            "query",
            [
                "A cartoon-like image of a TNT stick with a burning fuse, vibrant colors, and exaggerated features to emphasize its explosive nature.",
                "A cartoon-style illustration of a red cylindrical TNT stick with \"TNT\" written in black letters on its side, and a burning fuse on top with orange flames and smoke. The style should be fun and non-threatening, similar to old cartoons.",
                "A cartoon-style image of a classic TNT stick with a burning fuse. The TNT stick is bright red with bold white letters \'TNT\' on it, and the fuse is sparking at the end, ready to explode. The background is simple and colorful, emphasizing the playful, comic-book style.",
            ],
        ),
    ],
).add_user_message(
    user_message="Based on attached PDF file, Use RAG to extract the GDP forecast data for United States, China, India, Germany, United Kingdom. Then use PyInterpreter to calculate the average GDP Growth of these countries for 2025.",
    attachments=[Path(__file__).parent / "test_data/content/weo.pdf"],
    tool_calls=[
        ToolCall(ToolNames.RAG_SEARCH_TOOL.value, max_calls=5).add_soft_argument_check(
            "query",
            [
                "Extract GDP growth forecasts for 2025 for United States, China, India, Germany, and United Kingdom.",
            ],
        ),
        ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=10),
    ],
)


# Individual test for GPT-5
@pytest.mark.requires_session
@pytest.mark.e2e
@e2e_test(test_case=E2E_TEST_CASE, model="gpt-5-2025-08-07", runs=1)
def test_e2e_set_gpt5(client):
    pass


# Individual test for GPT-4 Turbo
@pytest.mark.requires_session
@pytest.mark.e2e
@e2e_test(test_case=E2E_TEST_CASE, model="gpt-4.1-2025-04-14", runs=1)
def test_e2e_set_gpt4_1(client):
    pass


# Individual test for Claude 4.5
# @pytest.mark.requires_session
# @pytest.mark.e2e
# @e2e_test(test_case=E2E_TEST_CASE, model="anthropic.claude-v4-5-sonnet-v1", runs=1)
# def test_e2e_set_claude45(client):
#     pass


# Individual test for Gemini
@pytest.mark.requires_session
@pytest.mark.e2e
@e2e_test(test_case=E2E_TEST_CASE, model="gemini-2.5-pro", runs=1)
def test_e2e_set_gemini(client):
    pass 
