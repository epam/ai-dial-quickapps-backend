"""Projects (I#656) through DIAL Core with the per-request key. Opt-in.

The other suites call QuickApps in-process with the static key, which owns the test project,
so Core never limits anything. Here every case goes the way a Chat user does: a user token
calls the app **through Core**, Core gives the app a per-request key, and that key reaches
the project only through the app's approved resource dependencies (Core
[I#1930](https://github.com/epam/ai-dial-core/issues/1930)).

Skipped unless ``PROJECTS_CORE_PATH=true`` and the Core URL and credentials below are set.
Never part of ``make test`` or the ``integration_test*`` targets (marker
``projects_core_path``, not ``integration``). Run it with ``make projects_core_path_test``.

Setup:

1. DIAL Core with #1930 (resource dependencies) **and** ``projects`` as a declarable target
   type, plus the v2 project API. Until the #1930 stack lands on ``development`` this is a
   local Core build of that stack with the ``projects`` target patch.
2. QuickApps running with ``ENABLE_PREVIEW_FEATURES=true``, registered in Core as the
   ``quickapps2`` application type schema (the local docker-compose stack does this), and
   able to reach the test MCP server (``make start_test_server``; the Makefile target starts
   it). Set ``PROJECTS_CORE_MCP_URL`` when QuickApps runs in a container.
3. A user and an admin. The suite, as the admin, registers two apps in
   ``PROJECTS_CORE_APP_BUCKET`` (default ``public``: the admin can only consent to apps it
   can see), each declaring ``projects/{current-user}/`` READ and WRITE as resource
   dependencies, and grants the admin consent. It deletes the apps at the end.
   - ``qa_projects_core_files_app``: DIAL file tools + the MCP ``get_test_pdf`` tool;
   - ``qa_projects_core_router_app``: no file tools, only a ``dial-app`` tool that calls the
     files app (the nested-app case).
   The dependencies are declared ``required: false``, so with the consent revoked Core still
   calls the app and QuickApps' access preflight answers 403 ``project_access_denied``.
4. The user creates a fresh project in their bucket (deleted at the end).

Environment (``PROJECTS_CORE_`` prefix):

| Variable | Meaning |
|---|---|
| ``PROJECTS_CORE_PATH`` | ``true`` to run the suite |
| ``PROJECTS_CORE_DIAL_URL`` | DIAL Core URL, e.g. ``http://localhost:8090`` |
| ``PROJECTS_CORE_USER_TOKEN`` / ``PROJECTS_CORE_ADMIN_TOKEN`` | Bearer tokens (e.g. copied from Chat); or the Keycloak settings below |
| ``PROJECTS_CORE_KEYCLOAK_TOKEN_URL`` | Token endpoint for a password grant (tokens are fetched per call, they expire in minutes) |
| ``PROJECTS_CORE_KEYCLOAK_CLIENT_ID`` / ``..._CLIENT_SECRET`` / ``..._CA`` | Keycloak client and CA bundle |
| ``PROJECTS_CORE_USER`` / ``..._USER_PASSWORD``, ``PROJECTS_CORE_ADMIN`` / ``..._ADMIN_PASSWORD`` | Keycloak users |
| ``PROJECTS_CORE_APP_BUCKET`` | Bucket the apps are registered in (default ``public``) |
| ``PROJECTS_CORE_SCHEMA_ID`` | QuickApps application type schema id |
| ``PROJECTS_CORE_MCP_URL`` | The test MCP server as QuickApps reaches it |

The orchestrator model is ``--model`` (``MODEL=`` in the Makefile target).

Local docker-compose stack (``docker_compose_files/keycloak/dial-dev-realm.json``)::

    PROJECTS_CORE_DIAL_URL=http://localhost:8090
    PROJECTS_CORE_KEYCLOAK_TOKEN_URL=https://keycloak.localtest.me:8443/realms/dial-dev/protocol/openid-connect/token
    PROJECTS_CORE_KEYCLOAK_CLIENT_ID=dial-local
    PROJECTS_CORE_KEYCLOAK_CLIENT_SECRET=dial-local-dev-secret
    PROJECTS_CORE_KEYCLOAK_CA=docker_compose_files/keycloak/certs/ca.crt
    PROJECTS_CORE_USER=user-dev  PROJECTS_CORE_USER_PASSWORD=user-dev
    PROJECTS_CORE_ADMIN=admin-dev  PROJECTS_CORE_ADMIN_PASSWORD=admin-dev
    make projects_core_path_test MODEL=gpt-5.5-2026-04-24

The resource dependency records follow the shape proven on the #1930 stack
(``kind: dial.resourceLink``, ``access`` as a list); adjust ``_DEPENDENCIES`` if the released
Core changes it.
"""

import uuid
from collections.abc import Iterator

import httpx
import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.common.project_context import PROJECT_HEADER, ProjectContext
from quickapp.config.application import ApplicationConfig, Features
from quickapp.config.dial_files import DialFilesConfig
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.shared.project._project_access_preflight import PROJECT_ACCESS_DENIED_CODE
from tests.integration_tests.test_runner.config import TestConfig
from tests.integration_tests.test_runner.projects import (
    MARKER,
    TICKET_CODE,
    create_project,
    delete_project,
    header_value,
    list_artifacts,
    read_artifact,
    user_bucket,
)


class _CorePathSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROJECTS_CORE_", extra="ignore")

    path: bool = False
    dial_url: str = ""
    user_token: SecretStr | None = None
    admin_token: SecretStr | None = None
    keycloak_token_url: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: SecretStr | None = None
    keycloak_ca: str | None = None
    user: str = ""
    user_password: SecretStr | None = None
    admin: str = ""
    admin_password: SecretStr | None = None
    app_bucket: str = "public"
    schema_id: str = "https://mydial.epam.com/custom_application_schemas/quickapps2"
    mcp_url: str = "http://localhost:8003/mcp"

    def missing(self) -> list[str]:
        """What prevents the suite from running; empty when it can run."""
        if not self.path:
            return ["PROJECTS_CORE_PATH=true"]
        missing = [] if self.dial_url else ["PROJECTS_CORE_DIAL_URL"]
        keycloak = bool(self.keycloak_token_url)
        if not self.user_token and not (keycloak and self.user):
            missing.append("PROJECTS_CORE_USER_TOKEN or Keycloak + PROJECTS_CORE_USER")
        if not self.admin_token and not (keycloak and self.admin):
            missing.append("PROJECTS_CORE_ADMIN_TOKEN or Keycloak + PROJECTS_CORE_ADMIN")
        return missing


_SETTINGS = _CorePathSettings()
_MISSING = _SETTINGS.missing()

pytestmark = [
    pytest.mark.projects_core_path,
    pytest.mark.skipif(bool(_MISSING), reason=f"Core-path suite needs {', '.join(_MISSING)}"),
]

FILES_APP = "qa_projects_core_files_app"
ROUTER_APP = "qa_projects_core_router_app"
NESTED_TOOLSET = "project_files_agent"
MCP_TOOLSET = "project_outputs"
GET_TEST_PDF = "get_test_pdf"
LAUNCH_DATE = "2026-11-03"
_TIMEOUT = httpx.Timeout(600, connect=30)

# Two records, so a member with read-only access to a project still gets READ.
_DEPENDENCIES = [
    {
        "kind": "dial.resourceLink",
        "linkId": f"projects-{access.lower()}",
        "target": {"path": "projects/{current-user}/"},
        "access": [access],
        # Optional: with the consent revoked Core still calls the app, and the app's own
        # preflight is what answers (the consent-revoked case asserts on its error code).
        "required": False,
    }
    for access in ("READ", "WRITE")
]


class _Core:
    """Calls to Core as the user or the admin, with a fresh token each time."""

    def __init__(self, settings: _CorePathSettings) -> None:
        self._settings = settings

    def user(self) -> httpx.Client:
        return self._client(
            self._settings.user_token, self._settings.user, self._settings.user_password
        )

    def admin(self) -> httpx.Client:
        return self._client(
            self._settings.admin_token, self._settings.admin, self._settings.admin_password
        )

    def _client(
        self, token: SecretStr | None, username: str, password: SecretStr | None
    ) -> httpx.Client:
        value = token.get_secret_value() if token else self._password_grant(username, password)
        return httpx.Client(
            base_url=self._settings.dial_url,
            headers={"Authorization": f"Bearer {value}"},
            timeout=_TIMEOUT,
        )

    def _password_grant(self, username: str, password: SecretStr | None) -> str:
        secret = self._settings.keycloak_client_secret
        response = httpx.post(
            self._settings.keycloak_token_url,
            verify=self._settings.keycloak_ca or True,
            data={
                "grant_type": "password",
                "client_id": self._settings.keycloak_client_id,
                "client_secret": secret.get_secret_value() if secret else "",
                "username": username,
                "password": password.get_secret_value() if password else "",
                "scope": "openid",
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


def _app_id(name: str) -> str:
    return f"applications/{_SETTINGS.app_bucket}/{name}"


def _files_app_config(model: str) -> ApplicationConfig:
    outputs: ToolSet = MCPToolSet(
        name=MCP_TOOLSET,
        description="Returns test files",
        mcp_server_info=MCPServerInfo(url=_SETTINGS.mcp_url, protocol=MCPProtocol.streamable_http),
        allowed_tools=[GET_TEST_PDF],
    )
    return TestConfig.create_app_configuration(toolsets=[outputs], model=model)


def _router_app_config(model: str) -> ApplicationConfig:
    nested: ToolSet = DialAppToolSet(
        name=NESTED_TOOLSET,
        description="An agent with file tools that works in the current project's files.",
        deployment_id=_app_id(FILES_APP),
        transport="chat-completion",
    )
    config = TestConfig.create_app_configuration(toolsets=[nested], model=model)
    # No file tools of its own: whatever lands in the project was written by the nested app.
    # File tools are on by default (#710), so an empty `enabled_tools` turns them off.
    return config.model_copy(
        update={"features": Features(dial_files=DialFilesConfig(enabled_tools=[]))}
    )


def _app_body(name: str, config: ApplicationConfig) -> dict:
    return {
        "displayName": name,
        "description": "QuickApps projects Core-path suite (I#722)",
        "applicationTypeSchemaId": _SETTINGS.schema_id,
        "inputAttachmentTypes": ["*/*"],
        "applicationProperties": config.model_dump(mode="json", exclude_none=True),
        "resourceDependencies": _DEPENDENCIES,
    }


def _consent_path(name: str) -> str:
    return f"/v1/consent/{_app_id(name)}/admin-consent"


@pytest.fixture(scope="module")
def core() -> _Core:
    return _Core(_SETTINGS)


@pytest.fixture(scope="module")
def model(request: pytest.FixtureRequest) -> str:
    value = request.config.getoption("--model")
    if not value:
        pytest.fail("No model: pass --model (MODEL= in the Makefile target)")
    return value


@pytest.fixture(scope="module", autouse=True)
def apps(core: _Core, model: str) -> Iterator[None]:
    configs = {FILES_APP: _files_app_config(model), ROUTER_APP: _router_app_config(model)}
    with core.admin() as admin:
        for name, config in configs.items():
            admin.delete(f"/v1/{_app_id(name)}")
            admin.put(f"/v1/{_app_id(name)}", json=_app_body(name, config)).raise_for_status()
            admin.post(_consent_path(name)).raise_for_status()
    try:
        yield
    finally:
        with core.admin() as admin:
            for name in configs:
                admin.delete(f"/v1/{_app_id(name)}")


@pytest.fixture(scope="module")
def project(core: _Core, apps: None) -> Iterator[ProjectContext]:
    with core.user() as user:
        created = create_project(user, user_bucket(user))
    try:
        yield created
    finally:
        with core.user() as user:
            delete_project(user, created)


def _chat(core: _Core, app: str, project: ProjectContext, prompt: str) -> httpx.Response:
    with core.user() as user:
        return user.post(
            f"/openai/deployments/{_app_id(app)}/chat/completions",
            headers={PROJECT_HEADER: header_value(project)},
            json={"messages": [{"role": "user", "content": prompt}], "stream": False},
        )


def _message(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text[:1000]
    return response.json()["choices"][0]["message"]


def _answer(response: httpx.Response) -> str:
    return _message(response).get("content") or ""


def _artifact_text(core: _Core, project: ProjectContext, name: str) -> str:
    with core.user() as user:
        response = read_artifact(user, project, name)
    assert response.status_code == 200, f"{name} is not in artifacts/: {response.status_code}"
    return response.text


def test_instructions(core: _Core, project: ProjectContext):
    answer = _answer(_chat(core, FILES_APP, project, "What is 2+2? Answer in one line."))
    assert MARKER in answer


def test_context_file_read(core: _Core, project: ProjectContext):
    prompt = "Which ticket in the project's context files has priority P1? Give its id."
    assert TICKET_CODE in _answer(_chat(core, FILES_APP, project, prompt))


def test_write_lands_in_artifacts(core: _Core, project: ProjectContext):
    token = uuid.uuid4().hex[:12]
    name = f"write-{token}.md"
    prompt = f"Save the text '{token}' to a file named {name}."
    _message(_chat(core, FILES_APP, project, prompt))
    assert token in _artifact_text(core, project, name)


def test_cross_chat_file(core: _Core, project: ProjectContext):
    prompt = f"Save the note 'The launch date is {LAUNCH_DATE}.' to a file named notes.md."
    _message(_chat(core, FILES_APP, project, prompt))
    # A new chat: no history, only the project's artifacts/ connects the two.
    answer = _answer(
        _chat(core, FILES_APP, project, "When is the launch date? Look it up in your files.")
    )
    assert LAUNCH_DATE in answer


def test_nested_app(core: _Core, project: ProjectContext):
    # The router has no file tools: the file can only come from the nested app, which gets
    # `x-project-id` downstream and its own grant from Core.
    token = uuid.uuid4().hex[:12]
    name = f"nested-{token}.md"
    prompt = (
        f"Ask the {NESTED_TOOLSET} tool to save the text '{token}' to a file named {name}. "
        "Report its answer."
    )
    _message(_chat(core, ROUTER_APP, project, prompt))
    assert token in _artifact_text(core, project, name)


def test_tool_output_into_artifacts(core: _Core, project: ProjectContext):
    message = _message(
        _chat(core, FILES_APP, project, f"Call the {GET_TEST_PDF} tool and give me the file.")
    )
    attachments = (message.get("custom_content") or {}).get("attachments") or []
    urls = [a.get("url") or "" for a in attachments]
    assert any(project.contains(url) and url.endswith(".pdf") for url in urls), urls
    with core.user() as user:
        assert any(url.endswith(".pdf") for url in list_artifacts(user, project))


def test_consent_revoked(core: _Core, project: ProjectContext):
    with core.admin() as admin:
        admin.delete(_consent_path(FILES_APP)).raise_for_status()
    try:
        response = _chat(core, FILES_APP, project, "What is 2+2?")
    finally:
        with core.admin() as admin:
            admin.post(_consent_path(FILES_APP)).raise_for_status()
    assert response.status_code == 403, response.text[:1000]
    assert response.json()["error"]["code"] == PROJECT_ACCESS_DENIED_CODE
