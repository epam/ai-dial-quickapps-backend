"""Projects (I#656) with the static key: the app runs in-process, as in the other suites.

The module fixture creates a fresh project with the static test key (which owns it, so Core
limits nothing) and every case sends ``x-project-id`` for it. These cases check the data
flow; the per-request-key permission path is ``test_projects_core_path.py``.

Needs a DIAL Core with the v2 project API (the module is skipped when Core has none) and
``ENABLE_PREVIEW_FEATURES=true`` (set by the Makefile integration targets). Live
orchestrator (``no_cache=True``): a fresh project per run changes the system prompt.
"""

from collections.abc import Iterator
from typing import get_args

import httpx
import pytest

from quickapp.common.project_context import PROJECT_HEADER, ProjectContext
from quickapp.common.tool_names import INTERNAL_FILE_TOOL_NAME_PREFIX, INTERNAL_FILE_WRITE_TOOL_NAME
from quickapp.config.dial_files import DialFilesToolName
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from tests.integration_tests.test_runner.config import TestDialCoreConfig
from tests.integration_tests.test_runner.e2e_runner import e2e_test
from tests.integration_tests.test_runner.models import ToolCall, TstCase
from tests.integration_tests.test_runner.projects import (
    MARKER,
    TICKET_CODE,
    ProjectApiUnavailable,
    create_project,
    delete_project,
    header_value,
    list_artifacts,
    read_artifact,
    user_bucket,
)

LAUNCH_DATE = "2026-11-03"
NOTES_FILE = "notes.md"
MCP_TOOLSET = "project_outputs"
GET_TEST_PDF = "get_test_pdf"

_project: dict[str, ProjectContext] = {}


def _core() -> httpx.Client:
    return httpx.Client(
        base_url=TestDialCoreConfig.REMOTE_DIAL_URL,
        headers={"Api-Key": TestDialCoreConfig.REMOTE_DIAL_API_KEY},
        timeout=30,
    )


@pytest.fixture(scope="module", autouse=True)
def project() -> Iterator[ProjectContext]:
    with _core() as core:
        try:
            created = create_project(core, user_bucket(core))
        except ProjectApiUnavailable as e:
            pytest.skip(f"DIAL Core has no v2 project API: {e}")
        _project["current"] = created
        try:
            yield created
        finally:
            delete_project(core, created)


def _project_headers() -> dict[str, str]:
    return {PROJECT_HEADER: header_value(_project["current"])}


def _file_tools(*required: str) -> list[ToolCall]:
    """Every DIAL file tool as optional, except ``required`` (called at least once)."""
    return [
        ToolCall(name, min_calls=1 if name in required else 0, max_calls=6)
        for name in (
            f"{INTERNAL_FILE_TOOL_NAME_PREFIX}{tool}" for tool in get_args(DialFilesToolName)
        )
    ]


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    runs=1,
    no_cache=True,
    test_case=TstCase("project_instructions", "PROJECT.md reaches the system prompt")
    .with_headers(_project_headers)
    .add_user_message(
        user_message="What is the capital of France? Answer in one word.",
        tool_calls=_file_tools(),
        answer_contains=[MARKER],
    ),
)
def test_project_instructions(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    runs=1,
    no_cache=True,
    test_case=TstCase("project_context_file", "A file in the project's context/ is readable")
    .with_headers(_project_headers)
    .add_user_message(
        user_message="Which ticket in the project's context files has priority P1? Give its id.",
        # The id is only in context/tickets.csv.
        tool_calls=_file_tools(),
        answer_contains=[TICKET_CODE],
    ),
)
def test_project_context_file(client):
    pass


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    runs=1,
    no_cache=True,
    test_case=TstCase("project_cross_chat_file", "A file written in chat 1 is found in chat 2")
    .with_headers(_project_headers)
    .add_user_message(
        user_message=f"Save the note 'The launch date is {LAUNCH_DATE}.' to a file named {NOTES_FILE}.",
        tool_calls=_file_tools(INTERNAL_FILE_WRITE_TOOL_NAME),
    )
    .add_user_message(
        user_message="When is the launch date? Look it up in your files.",
        new_conversation=True,
        tool_calls=_file_tools(),
        answer_contains=[LAUNCH_DATE],
    ),
)
def test_project_cross_chat_file(client):
    # The note landed in the project's artifacts/ (the agent home), not in appdata.
    with _core() as core:
        response = read_artifact(core, _project["current"], NOTES_FILE)
    assert response.status_code == 200
    assert LAUNCH_DATE in response.text


@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    runs=1,
    no_cache=True,
    test_case=TstCase(
        "no_project", "Without the header nothing project-specific reaches the prompt"
    ).add_user_message(
        user_message="What is the capital of France? Answer in one word.",
        tool_calls=_file_tools(),
        answer_not_contains=[MARKER],
    ),
)
def test_no_project_header(client):
    pass


@pytest.mark.requires_mcp
@pytest.mark.integration
@e2e_test(
    config_file_set="empty",
    runs=1,
    no_cache=True,
    toolsets=[
        MCPToolSet(
            name=MCP_TOOLSET,
            description="Returns test files",
            mcp_server_info=MCPServerInfo(
                url="http://localhost:8003/mcp", protocol=MCPProtocol.streamable_http
            ),
            allowed_tools=[GET_TEST_PDF],
        )
    ],
    test_case=TstCase("project_tool_output", "An MCP tool file lands in the project's artifacts/")
    .with_headers(_project_headers)
    .add_user_message(
        user_message=f"Call the {GET_TEST_PDF} tool and give me the file.",
        tool_calls=[ToolCall(f"{MCP_TOOLSET}_{GET_TEST_PDF}", max_calls=2), *_file_tools()],
    ),
)
def test_project_tool_output(client):
    with _core() as core:
        artifacts = list_artifacts(core, _project["current"])
    assert any(url.endswith(".pdf") for url in artifacts), artifacts
