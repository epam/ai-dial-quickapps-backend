import asyncio
import inspect
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from aidial_client import AsyncDial, DialException, ResourceNotFoundError
from aidial_client.types.prompt import Prompt
from aidial_sdk.chat_completion import Message, Role
from pydantic import SecretStr
from starlette.testclient import TestClient

from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig, Context
from quickapp.config.logging_config import LoggingConfig
from quickapp.config.logging_settings import LoggingSettings
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.config.utils import bool_env_var
from quickapp.skills._frontmatter import (  # test harness: same parser as production skills
    parse_frontmatter,
)
from tests.integration_tests.conftest import FailureReason, TestStats, report_test_stats
from tests.integration_tests.test_runner.app_test_module import TestApp
from tests.integration_tests.test_runner.cache.cache_middleware import (
    CacheMiddlewareApp,
    CacheMiddlewareConfig,
)
from tests.integration_tests.test_runner.config import TestConfig, TestDialCoreConfig
from tests.integration_tests.test_runner.models import (
    Failure,
    SkillFileConfig,
    TestContextConfig,
    TstCase,
    check_multiple_alternatives,
)
from tests.integration_tests.test_runner.paths import SKILLS_DIR
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
INTEGRATION_PROMPTS_FOLDER = "quickapps-integration-tests"


def _create_request_headers(api_key: SecretStr) -> dict[str, str]:
    return {API_KEY_HEADER: api_key.get_secret_value(), CONTENT_TYPE_HEADER: "application/json"}

def _dial_relative_file_url(url: str) -> str:
    """Normalize a DIAL file URL to ``files/...`` form for :class:`FileContextConfig`."""
    s = str(url).strip()
    if "files/" in s:
        idx = s.index("files/")
        return s[idx:].split("?", 1)[0].rstrip("/")
    return s


def create_request_headers(
        api_key: SecretStr, app_config: ApplicationConfig | None = None
) -> dict[str, str]:
    headers = _create_request_headers(api_key)
    if app_config:
        headers.update(
            {
                "X-DIAL-APPLICATION-PROPERTIES": app_config.model_dump_json(),
                "X-DIAL-APPLICATION-ID": TestDialCoreConfig.APP_DEPLOYMENT_V2_NAME,
            }
        )
    return headers


class TestRunner:
    @staticmethod
    def _resolve_path(path: str | Path, default_parent: Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        if candidate.parts and candidate.parts[0] == default_parent.name:
            return default_parent.parent / candidate
        return default_parent / candidate

    @staticmethod
    def _sanitize_path_segment(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()

    @staticmethod
    async def start_server(refresh: bool, test_name: str, port: int, model: str, no_cache: bool):
        logger.debug("Starting middleware server...")
        url = TestDialCoreConfig.REMOTE_DIAL_URL
        logger.debug(f"Remote dial url:{url}")
        config_data = {
            "dial_core_url": TestDialCoreConfig.REMOTE_DIAL_URL,
            "dial_core_api_key": TestDialCoreConfig.REMOTE_DIAL_API_KEY,
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
    async def _search_file(dial_client: AsyncDial, bucket: str, filename: str) -> str | None:
        """BFS over the bucket tree looking for a file by name. Returns its URL or None."""

        folders_to_visit = [f"files/{bucket}"]
        for folder in folders_to_visit:
            # Absolute URL preserves the trailing slash that DIAL Core requires
            # to distinguish a folder-listing request from a file-metadata request.
            folder_url = f"{dial_client.api_url}metadata/{folder}/"
            metadata = await dial_client.metadata.get("files", folder_url)
            for item in metadata.items or []:
                if item.node_type == "FOLDER":
                    folders_to_visit.append(f"{folder}/{item.name}")
                if item.name == filename:
                    return item.url
        return None

    @staticmethod
    async def get_attachment_url(dial_url: str, headers: dict[str, str], attachment: Path) -> str:
        api_key = headers.get(API_KEY_HEADER)
        dial_client = AsyncDial(api_key=api_key, base_url=dial_url)

        bucket_resp = await dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket

        url = await TestRunner._search_file(dial_client, bucket, attachment.name)

        if url is None:
            with open(attachment.absolute(), "rb") as file:
                file_bytes = file.read()
            file_mime = mimetypes.guess_type(attachment.name)[0]
            file_metadata = await dial_client.files.upload(
                f"files/{bucket}/{attachment.name}",
                file=(attachment.name, file_bytes, file_mime),
            )
            url = file_metadata.url

        return url

    @staticmethod
    async def upload_dial_prompt_skill(
        dial_url: str,
        headers: dict[str, str],
        skill_file: Path,
    ) -> str:
        api_key = headers.get(API_KEY_HEADER)
        dial_client = AsyncDial(api_key=api_key, base_url=dial_url)

        bucket_resp = await dial_client.bucket.get_raw()
        bucket = bucket_resp.appdata or bucket_resp.bucket

        skill_content = skill_file.read_text(encoding="utf-8")
        parsed_skill = parse_frontmatter(skill_content, str(skill_file))
        parsed_name = parsed_skill.metadata.name
        prompt_name = TestRunner._sanitize_path_segment(parsed_name)
        prompt_folder = f"{INTEGRATION_PROMPTS_FOLDER}/"
        prompt_url = f"prompts/{bucket}/{INTEGRATION_PROMPTS_FOLDER}/{prompt_name}"

        try:
            existing_prompt = await dial_client.prompts.get(prompt_url)
            if existing_prompt.content == skill_content:
                logger.info("Reusing existing dial-prompt skill: %s", prompt_url)
                return prompt_url
        except ResourceNotFoundError:
            pass
        except DialException as exc:
            logger.warning(
                "Failed to fetch existing skill before upload (%s), proceeding with upload: %s",
                exc,
                prompt_url,
            )

        prompt = Prompt(
            id=prompt_name,
            name=prompt_name,
            folder_id=prompt_folder,
            content=skill_content,
        )

        try:
            await dial_client.prompts.save(prompt_url, prompt)
            logger.info("Uploaded dial-prompt skill: %s", prompt_url)
            return prompt_url
        except Exception as e:
            raise RuntimeError(
                f"Failed to upload dial-prompt skill to DIAL for {skill_file}"
            ) from e

    @staticmethod
    def _resolve_skill_path(skill: str | Path | SkillFileConfig) -> Path:
        if isinstance(skill, SkillFileConfig):
            skill_path_value: str | Path = skill.path
        else:
            skill_path_value = skill

        skill_path_raw = Path(skill_path_value)
        if skill_path_raw.parts and skill_path_raw.parts[0] == "skills":
            skill_path = SKILLS_DIR / Path(*skill_path_raw.parts[1:])
        else:
            skill_path = TestRunner._resolve_path(skill_path_value, SKILLS_DIR)
        if skill_path.suffix == "":
            skill_path = skill_path.with_suffix(".md")
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")
        return skill_path

    @staticmethod
    def resolve_skill_files(
        skills: str | Path | SkillFileConfig | list[str | Path | SkillFileConfig] | None,
    ) -> list[Path]:
        if skills is None:
            return []
        if isinstance(skills, list):
            return [TestRunner._resolve_skill_path(skill) for skill in skills]
        return [TestRunner._resolve_skill_path(skills)]

    @staticmethod
    def normalize_context_configs(
        contexts: list[str | Path | TestContextConfig] | None,
        test_file_dir: Path,
    ) -> list[TestContextConfig]:
        if not contexts:
            return []
        normalized: list[TestContextConfig] = []

        for context in contexts:
            if isinstance(context, TestContextConfig):
                raw_path: str | Path = context.path
                description = context.description
            else:
                raw_path = context
                description = None

            resolved_path = TestRunner._resolve_path(raw_path, test_file_dir)
            if not resolved_path.exists():
                raise FileNotFoundError(f"Context file not found: {resolved_path}")

            normalized.append(TestContextConfig(path=resolved_path, description=description))
        return normalized

    @staticmethod
    async def resolve_application_contexts(
        dial_url: str,
        headers: dict[str, str],
        contexts: list[TestContextConfig],
    ) -> list[FileContextConfig]:
        app_contexts: list[FileContextConfig] = []
        for context in contexts:
            url = await TestRunner.get_attachment_url(
                dial_url=dial_url, headers=headers, attachment=context.path
            )
            app_contexts.append(FileContextConfig(url=url, description=context.description))
        return app_contexts

    @staticmethod
    async def execute_test_case(
        client: TestClient, test_case: TstCase, ts: TestStats, app_config: ApplicationConfig
    ) -> list[Failure]:
        messages = []
        all_failures = []
        headers = create_request_headers(
            api_key=TestDialCoreConfig.REMOTE_DIAL_API_KEY_SECRET, app_config=app_config
        )

        for i, test_message_data in enumerate(test_case.messages):
            message = {"role": "user", "content": test_message_data.user_message}

            if test_message_data.attachments:
                attachment_objects = []
                for attachment in test_message_data.attachments:
                    url = await TestRunner.get_attachment_url(
                        TestDialCoreConfig.REMOTE_DIAL_URL, headers, attachment
                    )
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

            # Add tool_choice if specified in test case
            if test_case.tool_choice is not None:
                request_payload["tool_choice"] = test_case.tool_choice
                logger.debug(f"Using tool_choice: {test_case.tool_choice}")

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
                        Failure(actual=response.status_code, expected=200, comment="Status code"),
                        Failure(actual=response.text, expected=None, comment="Content"),
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
                        actual=response_message.role,
                        expected=Role.ASSISTANT,
                        comment="Message role differs from expected",
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
            if response_message.custom_content and hasattr(
                response_message.custom_content, "state"
            ):
                state = response_message.custom_content.state
            logger.debug(f"state:{state}")
            all_failures.extend(
                ResponseValidator.check_tool_calls(state, test_message_data.tool_calls, ts)
            )
            attachments = (
                getattr(response_message.custom_content, "attachments", None)
                if response_message.custom_content
                else None
            )
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
    def collect_warnings(recwarn, ts: TestStats) -> list[Failure]:
        failures = []
        specific_warnings = [
            w for w in recwarn.list if TestConfig.WARNING_MESSAGE in str(w.message)
        ]
        if specific_warnings:
            ts.increment_failure(FailureReason.LLM_CACHE_MISSING)
            failures.append(Failure(actual="", expected="", comment=TestConfig.FAILURE_MESSAGE))
        return failures

    @staticmethod
    def check_test_outcome(failures: list[Failure]):
        if failures:
            error_message = "\n".join(map(str, failures))
            pytest.fail(f"Test failed with the following errors:\n{error_message}")


async def execute_single_test_run(
    client: TestClient,
    test_case: TstCase,
    ts: TestStats,
    recwarn,
    func,
    app_config: ApplicationConfig,
    *args,
    **kwargs,
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
    model: str = None,
    models_applicable_for_test: list[str] | None = None,
    refresh: bool = None,
    config_file_set: str = "e2e",
    runs: int = 3,
    no_cache: bool = False,
    skills: str | Path | SkillFileConfig | list[str | Path | SkillFileConfig] | None = None,
    application_context_files: list[str | Path | TestContextConfig] | None = None,
    include_rest_toolset: bool = False,
    attachment_strategy: LazyOnDemandAttachmentStrategy | None = None,
):
    if refresh is None:
        refresh = bool_env_var("REFRESH", default=False)

    _application_context_files = application_context_files
    _include_rest_toolset = include_rest_toolset
    _attachment_strategy = attachment_strategy

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
                if (
                    models_applicable_for_test is None
                    or len(models_applicable_for_test) == 0
                    or cli_model in models_applicable_for_test
                ):
                    model_to_use = cli_model
                    logger.debug(f"Using model from CLI option: {model_to_use}")
                else:
                    logger.debug(
                        f"Model '{cli_model}' is not in the applicable models list: {models_applicable_for_test}"
                    )
                    pytest.skip(f"Model '{cli_model}' is not applicable for this test")
            else:
                logger.debug("No model specified")
                pytest.fail("No model specified for test")

            # Run the test multiple times according to the runs parameter
            ts = TestStats(name=f"{test_name}[{model_to_use}]", passed=0, failed=0)
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
            contexts: list[FileContextConfig] = []
            if _application_context_files:
                await prepare_contexts(contexts)

            tool_sets = TestConfig.load_tools_config(unique_port, config_file_set, include_rest_toolset=_include_rest_toolset)
            app_config: ApplicationConfig = TestConfig.create_app_configuration(
                toolsets=tool_sets, model=execution_model,                contexts=contexts,
                attachment_strategy=_attachment_strategy,
            )

            app = TestApp.get_app(port=unique_port)
            client = TestClient(app)
            headers = create_request_headers(TestDialCoreConfig.REMOTE_DIAL_API_KEY_SECRET)

            skill_urls: list[str] = []
            for skill_file in TestRunner.resolve_skill_files(skills):
                skill_urls.append(
                    await TestRunner.upload_dial_prompt_skill(
                        dial_url=TestDialCoreConfig.REMOTE_DIAL_URL,
                        headers=headers,
                        skill_file=skill_file,
                    )
                )

            if hasattr(request.node, "path"):
                test_file_path = Path(str(request.node.path))
            else:
                test_file_path = Path(str(request.node.fspath))
            test_file_dir = test_file_path.parent
            normalized_contexts = TestRunner.normalize_context_configs(
                contexts, test_file_dir=test_file_dir
            )
            app_contexts = await TestRunner.resolve_application_contexts(
                dial_url=TestDialCoreConfig.REMOTE_DIAL_URL,
                headers=headers,
                contexts=normalized_contexts,
            )

            app_config: ApplicationConfig = TestConfig.create_app_configuration(
                toolsets=tool_sets,
                model=execution_model,
                skill_urls=skill_urls or None,
                contexts=app_contexts,
            )

            # Combine CLI flag with decorator parameter - CLI takes precedence
            cli_no_cache = bool(request.config.getoption("--no-cache", default=False))
            effective_no_cache = cli_no_cache or no_cache

            task, server, middleware = await TestRunner.start_server(
                model=execution_model,
                test_name=test_name,
                refresh=refresh,
                port=unique_port,
                no_cache=effective_no_cache,
            )
            try:
                run_failures, test_result = await execute_single_test_run(
                    client, test_case, test_stats, recwarn, func, app_config, *args, **kwargs
                )
                if len(run_failures) > 0:
                    test_stats.failed += 1
                    run_failures_with_index = [
                        Failure(
                            actual=f"{test_stats.name}[{run_index + 1}]: {failure.actual}",
                            expected=failure.expected,
                            comment=failure.comment,
                        )
                        for failure in run_failures
                    ]
                    return run_failures_with_index
                test_stats.passed += 1
                return []

            finally:
                await TestRunner.stop_server(server, middleware)
                # TestClient is synchronous and doesn't need async close
                # Don't shutdown async generators while loop is running

        async def prepare_contexts(contexts: list[Context]):
            upload_headers = {
                API_KEY_HEADER: TestDialCoreConfig.REMOTE_DIAL_API_KEY,
                CONTENT_TYPE_HEADER: "application/json",
            }
            for path in _application_context_files:
                raw_url = await TestRunner.get_attachment_url(
                    TestDialCoreConfig.REMOTE_DIAL_URL, upload_headers, path
                )
                contexts.append(
                    FileContextConfig(
                        url=_dial_relative_file_url(raw_url),
                        description=f"integration fixture: {path.name}",
                    )
                )

        return wrapper

    return decorator
