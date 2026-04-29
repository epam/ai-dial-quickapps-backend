from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from quickapp.agent.agent_module import AgentModule


def test_provide_openai_client_forwards_bearer_to_default_headers():
    module = AgentModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    config = MagicMock()
    config.orchestrator.deployment.name = "orchestrator-model"

    with patch("quickapp.agent.agent_module.AsyncAzureOpenAI") as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_openai_client(
            dial_settings=dial_settings,
            api_key=SecretStr("test-key"),
            config=config,
            forwarded_headers={"X-Request-Id": "req-1"},
            bearer=SecretStr("incoming-token"),
        )

    assert openai_client.call_args.kwargs["default_headers"] == {
        "X-Request-Id": "req-1",
        "Authorization": "Bearer incoming-token",
    }


def test_provide_openai_client_handles_missing_bearer_without_authorization_header():
    module = AgentModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    config = MagicMock()
    config.orchestrator.deployment.name = "orchestrator-model"

    with patch("quickapp.agent.agent_module.AsyncAzureOpenAI") as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_openai_client(
            dial_settings=dial_settings,
            api_key=SecretStr("test-key"),
            config=config,
            forwarded_headers={"X-Request-Id": "req-1"},
            bearer=None,
        )

    assert openai_client.call_args.kwargs["default_headers"] == {"X-Request-Id": "req-1"}

