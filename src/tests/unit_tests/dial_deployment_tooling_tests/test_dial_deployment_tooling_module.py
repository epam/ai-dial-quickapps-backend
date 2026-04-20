from unittest.mock import MagicMock

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
    )

    expected = openai.Timeout(connect=5.0, read=42.0, write=42.0, pool=42.0)
    assert client.timeout == expected
    resolver.resolve.assert_called_once()
