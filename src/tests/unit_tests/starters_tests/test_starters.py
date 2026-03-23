import logging

import pytest
from fastapi_injector import Injected
from injector import Binder
from pydantic import ValidationError
from starlette.testclient import TestClient

from quickapp.application import Configuration
from quickapp.config.application import ApplicationConfig, OrchestratorConfig
from quickapp.config.dial_deployment import DialDeploymentConfig, DialDeploymentParameters
from quickapp.config.prompt import CustomSystemPromptConfig
from quickapp.config.starters import ConversationStarter, ConversationStartersConfig
from quickapp.starters._button import _Button, _create_buttons
from quickapp.starters._utils import _create_dial_buttons, create_starters_configuration
from quickapp.starters.starters_module import StartersModule
from tests.unit_tests.common.common import create_test_app


class TestConversationStarterConfig:
    def test_valid_starter(self):
        starter = ConversationStarter(title="Hello", text="Say hello")
        assert starter.title == "Hello"
        assert starter.text == "Say hello"

    def test_valid_config_defaults(self):
        config = ConversationStartersConfig(
            starters=[ConversationStarter(title="Hello", text="Say hello")]
        )
        assert config.intro_text == "Select an action"
        assert config.chat_message_input_disabled is False
        assert config.auto_submit is True

    def test_valid_config_custom_fields(self):
        config = ConversationStartersConfig(
            intro_text="Pick one",
            chat_message_input_disabled=True,
            auto_submit=False,
            starters=[ConversationStarter(title="A", text="B")],
        )
        assert config.intro_text == "Pick one"
        assert config.chat_message_input_disabled is True
        assert config.auto_submit is False

    def test_empty_starters_list_rejected(self):
        with pytest.raises(ValidationError, match="starters"):
            ConversationStartersConfig(starters=[])


class TestButton:
    def test_to_json_schema(self):
        button = _Button(value=1, caption="Go", populateText="run it")
        schema = button.to_json_schema()

        assert schema["const"] == 1
        assert schema["title"] == "Go"
        assert schema["dial:widgetOptions"]["populateText"] == "run it"
        assert schema["dial:widgetOptions"]["submit"] is True
        assert schema["dial:widgetOptions"]["confirmationMessage"] is None

    def test_to_json_schema_with_confirmation(self):
        button = _Button(value=2, caption="Delete", confirmationText="Are you sure?")
        schema = button.to_json_schema()

        assert schema["dial:widgetOptions"]["confirmationMessage"] == "Are you sure?"

    def test_create_buttons(self):
        buttons = [
            _Button(value=1, caption="A", populateText="a"),
            _Button(value=2, caption="B", populateText="b"),
        ]
        result = _create_buttons(buttons=buttons)

        assert result["type"] == "object"
        assert result["additionalProperties"] is False
        assert result["dial:chatMessageInputDisabled"] is False

        prop = result["properties"]["starter"]
        assert prop["description"] == "Select an action"
        assert prop["type"] == "number"
        assert prop["dial:widget"] == "buttons"
        assert len(prop["oneOf"]) == 2
        assert prop["oneOf"][0]["title"] == "A"
        assert prop["oneOf"][1]["title"] == "B"

    def test_create_buttons_custom_params(self):
        buttons = [_Button(value=1, caption="X")]
        result = _create_buttons(
            buttons=buttons,
            property_name="action",
            description="Choose",
            chat_disabled=True,
        )

        assert result["dial:chatMessageInputDisabled"] is True
        assert "action" in result["properties"]
        assert result["properties"]["action"]["description"] == "Choose"


class TestCreateDialButtons:
    def test_creates_correct_buttons(self):
        starters = [
            ConversationStarter(title="Hello", text="Say hello"),
            ConversationStarter(title="Help", text="I need help"),
        ]
        buttons = _create_dial_buttons(starters, auto_submit=True)

        assert len(buttons) == 2
        assert buttons[0].const == 1
        assert buttons[0].title == "Hello"
        assert buttons[0].populateText == "Say hello"
        assert buttons[0].submit is True

        assert buttons[1].const == 2
        assert buttons[1].title == "Help"
        assert buttons[1].populateText == "I need help"
        assert buttons[1].submit is True

    def test_single_starter(self):
        buttons = _create_dial_buttons(
            [ConversationStarter(title="Go", text="go")], auto_submit=True
        )
        assert len(buttons) == 1
        assert buttons[0].const == 1

    def test_auto_submit_false(self):
        starters = [
            ConversationStarter(title="Hello", text="Say hello"),
        ]
        buttons = _create_dial_buttons(starters, auto_submit=False)

        assert len(buttons) == 1
        assert buttons[0].submit is False
        assert buttons[0].populateText == "Say hello"


class TestCreateStartersConfiguration:
    def test_default_config(self):
        config = ConversationStartersConfig(
            starters=[
                ConversationStarter(title="Hello", text="Say hello"),
                ConversationStarter(title="Help", text="I need help"),
            ]
        )
        schema = create_starters_configuration(config)

        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["dial:chatMessageInputDisabled"] is False

        prop = schema["properties"]["starter"]
        assert prop["description"] == "Select an action"
        assert prop["dial:widget"] == "buttons"
        assert len(prop["oneOf"]) == 2
        assert prop["oneOf"][0]["const"] == 1
        assert prop["oneOf"][0]["title"] == "Hello"
        assert prop["oneOf"][0]["dial:widgetOptions"]["populateText"] == "Say hello"
        assert prop["oneOf"][1]["const"] == 2
        assert prop["oneOf"][1]["title"] == "Help"

    def test_custom_intro_text(self):
        config = ConversationStartersConfig(
            intro_text="Pick an option",
            starters=[ConversationStarter(title="A", text="a")],
        )
        schema = create_starters_configuration(config)
        assert schema["properties"]["starter"]["description"] == "Pick an option"

    def test_chat_disabled(self):
        config = ConversationStartersConfig(
            chat_message_input_disabled=True,
            starters=[ConversationStarter(title="A", text="a")],
        )
        schema = create_starters_configuration(config)
        assert schema["dial:chatMessageInputDisabled"] is True

    def test_auto_submit_default(self):
        config = ConversationStartersConfig(
            starters=[ConversationStarter(title="A", text="a")],
        )
        schema = create_starters_configuration(config)
        opts = schema["properties"]["starter"]["oneOf"][0]["dial:widgetOptions"]
        assert opts["submit"] is True

    def test_auto_submit_false(self):
        config = ConversationStartersConfig(
            auto_submit=False,
            starters=[
                ConversationStarter(title="A", text="a"),
                ConversationStarter(title="B", text="b"),
            ],
        )
        schema = create_starters_configuration(config)
        for entry in schema["properties"]["starter"]["oneOf"]:
            assert entry["dial:widgetOptions"]["submit"] is False


def _make_app_config(
    starters: list[str] | None = None,
    conversation_starters: ConversationStartersConfig | None = None,
) -> ApplicationConfig:
    return ApplicationConfig(
        orchestrator=OrchestratorConfig(
            deployment=DialDeploymentConfig(
                name="test-model", parameters=DialDeploymentParameters()
            ),
            system_prompt=CustomSystemPromptConfig(
                type="custom", content="test", variables={"t": "t"}
            ),
        ),
        contexts=[],
        tool_sets=[],
        starters=starters,
        conversation_starters=conversation_starters,
    )


def _make_starters_app(app_config: ApplicationConfig) -> TestClient:
    def configure(binder: Binder):
        binder.bind(ApplicationConfig, to=app_config)

    app = create_test_app([StartersModule, configure])

    @app.get("/test")
    async def _endpoint(configs: list[Configuration] = Injected(list[Configuration])):
        return {"count": len(configs), "config": configs[0] if configs else None}

    return TestClient(app)


class TestStartersModuleDispatch:
    def test_neither_set_returns_empty(self):
        client = _make_starters_app(_make_app_config())
        response = client.get("/test")

        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_deprecated_starters_emits_warning(self, caplog: pytest.LogCaptureFixture):
        client = _make_starters_app(_make_app_config(starters=["Hello", "Help"]))

        with caplog.at_level(logging.WARNING, logger="quickapp.starters.starters_module"):
            response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

        config = data["config"]
        assert config["properties"]["starter"]["type"] == "number"
        assert len(config["properties"]["starter"]["oneOf"]) == 2

        assert any("deprecated" in r.message.lower() for r in caplog.records)

    def test_conversation_starters_used(self):
        conv_starters = ConversationStartersConfig(
            intro_text="Choose",
            starters=[ConversationStarter(title="Hello", text="Say hello")],
        )
        client = _make_starters_app(_make_app_config(conversation_starters=conv_starters))
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

        config = data["config"]
        assert config["properties"]["starter"]["description"] == "Choose"
        assert config["properties"]["starter"]["dial:widget"] == "buttons"
        assert len(config["properties"]["starter"]["oneOf"]) == 1
        assert config["properties"]["starter"]["oneOf"][0]["title"] == "Hello"

    def test_conversation_starters_takes_priority_over_deprecated(
        self, caplog: pytest.LogCaptureFixture
    ):
        conv_starters = ConversationStartersConfig(
            intro_text="New style",
            starters=[ConversationStarter(title="New", text="new")],
        )
        client = _make_starters_app(
            _make_app_config(starters=["Old"], conversation_starters=conv_starters)
        )

        with caplog.at_level(logging.WARNING, logger="quickapp.starters.starters_module"):
            response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

        # New-style config is used despite deprecated starters being set
        config = data["config"]
        assert config["properties"]["starter"]["description"] == "New style"
        assert config["properties"]["starter"]["dial:widget"] == "buttons"

        # Deprecation warning still emitted
        assert any("deprecated" in r.message.lower() for r in caplog.records)
