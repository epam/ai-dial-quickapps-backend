from datetime import date
from pathlib import Path

import pytest
from tests.test_runner.e2e_runner import e2e_test
from tests.test_runner.models import ToolCall, TstCase
from tests.test_runner.utils.tool_names_with_hash import ToolNames


@pytest.mark.integration
@e2e_test(config_file_set="integration",
          test_case=TstCase(
              "WebSearch and Text-to-image",
              "WebSearch and Text-To-image",
              similarity_threshold=0.8,
          )
          .add_mock_date(date(2024, 12, 31))
          .add_user_message(
              user_message="Use web search once to get current weather in Kyiv then Draw an image of Kyiv in the setting of the current weather. The picture should be with high quality and 1000x1000 size and natural style.",
              tool_calls=[
                  ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=4),
                  ToolCall(ToolNames.IMAGE_GENERATION_TOOL.value)
                  .add_soft_argument_check(
                      "query",
                      [
                          "Kyiv cityscape with mostly sunny weather, clear skies, and a temperature of 35°F (1.67°C). The scene should show a bright day with no precipitation, capturing the essence of a sunny winter day in Kyiv.",
                          "A daytime cityscape of Kyiv, Ukraine on a sunny winter day. Featured prominently are the golden domes of Saint Sophia Cathedral and other historic churches. The sky is clear blue, with some light clouds. The scene shows a crisp winter day with some snow on the ground, capturing the city's blend of historic architecture and modern buildings. The sunlight gleams off the golden domes.",
                          "A winter scene of Kyiv, Ukraine, with snow-covered streets and buildings. The sky is overcast, typical of a cold December day. Iconic landmarks such as St. Sophia's Cathedral are visible, surrounded by snow-laden trees and a serene, wintry atmosphere.",
                          "A high-quality, vivid image of Kyiv city under mostly sunny weather conditions. Show iconic landmarks such as St. Sophia's Cathedral, a clear blue sky with few clouds, bright sunlight, and the lively city atmosphere. The temperature is warm (24°C), moderate humidity, and a gentle breeze. The scene should feel inviting and modern, reflecting today's pleasant weather.",
                          "A photorealistic image of Kyiv on a mostly cloudy summer day"
                      ],
                  )
                  .add_strict_argument_check("size", "1024x1024")
                  .add_strict_argument_check("style", "natural")
                  .add_strict_argument_check("quality", "hd"),
              ],
              answer=[
                  "Here is the image of Kyiv with the current weather. Did you like it?",
                  "The current weather in Kyiv is sunny with a temperature of 14°C (58°F). The real feel temperature is 13°C (55°F) with 68% humidity. Here is an image of Kyiv on a sunny day, as you requested:"
              ],
          ))
def test_web_search_and_text_to_image(client):
    pass


@pytest.mark.requires_session
@pytest.mark.integration
@e2e_test(config_file_set="integration",
          test_case=TstCase(
              "RAG+Interpreter", "Search information in document, and calculate it"
          ).add_user_message(
              user_message="""Based on attached PDF file: extract the GDP forecast data for the next countries of 2023 year: India, China, Brazil, Japan, United States with rag search tool, then calculate the average GDP Growth with py interpreter tool.
        In the result i want to see next structure:
         1. India: value%
         2. China: value%
         3. United States: value%
         4. Brazil: value%
         5. Japan: value%
         The average GDP growth for the selected countries is as follows:
- **2023**: value%
- **2024**: value%
DO NOT PROVIDE ANY ADDITIONAL INFORMATION, EXPLANATIONS, SUGGESTIONS OR QUESTIONS!!!. I NEED AN ANSWER IN FORMAT DESCRIBED ABOVE!!!.""",
              attachments=[Path(__file__).parent / "test_documents/weo.pdf"],
              tool_calls=[
                  ToolCall(ToolNames.RAG_SEARCH_TOOL.value, max_calls=10),
                  ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=4),
              ],
              answer=[
                  """
                  1. India: 6.5%
                  2. China: 4.6%
                  3. United States: 2.7%
                  4. Brazil: 2.2%
                  5. Japan: 1.1%
                  The average GDP growth for the selected countries is as follows:
      - **2023**: 3.04%
      - **2024**: 2.82%
      """,
              """
      1. India: 8.2% [IMF WEO PDF, Annex Table 1. Selected Economies Real GDP Growth]
2. China: 5.2% [IMF WEO PDF, Annex Table 1. Selected Economies Real GDP Growth]
3. United States: 2.9% [IMF WEO PDF, Annex Table 1. Selected Economies Real GDP Growth]
4. Brazil: 3.2% [IMF WEO PDF, Annex Table 1. Selected Economies Real GDP Growth]
5. Japan: 1.5% [IMF WEO PDF, Annex Table 1. Selected Economies Real GDP Growth]
The average GDP growth for the selected countries is as follows:
- 2023: 4.2% [Calculated using Python interpreter]
- 2024: 3.52% [Calculated using Python interpreter]
"""
        ]
    )
          )
def test_rag_interpreter(client):
    pass


@pytest.mark.integration
@e2e_test(config_file_set="integration",
          test_case=TstCase(
              name="Image recognition and Web search",
              description="Image recognition and Web search",
              similarity_threshold=0.85,
          )
          .add_user_message(
              user_message="Identify the movie on the attached image without any tool calling. Then find information about this movie Budget and Worldwide Gross using web search. Provide the result in the EXACT fromat: \n\rThe movie in the attached image: <movie name>. \n\rBudget: <budget>. \n\rWorldwide Gross: <gross>. \n\r\n\r You may add sources if needed, but it's not required.",
              attachments=[Path(__file__).parent / "test_documents/unknown.png"],
              tool_calls=[
                  ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=6).add_soft_argument_check(
                      "query",
                      [
                          "significance of the number 42 in The Hitchhiker's Guide to the Galaxy",
                          "The Hitchhiker's Guide to the Galaxy significance and details",
                          "The Hitchhiker's Guide to the Galaxy movie budget and worldwide gross"
                      ],
                  ),
              ],
              answer=[
                  """The movie in the attached image: "The Hitchhiker's Guide to the Galaxy,".
                  Budget: Approximately $50 million
                  Worldwide Gross: Over $104 million
              """
              ]
          ).add_mock_date(date(2024, 12, 31))
          )
def test_image_recognition_and_web_search(client):
    pass
