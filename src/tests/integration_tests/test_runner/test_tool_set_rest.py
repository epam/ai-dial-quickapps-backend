import json

from pydantic.type_adapter import TypeAdapter

from quickapp.config.toolsets.rest_api import RestApiToolSet
from tests.integration_tests.test_runner.paths import TOOLSETS_DIR


class TestToolSetRest:
    @staticmethod
    def get_rest_toolset(port: int):
        file_path = TOOLSETS_DIR / "test_rest_toolset.json"
        data_text = file_path.read_text().replace("<PORT>", str(port))
        data = json.loads(data_text)
        tool_set: RestApiToolSet = TypeAdapter(RestApiToolSet).validate_python(data)
        return tool_set
