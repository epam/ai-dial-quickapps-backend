import json
from unittest.mock import MagicMock, Mock

import pytest
from aidial_sdk.chat_completion import Stage
from pydantic import BaseModel

from quickapp.common import CompletionResult
# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper


@pytest.fixture
def mock_stage():
    stage = MagicMock(spec=Stage)
    stage.__enter__.return_value = stage
    stage.append_content = MagicMock()
    stage.append_name = MagicMock()
    return stage


@pytest.fixture
def mock_tool_config():
    config = MagicMock()
    config.display = None
    config.open_ai_tool.function.parameters.properties = {}
    return config


@pytest.fixture
def wrapper(mock_stage, mock_tool_config):
    return _MCPStageWrapper(
        stage=mock_stage,
        tool_config=mock_tool_config,
        stage_name="test_stage"
    )


@pytest.fixture
def params():
    return {"email": "test@example.com", "message": "Hello", "subject": "Test"}


def test_result_and_param(mock_stage, wrapper, params):
    result = CompletionResult(
        content=json.dumps({"content": "response content"}), content_type="application/json"
    )

    expected_params = '> ##### Request:\n```json\n{\n    "email": "test@example.com",\n    "message": "Hello",\n    "subject": "Test"\n}\n```\n\n'
    expected_result = '> ##### Response:\n```json\n{\n    "content": "response content"\n}\n```\n'

    with mock_stage:
        wrapper.add_parameters(params)
        wrapper.add_result(result)

    # Check that both calls were made
    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_result)


def test_serialize_base_model_request(mock_stage, wrapper):
    result = CompletionResult(
        content="", content_type="application/json"
    )
    class BaseModelParams(BaseModel):
        email: str = "a@a.com"
        message: str = "Hello"
        subject: str = "Test"

    base_model_request_value = BaseModelParams()

    expected = '> ##### Request:\n```json\n{\n    "key": {\n        "email": "a@a.com",\n        "message": "Hello",\n        "subject": "Test"\n    }\n}\n```\n\n'

    with mock_stage:
        wrapper.add_parameters({"key": base_model_request_value})

    mock_stage.append_content.assert_called_with(expected)


def test_serialize_request_object_with_dict(mock_stage, wrapper):
    result = CompletionResult(
        content="", content_type="application/json"
    )
    class TestClass:
        def __init__(self):
            self.name = "test"
            self.value = 42


    expected = '> ##### Request:\n```json\n{\n    "key": {\n        "name": "test",\n        "value": 42\n    }\n}\n```\n\n'

    with mock_stage:
        wrapper.add_parameters({"key": TestClass()})

    mock_stage.append_content.assert_called_with(expected)


def test_serialize_non_serializable(mock_stage, wrapper):
    result = CompletionResult(
        content="", content_type="application/json"
    )
    non_serializable = object()

    with pytest.raises(TypeError) as excinfo:
        with mock_stage:
            wrapper.add_parameters({"key": non_serializable})

    assert f"Object of type {type(non_serializable).__name__} isn't JSON serializable" in str(excinfo.value)

def test_xml_build_debug_info_from_params_and_result(mock_stage, wrapper, params):
    result = CompletionResult(
        content="<root><child>data</child></root>", content_type="application/xml"
    )
    expected_params = """> ##### Request:
```json
{
    "email": "test@example.com",
    "message": "Hello",
    "subject": "Test"
}
```

"""
    expected_result = """> ##### Response:
```xml
<?xml version="1.0" ?>
<root>
	<child>data</child>
</root>

```
"""
    with mock_stage:
        wrapper.add_parameters(params)
        wrapper.add_result(result)

    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_result)


def test_html_build_debug_info_from_params_and_result(mock_stage, wrapper, params):
    result = CompletionResult(
        content="<html><body><p>data</p></body></html>", content_type="text/html"
    )
    expected_params = """> ##### Request:
```json
{
    "email": "test@example.com",
    "message": "Hello",
    "subject": "Test"
}
```

"""
    expected_result = """> ##### Response:
```html
<html>
 <body>
  <p>
   data
  </p>
 </body>
</html>

```
"""
    with mock_stage:
        wrapper.add_parameters(params)
        wrapper.add_result(result)

    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_result)


def test_csv_build_debug_info_from_params_and_result(mock_stage, wrapper, params):
    result = CompletionResult(content="col1,col2\nval1,val2", content_type="text/csv")
    expected_params = """> ##### Request:
```json
{
    "email": "test@example.com",
    "message": "Hello",
    "subject": "Test"
}
```

"""
    expected_result = """> ##### Response:
|    | col1   | col2   |
|---:|:-------|:-------|
|  0 | val1   | val2   |
"""
    with mock_stage:
        wrapper.add_parameters(params)
        wrapper.add_result(result)

    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_result)

def test_build_debug_info_from_params_and_exception(mock_stage, wrapper, params):
    exception = ValueError("Invalid value provided")

    wrapper.add_parameters(params)
    wrapper.add_exception(exception)

    expected_params = "> ##### Request:\n```json\n{\n    \"email\": \"test@example.com\",\n    \"message\": \"Hello\",\n    \"subject\": \"Test\"\n}\n```\n\n"
    expected_exception = "> ##### Exception:\nValueError: Invalid value provided\n"

    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_exception)

def test_exception_handling_in_format_response(mock_stage, wrapper, params):
    result = CompletionResult(
        content={"content": "response content"}, content_type="application/json"
    )

    expected_params = """> ##### Request:
```json
{
    "email": "test@example.com",
    "message": "Hello",
    "subject": "Test"
}
```

"""
    # When JSON formatting fails, it should fallback to the raw content
    expected_result = """> ##### Response:
```json
{'content': 'response content'}
```
"""

    with mock_stage:
        wrapper.add_parameters(params)
        wrapper.add_result(result)

    assert mock_stage.append_content.call_count == 2
    mock_stage.append_content.assert_any_call(expected_params)
    mock_stage.append_content.assert_any_call(expected_result)