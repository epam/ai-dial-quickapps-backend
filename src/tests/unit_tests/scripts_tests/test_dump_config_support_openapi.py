import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.dump_config_support_openapi import (
    check_config_support_openapi,
    dump_config_support_openapi,
    get_config_support_openapi_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DUMP_SCRIPT = REPO_ROOT / "src" / "scripts" / "dump_config_support_openapi.py"
EXPECTED_OPERATIONS = {
    ("get", "/v1/configuration-support/application-schema"),
    ("get", "/v1/configuration-support/default-configuration"),
    ("get", "/v1/configuration-support/skills"),
    ("post", "/v1/configuration-support/skills/validate"),
}
REMOVED_PATHS = {
    "/v1/configuration-support/system-prompts",
    "/v1/configuration-support/tool-sets",
    "/v1/configuration-support/tools",
    "/v1/configuration-support/system-prompts/{deployment_name}",
    "/v1/configuration-support/tool-sets/{toolset_name}",
    "/v1/configuration-support/tools/{tool_name}",
    "/v1/configuration-support/template/{deployment}",
}


def _operation_keys(schema: dict) -> set[tuple[str, str]]:
    paths = schema.get("paths", {})
    return {(method.lower(), path) for path, methods in paths.items() for method in methods}


class TestConfigSupportOpenApiGeneration:
    def test_generated_spec_includes_all_endpoints(self):
        schema = get_config_support_openapi_schema()
        operations = _operation_keys(schema)

        assert operations == EXPECTED_OPERATIONS

    def test_removed_endpoints_are_absent(self):
        schema = get_config_support_openapi_schema()
        paths = set(schema.get("paths", {}))

        assert paths.isdisjoint(REMOVED_PATHS)

    def test_route_filter_excludes_non_config_support_routes(self):
        schema = get_config_support_openapi_schema()
        paths = set(schema.get("paths", {}))

        assert all(path.startswith("/v1/configuration-support") for path in paths)
        assert "/health" not in paths
        assert "/openapi.json" not in paths


class TestConfigSupportOpenApiCheck:
    def test_check_passes_on_matching_file(self, tmp_path: Path):
        output_file = tmp_path / "openapi.json"
        dump_config_support_openapi(str(output_file))

        check_config_support_openapi(str(output_file))

    def test_check_fails_on_stale_file(self, tmp_path: Path):
        output_file = tmp_path / "openapi.json"
        output_file.write_text('{"openapi": "3.1.0", "paths": {}}\n', encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            check_config_support_openapi(str(output_file))

        assert exc_info.value.code == 1

    def test_check_fails_when_file_missing(self, tmp_path: Path):
        missing = tmp_path / "missing.json"

        with pytest.raises(SystemExit) as exc_info:
            check_config_support_openapi(str(missing))

        assert exc_info.value.code == 1

    def test_cli_check_flag(self, tmp_path: Path):
        output_file = tmp_path / "openapi.json"
        dump_config_support_openapi(str(output_file))

        result = subprocess.run(
            [sys.executable, str(DUMP_SCRIPT), str(output_file), "--check"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "up to date" in result.stdout

    def test_generated_json_is_valid(self):
        schema = get_config_support_openapi_schema()
        serialized = json.dumps(schema)

        assert json.loads(serialized)["info"]["title"] == "QuickApps Configuration Support API"
