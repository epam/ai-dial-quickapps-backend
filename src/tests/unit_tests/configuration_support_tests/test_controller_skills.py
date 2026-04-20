from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.configuration_support._controller import _Controller
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from quickapp.skills.agent_skills_provider import AgentSkillsProvider, SkillMetadata

VALID_SKILL_CONTENT = (
    "---\n" "name: my-skill\n" "description: A test skill\n" "---\n" "Body content\n"
)

BASE_URL = "http://test"
SKILLS_URL = "/v1/configuration-support/skills"
VALIDATE_URL = "/v1/configuration-support/skills/validate"


def _make_controller(
    skills: list[SkillMetadata] | None = None,
) -> _Controller:
    skills_provider = MagicMock(spec=AgentSkillsProvider)
    skills_provider.get_all_skills.return_value = skills or []

    dial_settings = MagicMock()
    dial_settings.url = "https://dial.example.com"
    dial_settings.api_version = "2025-01-01-preview"

    return _Controller(
        config_resolver=MagicMock(spec=ConfigResolver),
        service=MagicMock(spec=ToolConfigCoreService),
        skills_provider=skills_provider,
        dial_settings=dial_settings,
    )


def _make_app(controller: _Controller) -> FastAPI:
    app = FastAPI()
    controller.register_routes(app)
    return app


class TestGetSkills:
    @pytest.mark.asyncio
    async def test_returns_predefined_skills(self):
        skills = [
            SkillMetadata(name="skill-a", description="Skill A"),
            SkillMetadata(name="skill-b", description="Skill B"),
        ]
        app = _make_app(_make_controller(skills=skills))

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.get(SKILLS_URL)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "skill-a"
        assert data[1]["name"] == "skill-b"

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        app = _make_app(_make_controller(skills=[]))

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.get(SKILLS_URL)

        assert response.status_code == 200
        assert response.json() == []


class TestValidateSkill:
    @pytest.mark.asyncio
    @patch("quickapp.configuration_support._controller.AsyncDial")
    async def test_valid_prompt_returns_metadata(self, mock_dial_cls):
        prompt = MagicMock()
        prompt.content = VALID_SKILL_CONTENT
        mock_client = MagicMock()
        mock_client.prompts = MagicMock()
        mock_client.prompts.get = AsyncMock(return_value=prompt)
        mock_dial_cls.return_value = mock_client

        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/my-skill"},
                headers={"api-key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-skill"
        assert data["description"] == "A test skill"

    @pytest.mark.asyncio
    @patch("quickapp.configuration_support._controller.AsyncDial")
    async def test_prompt_not_found_returns_404(self, mock_dial_cls):
        from aidial_client import DialException

        mock_client = MagicMock()
        mock_client.prompts = MagicMock()
        mock_client.prompts.get = AsyncMock(
            side_effect=DialException(message="Not found", status_code=404)
        )
        mock_dial_cls.return_value = mock_client

        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/missing"},
                headers={"api-key": "test-key"},
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    @patch("quickapp.configuration_support._controller.AsyncDial")
    async def test_empty_content_returns_422(self, mock_dial_cls):
        prompt = MagicMock()
        prompt.content = None
        mock_client = MagicMock()
        mock_client.prompts = MagicMock()
        mock_client.prompts.get = AsyncMock(return_value=prompt)
        mock_dial_cls.return_value = mock_client

        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/empty"},
                headers={"api-key": "test-key"},
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    @patch("quickapp.configuration_support._controller.AsyncDial")
    async def test_invalid_frontmatter_returns_422(self, mock_dial_cls):
        prompt = MagicMock()
        prompt.content = "No frontmatter here"
        mock_client = MagicMock()
        mock_client.prompts = MagicMock()
        mock_client.prompts.get = AsyncMock(return_value=prompt)
        mock_dial_cls.return_value = mock_client

        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/bad"},
                headers={"api-key": "test-key"},
            )

        assert response.status_code == 422
        assert "frontmatter" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self):
        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/my-skill"},
            )

        assert response.status_code == 401

    @pytest.mark.asyncio
    @patch("quickapp.configuration_support._controller.AsyncDial")
    async def test_dial_401_returns_401(self, mock_dial_cls):
        from aidial_client import DialException

        mock_client = MagicMock()
        mock_client.prompts = MagicMock()
        mock_client.prompts.get = AsyncMock(
            side_effect=DialException(message="Unauthorized", status_code=401)
        )
        mock_dial_cls.return_value = mock_client

        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "dial-prompt", "url": "prompts/bucket/my-skill"},
                headers={"api-key": "bad-key"},
            )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_skill_type_returns_422(self):
        app = _make_app(_make_controller())

        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                VALIDATE_URL,
                json={"type": "mystery", "url": "prompts/bucket/skill"},
                headers={"api-key": "test-key"},
            )

        assert response.status_code == 422
