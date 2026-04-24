from unittest.mock import MagicMock, patch

import openai
from pydantic import SecretStr

from quickapp.dial_deployment_tooling.dial_deployment_tooling_module import (
    DialDeploymentToolingModule,
)
from tests.unit_tests.common.common import noop_timeout_resolver


def test_provide_deployment_openai_client_applies_resolved_timeout():
    module = DialDeploymentToolingModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    api_key = SecretStr("test-key")
    resolver = noop_timeout_resolver(value=42.0)

    client = module.provide_deployment_openai_client(
        dial_settings=dial_settings,
        api_key=api_key,
        forwarded_headers=None,
        timeout_resolver=resolver,
        bearer=None,
    )

    expected = openai.Timeout(connect=5.0, read=42.0, write=42.0, pool=42.0)
    assert client.timeout == expected
    resolver.resolve.assert_called_once()


def test_provide_deployment_openai_client_forwards_bearer_to_default_headers():
    module = DialDeploymentToolingModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    api_key = SecretStr("test-key")
    resolver = noop_timeout_resolver(value=42.0)

    with patch(
        "quickapp.dial_deployment_tooling.dial_deployment_tooling_module.AsyncAzureOpenAI"
    ) as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_deployment_openai_client(
            dial_settings=dial_settings,
            api_key=api_key,
            forwarded_headers={"X-Request-Id": "req-1"},
            timeout_resolver=resolver,
            bearer=SecretStr("incoming-token"),
        )

    expected_timeout = openai.Timeout(connect=5.0, read=42.0, write=42.0, pool=42.0)
    assert openai_client.call_args.kwargs["default_headers"] == {
        "X-Request-Id": "req-1",
        "Authorization": "Bearer incoming-token",
    }
    assert openai_client.call_args.kwargs["timeout"] == expected_timeout
    resolver.resolve.assert_called_once()


def test_provide_deployment_openai_client_keeps_forwarded_authorization_header():
    module = DialDeploymentToolingModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    api_key = SecretStr("test-key")

    with patch(
        "quickapp.dial_deployment_tooling.dial_deployment_tooling_module.AsyncAzureOpenAI"
    ) as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_deployment_openai_client(
            dial_settings=dial_settings,
            api_key=api_key,
            forwarded_headers={"Authorization": "Bearer forwarded-token"},
            timeout_resolver=noop_timeout_resolver(),
            bearer=SecretStr("incoming-token"),
        )

    assert openai_client.call_args.kwargs["default_headers"]["Authorization"] == (
        "Bearer forwarded-token"
    )


def test_provide_deployment_openai_client_handles_missing_bearer_without_authorization_header():
    module = DialDeploymentToolingModule()
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    api_key = SecretStr("test-key")

    with patch(
        "quickapp.dial_deployment_tooling.dial_deployment_tooling_module.AsyncAzureOpenAI"
    ) as openai_client:
        openai_client.return_value = MagicMock()

        module.provide_deployment_openai_client(
            dial_settings=dial_settings,
            api_key=api_key,
            forwarded_headers={"X-Request-Id": "req-1"},
            timeout_resolver=noop_timeout_resolver(),
            bearer=None,
        )

    assert openai_client.call_args.kwargs["default_headers"] == {"X-Request-Id": "req-1"}
