"""Standalone runnable server for the error-injection sample model.

This is a *sample* DIAL application built directly on the installed ``aidial-sdk``. It is
meant to be registered in DIAL Core as a model and wired as the orchestrator deployment
of a QuickApp so that QuickApps' error-handling pipeline
(``_exception_message_resolver`` -> ``_quick_app_completion``) can be exercised
end-to-end.

The scenario registry lives in ``scenarios.py`` and the request handler in
``completion.py``. This module only assembles the ``DIALApp`` and runs uvicorn.

This module is NOT a pytest and must not run as part of ``make test``. Run it as a
standalone server -- see ``README.md``:

    poetry run python src/tests/sample_apps/error_injection_app/error_injection_app.py
"""

import logging

import uvicorn
from aidial_sdk import DIALApp
from completion import ErrorInjectionModel
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Deployment name this app registers under. Point a QuickApp's
# ``orchestrator.deployment.deployment_id`` at this (via a DIAL Core model that proxies
# to this server) to test the error resolver.
DEPLOYMENT_NAME = "error-injection-model"


class _ServerSettings(BaseSettings):
    """Runner configuration read from the environment."""

    model_config = SettingsConfigDict()

    host: str = Field(default="0.0.0.0", alias="ERROR_INJECTION_APP_HOST")
    port: int = Field(default=5002, alias="ERROR_INJECTION_APP_PORT")


def build_app() -> DIALApp:
    """Assemble the DIAL app with the error-injection deployment registered."""
    app = DIALApp(add_healthcheck=True)
    app.add_chat_completion(DEPLOYMENT_NAME, ErrorInjectionModel())
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = _ServerSettings()
    logger.info(
        "Starting error-injection model on %s:%d (deployment %r)",
        settings.host,
        settings.port,
        DEPLOYMENT_NAME,
    )
    uvicorn.run(build_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
