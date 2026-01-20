import json
from pathlib import Path

from pydantic.type_adapter import TypeAdapter

from quickapp.config.toolsets.rest_api import RestApiToolSet


class TestToolSetRest:
    @staticmethod
    def get_rest_toolset(port: int):
        file_path = Path(__file__).parent / "test_rest_toolset.json"
        data_text = file_path.read_text().replace("<PORT>", str(port))
        data = json.loads(data_text)
        tool_set: RestApiToolSet = TypeAdapter(RestApiToolSet).validate_python(data)
        return tool_set
