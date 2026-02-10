import asyncio
import inspect
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any, List

import pytest
import uvicorn
from aidial_sdk.chat_completion import Role
from aidial_sdk.chat_completion import Message
from starlette.testclient import TestClient

from pydantic import SecretStr

from quickapp.common.dial_core_client import DialCoreClient
from quickapp.config.application import ApplicationConfig
from quickapp.config.logging_config import LoggingConfig
from quickapp.config.logging_settings import LoggingSettings
from quickapp.config.utils import bool_env_var
from tests.integration_tests.conftest import FailureReason, TestStats, report_test_stats
from tests.integration_tests.test_runner.app_test_module import TestApp
from tests.integration_tests.test_runner.cache.cache_middleware import CacheMiddlewareApp, CacheMiddlewareConfig
from tests.integration_tests.test_runner.config import TestConfig, TestDialCoreConfig
from tests.integration_tests.test_runner.models import Failure, TstCase, check_multiple_alternatives
from tests.integration_tests.test_runner.utils.string_utils import extract_total_price
from tests.integration_tests.test_runner.validators import ResponseValidator

logging_config = LoggingConfig(settings=LoggingSettings())

logger = logging.getLogger(__name__)


def extract_usage(response_message):
    total_usage = 0

    if response_message.custom_content is None or response_message.custom_content.stages is None:
        return total_usage

    for stage in response_message.custom_content.stages:
        if stage.name == "Usage statistics":
            total_usage = float(extract_total_price(stage.content))
    return total_usage


API_KEY_HEADER = "Api-Key"
CONTENT_TYPE_HEADER = "Content-Type"


def create_request_headers(
        api_key: SecretStr, app_config: ApplicationConfig
) -> dict[str, str]:
    return {
        API_KEY_HEADER: api_key.get_secret_value(),
        CONTENT_TYPE_HEADER: "application/json",
        "X-DIAL-APPLICATION-PROPERTIES": app_config.model_dump_json(),
        "X-DIAL-APPLICATION-ID": TestDialCoreConfig.APP_DEPLOYMENT_V2_NAME,
    }


class TestRunner:
    @staticmethod
    async def start_server(refresh: bool, test_name: str, port: int, model: str, no_cache: bool):
        logger.debug("Starting middleware server...")
        url = TestDialCoreConfig.REMOTE_DIAL_URL
        logger.debug(f"Remote dial url:{url}")
        config_data = {
            "dial_core_url": TestDialCoreConfig.REMOTE_DIAL_URL,
            "dial_core_api_key": TestConfig.REMOTE_DIAL_API_KEY,
            "model": model,
            "test_name": test_name,
            "refresh": refresh,
            "no_cache": no_cache,
        }
        cache_middleware_app = CacheMiddlewareApp(app_config=CacheMiddlewareConfig(**config_data))

        config = uvicorn.Config(
            cache_middleware_app,
            host="0.0.0.0",
            port=port,
            log_level="debug",
        )
        server = uvicorn.Server(config)

        loop = asyncio.get_running_loop()
        task = loop.run_in_executor(None, server.run)

        await asyncio.sleep(1)  # Wait until server is up

        return task, server, cache_middleware_app

    @staticmethod
    async def stop_server(server, cache_middleware_app):
        # Signal server to shut down first
        server.should_exit = True
        logger.debug("Signaling server shutdown...")

        # Give server a moment to start shutting down
        await asyncio.sleep(0.5)

        # Then close app resources
        try:
            await cache_middleware_app.close_resources()
        except Exception as e:
            logger.warning(f"Error during resource cleanup: {e}")

        # Give more time for cleanup to complete
        await asyncio.sleep(1.5)

    @staticmethod
    async def get_attachment_url(dial_url: str, headers, attachment: Path):
        # Use DialCoreClient (httpx-based) directly.
        api_key = headers.get(API_KEY_HEADER)
        async with DialCoreClient(api_key, dial_url) as client:
            url = await client.search_file_on_core(attachment.name)
            if url is None:
                with open(attachment.absolute(), "rb") as file:
                    file_bytes = file.read()
                    file_mime = mimetypes.guess_type(attachment.name)[0]
                    metadata = await client.upload_bytes(
                        name=attachment.name, file_bytes=file_bytes, mime_type=file_mime
                    )
                    url = metadata["url"]
        return url

    @staticmethod
    async def execute_test_case(
        client: TestClient, test_case: TstCase, ts: TestStats, app_config: ApplicationConfig
    ) -> List[Failure]:
        messages = []
        all_failures = []
        headers = create_request_headers(api_key=TestConfig.REMOTE_DIAL_API_KEY, app_config=app_config)

        for i, test_message_data in enumerate(test_case.messages):
            message = {"role": "user", "content": test_message_data.user_message}

            if test_message_data.attachments:
                attachment_objects = []
                for attachment in test_message_data.attachments:
                    url = await TestRunner.get_attachment_url(TestDialCoreConfig.REMOTE_DIAL_URL, headers, attachment)
                    attachment_object = {
                        "type": mimetypes.guess_type(attachment.name)[0],
                        "title": attachment.name,
                        "url": url,
                    }
                    logger.info(f"Prepared attachment: {attachment_object}")
                    attachment_objects.append(attachment_object)

                message["custom_content"] = {"attachments": attachment_objects}
            messages.append(message)
            logger.debug(f"send {message} to {client.base_url}")

            # Prepare request payload
            request_payload = {
                "model": TestDialCoreConfig.APP_DEPLOYMENT_V2_NAME,
                "messages": messages,
            }

            # Add response_format if specified in test case
            if test_case.response_format:
                request_payload["response_format"] = test_case.response_format
                logger.debug(f"Using response_format: {test_case.response_format}")

            response = client.post(
                TestConfig.API_ENDPOINTS['CHAT_COMPLETIONS'],
                headers=headers,
                json=request_payload,
                timeout=100.0,
            )

            if response.status_code != 200:
                ts.increment_failure(FailureReason.HTTP_STATUS)
                all_failures.extend(
                    [
                        Failure(response.status_code, 200, "Status code"),
                        Failure(response.text, None, "Content"),
                    ]
                )
                break

            response_data = json.loads(response.text)
            messages.append(response_data["choices"][0]["message"])
            response_message = Message(**response_data["choices"][0]["message"])

            if response_message.role != Role.ASSISTANT:
                ts.increment_failure(FailureReason.ROLE)
                all_failures.append(
                    Failure(
                        response_message.role,
                        Role.ASSISTANT,
                        "Message role differs from expected",
                    )
                )
                break

            logger.info(f"content:{response_message.content}")

            # Validate response format if specified
            if test_case.response_format:
                format_failures = ResponseValidator.validate_json_schema_response(
                    response_message.content, test_case.response_format, ts
                )
                if format_failures:
                    ts.increment_failure(FailureReason.ANSWER)
                    all_failures.extend(format_failures)

            # Check message answer if expected
            if test_message_data.answer:
                failures = check_multiple_alternatives(
                    response_message.content,
                    test_message_data.answer,
                    "User message answer content similarity ",
                    test_case.similarity_threshold,
                )
                if failures:
                    ts.increment_failure(FailureReason.ANSWER)
                    all_failures.extend(failures)

            # Check tool calls and attachments
            state = None
            if response_message.custom_content and hasattr(response_message.custom_content, "state"):
                state = response_message.custom_content.state
            logger.debug(f"state:{state}")
            all_failures.extend(
                ResponseValidator.check_tool_calls(state, test_message_data.tool_calls, ts)
            )
            attachments = getattr(response_message.custom_content, "attachments", None) if response_message.custom_content else None
            all_failures.extend(
                ResponseValidator.check_attachments(
                    attachments,
                    test_message_data.attachment_checks,
                    ts,
                )
            )
            # update price:
            ts.price += extract_usage(response_message)

            if len(all_failures) > 0:
                failures_str = "\n".join(map(str, all_failures))
                logger.info(f"[{i}] Failures: \n{failures_str}")

        return all_failures

    @staticmethod
    def collect_warnings(recwarn, ts: TestStats) -> List[Failure]:
        failures = []
        specific_warnings = [
            w for w in recwarn.list if TestConfig.WARNING_MESSAGE in str(w.message)
        ]
        if specific_warnings:
            ts.increment_failure(FailureReason.LLM_CACHE_MISSING)
            failures.append(Failure("", "", TestConfig.FAILURE_MESSAGE))
        return failures

    @staticmethod
    def check_test_outcome(failures: List[Failure]):
        if failures:
            error_message = "\n".join(map(str, failures))
            pytest.fail(f"Test failed with the following errors:\n{error_message}")


async def execute_single_test_run(
    client: TestClient, test_case: TstCase, ts: TestStats, recwarn, func, app_config: ApplicationConfig, *args, **kwargs
) -> tuple[list[Failure], Any]:
    """Executes a single test run and returns failures."""
    run_failures = []
    if test_case:
    #     with patch('chat_v2.agents.chat_hub_agent.get_today') as mock_date:
    #         mock_date.return_value = test_case.mock_date
        run_failures.extend(await TestRunner.execute_test_case(client, test_case, ts, app_config))

    # Call the test itself, in most cases it would be empty
    if inspect.iscoroutinefunction(func):
        test_result = await func(client, *args, **kwargs)
    else:
        test_result = func(client, *args, **kwargs)

    # Collect warnings but don't fail yet
    run_failures.extend(TestRunner.collect_warnings(recwarn, ts))
    return run_failures, test_result


def e2e_test(
    test_case: TstCase = None,
    app_config_path: Path = None,
    model: str = None,
    models_applicable_for_test: List[str] = None,
    refresh: bool = None,
    config_file_set: str = "e2e",
    runs: int = 3,
    no_cache: bool = False,
):
    """
    Decorator for end-to-end tests.

    Args:
        no_cache: If True, bypass cache for this test. Can also be set globally via --no-cache CLI flag.
                  CLI flag takes precedence over decorator parameter.
    """

    if refresh is None:
        refresh = bool_env_var("REFRESH", default="false")

    def decorator(func):
        func = pytest.mark.filterwarnings(f"always:{TestConfig.WARNING_MESSAGE}")(func)

        @pytest.mark.asyncio
        async def wrapper(request, recwarn, unique_port, *args, **kwargs):
            # Collect all failures across all runs
            all_runs_failures = []
            test_result = None
            test_name = (
                f"{Path(request.node.parent.name).with_suffix('').name}/"
                f"{test_case.name if test_case else request.node.name}"
            )

            model_to_use: str
            if model:
                model_to_use = model
                logger.debug(f"Using model from parameter defined in test: {model_to_use}")
            elif request.config.getoption("--model"):
                cli_model = request.config.getoption("--model")
                if models_applicable_for_test is None or len(
                        models_applicable_for_test) == 0 or cli_model in models_applicable_for_test:
                    model_to_use = cli_model
                    logger.debug(f"Using model from CLI option: {model_to_use}")
                else:
                    logger.debug(
                        f"Model '{cli_model}' is not in the applicable models list: {models_applicable_for_test}")
                    pytest.skip(f"Model '{cli_model}' is not applicable for this test")
            else:
                logger.debug("No model specified")
                pytest.fail("No model specified for test")



               # Run the test multiple times according to the runs parameter
            ts = TestStats(f"{test_name}[{model_to_use}]", 0, 0)
            for run_index in range(runs):
                logger.info(f"Running test iteration {run_index + 1}/{runs}")
                failures = await prepare_and_execute_test(
                    args,
                    kwargs,
                    recwarn,
                    request,
                    unique_port,
                    execution_model=model_to_use,
                    test_name=test_name,
                    test_stats=ts,
                    run_index=run_index,
                )
                all_runs_failures.extend(failures)
            logger.info(ts)
            report_test_stats(request.config, ts)

            # After all runs/models are complete, check if any failures occurred
            TestRunner.check_test_outcome(all_runs_failures)

            return test_result

        async def prepare_and_execute_test(
            args,
            kwargs,
            recwarn,
            request,
            unique_port,
            execution_model,
            test_name,
            test_stats,
            run_index,
        ):
            tool_sets = TestConfig.load_tools_config(unique_port, config_file_set)
            app_config: ApplicationConfig = TestConfig.create_app_configuration(toolsets=tool_sets, model=execution_model)

            app = TestApp.get_app(port=unique_port)

            client = TestClient(app)

            # Combine CLI flag with decorator parameter - CLI takes precedence
            cli_no_cache = bool(request.config.getoption("--no-cache", default=False))
            effective_no_cache = cli_no_cache or no_cache

            task, server, middleware = await TestRunner.start_server(
                model=execution_model,
                test_name=test_name,
                refresh=refresh,
                port=unique_port,
                no_cache=effective_no_cache
            )
            try:
                run_failures, test_result = await execute_single_test_run(
                    client, test_case, test_stats, recwarn, func, app_config, *args, **kwargs
                )
                if len(run_failures) > 0:
                    test_stats.failed += 1
                    run_failures_with_index = [
                        Failure(
                            f"{test_stats.name}[{run_index+1}]: {failure.actual}",
                            failure.expected,
                            failure.comment,
                        )  # Using comment instead of message
                        for failure in run_failures
                    ]
                    return run_failures_with_index
                test_stats.passed += 1
                return []

            finally:
                await TestRunner.stop_server(server, middleware)
                # TestClient is synchronous and doesn't need async close
                # Don't shutdown async generators while loop is running

        return wrapper

    return decorator
