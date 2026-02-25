import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import _PyInterpreterClient
from quickapp.internal_tooling.py_interpreter_tooling.handlers.session_manager import SessionManager

from tests.integration_tests.test_runner.config import SimilarityThreshold, TestConfig
from tests.integration_tests.test_runner.custom_function import CustomFunction
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.utils.tool_names_with_hash import ToolNames

logger = logging.getLogger(__name__)


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        "Text-to-image",
        "Image generation test case",
        similarity_threshold=0.8,
    ).add_user_message(
        user_message="Draw an image of a dinosaur. It should looks like super real with super quality image in size 1792x1024. When you ll be ready, please show me the image and say: Here is the image of a dinosaur. Do you like it?",
        tool_calls=[
            ToolCall(ToolNames.IMAGE_GENERATION_TOOL.value)
            .add_soft_argument_check(
                "query",
                [
                    "A realistic depiction of a dinosaur in its natural habitat, showcasing a large, majestic creature with scales and a long tail, surrounded by lush greenery and a prehistoric landscape.",
                    "A realistic depiction of a dinosaur in a prehistoric landscape, with lush vegetation and a clear blue sky.",
                    "A realistic depiction of a dinosaur, specifically a Tyrannosaurus Rex, in a prehistoric jungle setting. The dinosaur is standing majestically with its large, powerful legs and sharp teeth visible. The background features lush green vegetation, tall trees, and a clear blue sky. The scene captures the grandeur and might of the dinosaur in its natural habitat."
                    "A majestic dinosaur, highly detailed digital art of a Tyrannosaurus Rex in a prehistoric jungle setting, dramatic lighting, realistic textures, showing its powerful stance and detailed scales, cinematic composition",
                    "Photorealistic dinosaur in a natural prehistoric environment, hyper-detailed scales and features, cinematic lighting, ultra high definition",
                    "A dinosaur",
                ],
            )
            .add_strict_argument_check("size", "1536x1024")
            .add_strict_argument_check("quality", "high"),
        ],
        answer=[
            "Here is the image of a dinosaur. Do you like it?",
            "I'll help you generate an image of a dinosaur using the image generation tool. I'll create a detailed query to ensure we get an impressive dinosaur illustration.I've generated an image of a powerful Tyrannosaurus Rex in its natural prehistoric environment. The image shows the dinosaur with detailed scales and realistic features, set against a jungle backdrop. Would you like me to generate another dinosaur image with a different species or setting?",
        ],
    )
)
def test_text_to_image(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("Text-to-image2", "Image generation test case", similarity_threshold=0.7).add_user_message(
        user_message="Draw an image with small size 1024x1024 and in medium quality of A beautiful winter scene in Vilnius, Lithuania. Snow-covered baroque architecture with the iconic Gediminas Tower visible on the hill. The old town streets are blanketed in fresh white snow, with warm golden lights glowing from windows of historic buildings. The Cathedral Square with its bell tower is partially visible, all covered in pristine snow. Street lamps create a warm glow in the winter evening atmosphere. Traditional Lithuanian architectural details are visible on the colorful building facades despite the snow coverage.",
        tool_calls=[
            ToolCall(ToolNames.IMAGE_GENERATION_TOOL.value)
            .add_soft_argument_check(
                "query",
                [
                    "A beautiful winter scene in Vilnius, Lithuania. Snow-covered baroque architecture with the iconic Gediminas Tower visible on the hill. The old town streets are blanketed in fresh white snow, with warm golden lights glowing from windows of historic buildings. The Cathedral Square with its bell tower is partially visible, all covered in pristine snow. Street lamps create a warm glow in the winter evening atmosphere. Traditional Lithuanian architectural details are visible on the colorful building facades despite the snow coverage."
                ],
                similarity_threshold=0.6,
            )
            .add_strict_argument_check("size", "1024x1024")
            .add_strict_argument_check("quality", "medium"),
        ],
        answer=[
            "Here is the image of Vilnius in winter. How do you like it?",
            "Here is the image of Vilnius in winter. It captures the cityscape covered in snow with historical buildings under a clear blue sky. Did you like it?",
            "Here is the image of Vilnius in winter. It captures the snowy rooftops, Gediminas' Tower, and the charming Old Town streets. Let me know if you like it!",
            "I'll help you generate an image of Vilnius in winter using the image generation tool. Vilnius, the capital of Lithuania, is known for its beautiful Old Town, baroque architecture, and scenic winter landscapes. I've generated a winter scene of Vilnius featuring its iconic Old Town architecture covered in snow. The image captures the magical winter atmosphere of the Lithuanian capital with its historic baroque churches and buildings. Would you like me to generate another version or perhaps focus on a specific landmark in Vilnius?",
            "Here is the image of Vilnius in winter. How do you like it? The picture shows a snowy Vilnius cityscape with the historic Old Town, Gediminas’ Tower, and soft evening lights reflecting on the Neris River, all under a serene winter sky."
            "A beautiful winter scene in Vilnius, Lithuania. Snow-covered baroque architecture with the iconic Gediminas Tower visible on the hill. The old town streets are blanketed in fresh white snow, with warm golden lights glowing from windows of historic buildings. The Cathedral Square with its bell tower is partially visible, all covered in pristine snow. Street lamps create a warm glow in the winter evening atmosphere. Traditional Lithuanian architectural details are visible on the colorful building facades despite the snow coverage."
            "Here is the image you requested."
        ],
    )
)
def test_text_to_image2(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("Web search", "NBA winner 2025", similarity_threshold=0.7)
    .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
    .add_user_message(
        user_message="Which NBA club won in 2024-2025 season? Use web search to find the answer, don't use your own knowledge. In answer, please provide only the name of the club without any other text or explanations'",
        tool_calls=[
            ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=6).add_soft_argument_check(
                "query",
                [
                    "who won 2024-2025 NBA season"
                ],
            )
        ],
        answer=[
            "Oklahoma City Thunder",
            "Let me search for this information.Oklahoma City Thunder",
            "I need to find which NBA team won in the 2025 season using web search. Let me look that up for you.Oklahoma City Thunder"
        ]
    )
)
def test_web_search(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("Web search2", "How many Tesla cars were sold in 2024", similarity_threshold=0.7)
    .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
    .add_user_message(
        user_message="ONE NUMBER ONLY, NO EXPAINATIONS!!! Use web search and say how many Tesla cars were sold in 2024",
        tool_calls=[
            ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=6).add_soft_argument_check(
                "query",
                ["Amount of Tesla cars sold in 2024"],
            )
        ],
        answer=[
            "1,789,226",
            "I'll search for the latest information on Tesla sales in 2024 and provide just the number.1,789,226",
            "1789226"
        ],
    )
)
def test_web_search2(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("Web search3", "Search several items in web", similarity_threshold=0.7)
    .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
    .add_user_message(
        user_message="Who is Archimedes? Use web search to find information about him.",
        tool_calls=[
            ToolCall(ToolNames.WEB_SEARCH_TOOL.value, max_calls=5).add_soft_argument_check(
                "query",
                [
                    "Who is Archimedes?",
                    "Key biography facts, achievements, contributions to mathematics and science.",
                    "Who is Archimedes? Provide a concise overview: life dates, location (Syracuse), major contributions (mathematics, physics, engineering), Archimedes' principle of buoyancy, method of exhaustion, inventions (war machines, screw), key works (On the Sphere and Cylinder, Measurement of a Circle), and death circumstances."
                ],
            )
        ],
        answer=[
            '''
            Archimedes: The Genius of Antiquity Who Shaped Science and Engineering
Archimedes of Syracuse (c. 287 – c. 212 BC) was a preeminent ancient Greek mathematician, physicist, engineer, inventor, and astronomer, widely regarded as one of the greatest scientists in history. His work laid the foundations for numerous scientific fields, and his inventions and discoveries continue to influence technology and science to this day. He was born in the city of Syracuse in Sicily and spent most of his life there, with a period of study in Alexandria, Egypt.

Groundbreaking Contributions to Mathematics and Physics
Archimedes is celebrated for his revolutionary work in mathematics, where he anticipated modern calculus by using concepts like infinitesimals to prove geometrical theorems. He derived an accurate approximation of pi, calculated the area of a circle, and determined the surface area and volume of a sphere. In fact, he was so proud of his discovery that the volume of a sphere is two-thirds the volume of a cylinder that encloses it, he requested it be engraved on his tombstone.

In the realm of physics, Archimedes is credited with inventing the sciences of mechanics and hydrostatics. He formulated the law of the lever and pulleys, demonstrating how heavy objects could be moved with minimal force. He also established the concept of the center of gravity.

The "Eureka!" Moment and the Principle of Buoyancy
One of the most famous anecdotes about Archimedes is his "Eureka!" moment. Tasked by King Hiero II to determine if a new crown was made of pure gold without damaging it, Archimedes discovered the principle of buoyancy while taking a bath. He noticed that the water level rose as he submerged himself, realizing that the volume of displaced water was equal to the volume of his submerged body. This meant he could determine the crown's volume and, by comparing its weight to the weight of a pure gold sample of the same volume, ascertain its purity. Overjoyed with his discovery, he is said to have run naked through the streets of Syracuse shouting "Eureka!" meaning "I have found it!". This discovery led to the formulation of Archimedes' principle, which states that a body immersed in a fluid experiences a buoyant force equal to the weight of the fluid it displaces.

Ingenious Inventions
Archimedes was a prolific inventor. Among his most notable creations is the Archimedes screw, a device for raising water that is still used for irrigation and in sewage treatment plants. He also developed an early version of the odometer to measure distance.

During the Roman siege of Syracuse, Archimedes' genius was turned to warfare. He designed formidable "engines of war" to defend his city, including cranes capable of dropping heavy rocks and claws that could lift enemy ships out of the water. It is also said that he devised a system of mirrors to focus sunlight and set Roman ships ablaze.

Legacy and Death
Despite his crucial role in the city's defense, Syracuse eventually fell to the Romans in 212 BC. Archimedes was killed by a Roman soldier, reportedly because he was so engrossed in a mathematical problem that he refused to follow the soldier's orders. His legacy, however, endures. His writings and inventions have been studied for centuries, and his name is honored in numerous ways, including a crater and a mountain range on the Moon.
            '''
        ],
    ),
)
def test_web_search3(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("RAG search", "Search information in document", similarity_threshold=0.8).add_user_message(
        user_message="What are the tools to use when working with ontologies? Use attached document to find the answer. I want just the list of tools like 1. Name 2. Name etc...",
        attachments=[Path(__file__).parent / "test_documents/ontologies.pdf"],
        tool_calls=[ToolCall(ToolNames.RAG_SEARCH_TOOL.value, max_calls=6)],
        answer=[
            """
            1. Protégé
            2. TopBraid Composer
            3. OntoStudio
            4. Fluent Editor
            5. VocBench
            6. Swoop
            7. OBO-Edit""",
            """
            I'll search the attached document for information about tools used when working with ontologies.
           
           Based on the attached document, here are the tools for working with ontologies:
           
           1. Protégé
           2. TopBraid Composer
           3. OntoStudio
           4. Fluent Editor
           5. VocBench
           6. Swoop
           7. OBO-Edit'
            """
        ],
    )
)
def test_rag_search(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        "RAG search2",
        "Search information in document2",
        similarity_threshold=SimilarityThreshold.LENIENT.value,
    ).add_user_message(
        user_message="Which organization provide an article described in the document and when. I want an answer like: 'The article is provided by XXX organization in YYYY year'.",
        attachments=[Path(__file__).parent / "test_documents/weo.pdf"],
        tool_calls=[
            ToolCall(ToolNames.RAG_SEARCH_TOOL.value).add_soft_argument_check(
                "query",
                [
                    "Identify the organization that provided or published the article described in this document and the year of publication. Provide the organization name and year.",
                    "who is the author of the document and what is the year of publication",
                    "Which organization provided the article and when was it published?",
                    "Which organization provided this article or report and in what year was it published?",
                    "The article is provided by XXX organization in YYYY year"
                ],
                similarity_threshold=SimilarityThreshold.LENIENT.value)
        ],
        answer=[
            "The article is provided by INTERNATIONAL MONETARY FUND organization in 2025 year""",
        ],
    ),
)
def test_rag_search2(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        name="Image Recognition",
        description="Recognize the image content",
        similarity_threshold=SimilarityThreshold.STRICT.value)
    .add_user_message(
        user_message="ANSWER ONE WORD ONLY: What is shown in the attached picture? Do not use any external tools, use only your own vision. If you can't open or handle attachment, please say that you can't open it",
        attachments=[Path(__file__).parent / "test_documents/test.jpg"],
        answer=[
            "Elephant",
            "African Elephant",
            "Elephant."
        ],
    )
)
def test_image_recognition(client):
    pass


@pytest.mark.requires_session
@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase("PyInterpreter", "Python code interpreter")
    .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
    .add_user_message(
        user_message="25373773, 27273552, 237737373 sinus in radians of what number is the least? Use Python Interpreter tool to calculate. In answer, please provide only the number with the smallest sine value without any other text or explanations",
        tool_calls=[ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=5)],
        answer=[
            "27273552",
            "I'll calculate the sine values for these numbers and find which one has the smallest sine value.27273552",
            "I'll calculate the sine values for each of these numbers using the Python interpreter.27273552"
        ],
    )
)
def test_pyinterpreter(client):
    pass


@pytest.mark.requires_session
@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        "PyInterpreter2",
        "Python code interpreter",
        similarity_threshold=SimilarityThreshold.STRICT.value,
    )
    .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
    .add_user_message(
        user_message="Calculate the exact result using Python: `2^3 + 7!`. In answer, please provide only the exact result without any additional text or explanations.",
        tool_calls=[ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=5)],
        answer=[
            "5048",
            "I'll calculate `2^3 + 7!` using Python.5048",
            "I'll calculate the exact result of 2^3 + 7! using Python.5048",
            """I'll calculate this expression using Python to get the exact result.
               I need to import the math module first. Let me correct that: 5048"""
        ],
    )
)
def test_pyinterpreter2(client):
    pass


@pytest.mark.asyncio
@pytest.mark.requires_session
@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=(
            TstCase("PyInterpreter3", "Python code interpreter use same session test",
                    similarity_threshold=SimilarityThreshold.DEFAULT.value)
            .add_mock_date(datetime(2024, 12, 31, tzinfo=timezone.utc))
            .add_user_message(
                user_message="""Use python interpreter tool to write a function called calculate_hypotenuse in NumPy that takes two arguments and calculates the hypotenuse using the Pythagorean theorem.
                            Then, calculate and show me result of the calculate_hypotenuse function for 3 and 4. Don't answer with additional text or explanations, just calculate the result and show it to me.""",
                tool_calls=[
                    ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=5).add_custom_function_argument_check(
                        name="code",
                        value=["import numpy as np", "def calculate_hypotenuse"],
                        func=CustomFunction.contains,
                    )
                ],
                answer=[
                    "5.0",
                    "The hypotenuse is: 5.0",
                    "I'll write a function to calculate the hypotenuse using NumPy and show you the result for inputs 3 and 4. 5.0",
                    "I'll create a NumPy function to calculate the hypotenuse using the Pythagorean theorem and then calculate the result for the values 3 and 4. I've created the `calculate_hypotenuse` function using NumPy that implements the Pythagorean theorem (c = √(a² + b²)). The function takes two arguments representing the two sides of a right triangle and returns the length of the hypotenuse.For the values a=3 and b=4, the result is:**5.0**",
                    "I'll help you create a NumPy function to calculate the hypotenuse and then compute the result for values 3 and 4. 5.0"
                ],
            )
            .add_user_message(
                user_message="Now use python code interpreter and calculate hypotenuse for 8 and 15. And please use the same calculate_hypotenuse function that you defined before. Don't answer with additional text or explanations, just calculate the result and show it to me.",
                tool_calls=[
                    ToolCall(ToolNames.PYTHON_CODE_INTERPRETER.value, max_calls=5)
                    .add_custom_function_argument_check(
                        name="code",
                        value=["import numpy as np", "def calculate_hypotenuse"],
                        func=CustomFunction.not_contains,
                    )
                    .add_custom_function_argument_check(
                        name="code", value=["calculate_hypotenuse"], func=CustomFunction.contains
                    )
                ],
                answer=[
                    "17.0",
                    "The hypotenuse is: 17.0",
                ],
            )
    )
)
async def test_pyinterpreter_reuse_same_session(app_client: TestClient):
    pass


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pyinterpreter_close_session():
    async with _PyInterpreterClient(
            api_key=TestConfig.PY_INTERPRETER_API_KEY, base_url=TestConfig.PY_INTERPRETER_URL
    ) as client:
        session_manager = SessionManager(client=client, messages=[])
        session_id = await session_manager.ensure_valid_session(None, True)
        logger.info("Closing session, and try call py_interpreter again")
        await session_manager.close_session(session_id)
        new_session_id = await session_manager.ensure_valid_session(session_id, True)
        assert new_session_id != session_id


@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        "Rest-api-toolset-test",
        "Rest api toolset test case",
        similarity_threshold=0.8,
    ).add_user_message(
        user_message="""Use the shape box toolset to do next:
            1. Create new shapes box with ["square", "triangle"] and capacity 3
            2. Add new shape "circle" to the box
            3. Remove shapes "square" and "triangle" from the box
            4. Check is the circle in the box? And if yes, please say: Circle is in the box, the colour of the circle is ... .
        Do NOT DO ANY PARALLEL TOOL CALLS, do all calls in sequence one by one. In answer, please provide only the final answer without any other text or explanations""",
        tool_calls=[
            ToolCall(ToolNames.CREATE_SHAPE_BOX.value)
            .add_soft_argument_check(
                "box_data",
                [
                    """{"shapes": ["square", "triangle"], "capacity": 3}"""
                ],
            ),
            ToolCall(ToolNames.ADD_SHAPE_TO_BOX.value).add_soft_argument_check("shape", ["circle"]),
            ToolCall(ToolNames.REMOVE_SHAPES_FROM_BOX.value).add_soft_argument_check("shapes", ["square", "triangle"]),
            ToolCall(ToolNames.GET_SHAPES_FROM_BOX.value).add_soft_argument_check(name="shape", value=["circle"])

        ],
        answer=[
            "Circle is in the box, the colour of the circle is blue."
        ],
    )
)
def test_rest_api_toolcall(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="integration",
    test_case=TstCase(
        "mcp-tool-test",
        "MCP toolset test case",
        similarity_threshold=0.8,
    ).add_user_message(
        user_message="Use available tools (invert the string, create list from word) and do next thing with minimum communication with me: - Invert the string: `abrakadabra`, and after that, return the list containing resulting word",
        tool_calls=[
            ToolCall(ToolNames.INVERT_STRING.value)
            .add_soft_argument_check(
                "incoming",
                [
                    "abrakadabra"
                ],
            ),
            ToolCall(ToolNames.LIST_FROM_WORD.value, max_calls=3).add_soft_argument_check("incoming", ["arbadakarba"]),
        ],
        answer=[
            """Here are the results using the available tools:
            
            - Inverted string: arbadakarba
            - List containing the resulting word: ['a', 'r', 'b', 'a', 'd', 'a', 'k', 'a', 'r', 'b', 'a']
            
            If you need anything else or want me to perform another operation, let me know!""",
            "['a', 'r', 'b', 'a', 'd', 'a', 'k', 'a', 'r', 'b', 'a']"
        ],
    )
)
def test_mcp_toolcall(client):
    pass


@pytest.mark.integration
@e2e_test(
    runs=1,
    config_file_set="integration_simple",
    models_applicable_for_test=["gemini-2.5-pro", "gpt-5-2025-08-07", "gpt-5-mini-2025-08-07", "gpt-4.1-2025-04-14"],
    no_cache=True,
    test_case=TstCase(
        "Response format JSON schema",
        "Test response format with JSON schema for structured output",
        similarity_threshold=0.7,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "character_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The character's name."
                        },
                        "age": {
                            "type": "number",
                            "description": "The character's age."
                        },
                        "weapon": {
                            "type": "string",
                            "description": "The character's weapon."
                        },
                        "friend": {
                            "type": "boolean",
                            "description": "Is the character a friend?"
                        }
                    },
                    "required": ["name", "age", "weapon", "friend"],
                    "additionalProperties": False
                }
            }
        }
    ).add_user_message(
        user_message="DO NOT USE ANY TOOLS. You have enough info in the next message to provide an answer. Use next description and provide info about this character according to response schema: Henry was a 30 years old warrior. He used a sword as his main weapon. He was a friend to all.",
    )
)
def test_response_format_json_schema(client):
    pass
