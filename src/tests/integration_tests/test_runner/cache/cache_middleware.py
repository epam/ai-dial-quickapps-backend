import asyncio
import gzip
import json
import logging
import warnings
from pathlib import Path
from typing import List
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Request, Response
from pydantic.dataclasses import dataclass
from pydantic import SecretStr
from tests.integration_tests.test_runner.cache.cache_request import CacheRequest
from tests.integration_tests.test_runner.cache.cache_response import CacheResponse
from tests.integration_tests.test_runner.config import TestConfig
from tests.integration_tests.test_runner.cache.llm_cache import LlmCache, get_cache_key

llm_cache = None

FAILURE_MESSAGE = (
    "There is no response found in cache, use environment variable REFRESH=True to update cache "
    "and commit to repository"
)

logger = logging.getLogger("__name__")

# Specify all models that should be not cached.
AGENT_MODELS = [
    "gpt-4.1-2025-04-14",
    "gpt-5-2025-08-07",
    "gpt-5-mini-2025-08-07",
    "gpt-5.2-2025-12-11",
    "claude-opus-4@20250514",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "us.anthropic.claude-3-7-sonnet-20250219-v1",
    "anthropic.claude-v4-5-sonnet-v1"
]


@dataclass
class CacheMiddlewareConfig:
    dial_core_url: str = "http://host.docker.internal:8090"
    dial_core_api_key: SecretStr = SecretStr("dial_api_key")
    base_path: Path = Path(__file__).parent.parent
    content_base_path: Path = Path(__file__).parent.parent.parent / "documentation"
    model: str = ""
    test_name: str = ""
    refresh: bool = False
    no_cache: bool = False


def _extract_host_port(url: str) -> str:
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    port = parsed_url.port
    if port is None:
        port = 80 if parsed_url.scheme == "http" else 443
    return f"{host}:{port}"


class CacheMiddlewareApp(FastAPI):
    llm_cache: LlmCache

    def __init__(self, app_config: CacheMiddlewareConfig):
        self.target_url = app_config.dial_core_url
        self.dial_core_host = _extract_host_port(app_config.dial_core_url)
        self.dial_core_api_key = app_config.dial_core_api_key
        self.test_name = app_config.test_name
        self.refresh = app_config.refresh
        self.no_cache = app_config.no_cache
        self.base_path = Path(app_config.base_path)
        self.content_base_path = app_config.content_base_path
        self.llm_cache = LlmCache(
            cache_path=self.base_path / 'cache' / app_config.model / app_config.test_name,
            enable_cache=True,
        )
        self.used_cache_responses = set()
        self._background_tasks: List[asyncio.Task] = []

        super().__init__()
        self.router = APIRouter()
        self.register_routes()

        self.add_event_handler("shutdown", self.close_resources)

        self.http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            timeout=600.0
        )

    def track_task(self, task: asyncio.Task):
        """Track a background task for cleanup"""
        self._background_tasks.append(task)

        # Remove task from list when it completes
        def _remove_task(t):
            if t in self._background_tasks:
                self._background_tasks.remove(t)

        task.add_done_callback(_remove_task)

    async def close_resources(self):
        """Close all async resources gracefully"""
        logger.debug("Closing CacheMiddlewareApp resources...")

        # Cancel any pending background tasks
        tasks = self._background_tasks.copy()
        for task in tasks:
            if not task.done():
                logger.debug(f"Cancelling task: {task.get_name()}")
                task.cancel()

        if tasks:
            try:
                # Wait for tasks to complete with timeout
                await asyncio.wait(tasks, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for tasks to cancel")
            except Exception as e:
                logger.warning(f"Error waiting for tasks: {e}")

        if not self.http_client.is_closed:
            try:
                # Check if event loop is still running before attempting to close
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    logger.debug("HTTP client close skipped - event loop is already closed")
                else:
                    await self.http_client.aclose()
                    logger.debug("HTTP client closed")

                    # Wait a bit for any cleanup tasks to complete
                    await asyncio.sleep(0.1)

            except RuntimeError as e:
                # Event loop may already be closing
                if "Event loop is closed" in str(e):
                    logger.debug("HTTP client close skipped - event loop is closing")
                else:
                    logger.warning(f"Error closing HTTP client: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error closing HTTP client: {e}")

        logger.debug("CacheMiddlewareApp resources closed")

    async def send_put(self, request: Request, request_body: bytes):
        logger.debug(
            f"Sending PUT request to real DIAL at {self.target_url}{request.url.path}, params: {request.query_params}"
        )
        response = await self.http_client.put(
            url=f"{self.target_url}{request.url.path}",
            params=request.query_params,
            content=request_body,
            headers=self._get_headers(request),
            timeout=600,
        )
        content = response.content
        headers = dict(response.headers)
        status = response.status_code
        return content, status, headers

    async def send_delete(self, request: Request):
        logger.debug(
            f"Sending DELETE request to real DIAL at {self.target_url}{request.url.path}, params: {request.query_params}"
        )
        response = await self.http_client.delete(
            url=f"{self.target_url}{request.url.path}",
            params=request.query_params,
            headers=self._get_headers(request),
            timeout=600,
        )
        content = response.content
        headers = dict(response.headers)
        status = response.status_code
        return content, status, headers

    async def send_post(self, request: Request, request_body: bytes):
        logger.debug(
            f"Sending POST request to real DIAL at {self.target_url}{request.url.path}, params: {request.query_params}"
        )
        response = await self.http_client.post(
            url=f"{self.target_url}{request.url.path}",
            params=request.query_params,
            content=request_body,
            headers=self._get_headers(request),
            timeout=600,
        )
        cache_request = CacheRequest.from_request_body(request_body)
        cache_response = CacheResponse.from_response(response, cache_request)
        return cache_response

    async def send_get(self, request: Request):

        logger.debug(
            f"Sending GET request to real DIAL at {self.target_url}{request.url.path}, params: {request.query_params}"
        )
        r = await self.http_client.get(
            url=f"{self.target_url}{request.url.path}",
            params=request.query_params,
            headers=self._get_headers(request),
            timeout=600,
        )
        content = r.content
        headers = dict(r.headers)
        status = r.status_code
        return content, status, headers

    async def handle_get(self, request: Request):
        logger.debug(f"Receive GET request to {request.url.path}")
        content, status_code, headers = await self.send_get(request)
        # Ensure content-length is correct
        if "content-encoding" in headers.keys() and "gzip" in headers["content-encoding"]:
            body = gzip.compress(content)
        else:
            body = content
        headers["content-length"] = str(len(body))
        return Response(
            content=body,
            status_code=status_code,
            headers=headers,
        )

    async def handle_post(self, request: Request) -> Response:
        body = await request.body()
        messages = json.loads(body).get("messages", [])
        if messages[0].get("role", "").lower() == "system" and messages[0].get("content", None):
            messages[0]["content"] = messages[0]["content"][:30]+"..."
        logger.info(f"Receive POST request to {request.url.path}:")
        logger.info(f"## messages: {messages}:")

        cache_response = None

        if self.no_cache:
            logger.debug("Tests are executed without cache. Proxying request directly to core.")
            cache_response = await self.send_post(request, body)
        else:
            for model in AGENT_MODELS:
                path_parts = request.url.path.split('/')
                if len(path_parts) >= 4 and path_parts[2] == "deployments":
                    actual_model = path_parts[3]
                    if actual_model == model:
                        logger.debug(
                            f"The model {actual_model} is in {AGENT_MODELS}. Proxying request directly to core."
                        )
                        cache_response = await self.send_post(request, body)
                        break

        if cache_response is None:
            cache_request = CacheRequest.from_request_body(body)
            cache_response = self.llm_cache.get_cache_response(cache_request)

            if cache_response is None:
                warnings.warn(TestConfig.WARNING_MESSAGE)
                if self.refresh:
                    logger.debug(f"No cache for POST request. Send to {self.target_url}{request.url.path}")
                    cache_response = await self.send_post(request, body)
                    if cache_response.status_code == 200:
                        self.llm_cache.store(cache_response)
                    else:
                        cache_response = None
                if cache_response is None:
                    pytest.fail(f"{FAILURE_MESSAGE}::{get_cache_key(cache_request)}::")
            else:
                self.used_cache_responses.add(cache_response)

        if (
            "content-encoding" in cache_response.headers.keys()
            and "gzip" in cache_response.headers["content-encoding"]
        ):
            body = gzip.compress(cache_response.get_body_bytes())
        else:
            body = cache_response.body

        return Response(
            content=body,
            status_code=cache_response.status_code,
            media_type=cache_response.headers.get("content-type"),
            headers=cache_response.headers,
        )

    async def handle_put(self, request: Request):
        logger.info(f"Receive PUT request to {request.url.path}")
        body = await request.body()
        content, status_code, headers = await self.send_put(request, body)
        # Ensure content-length is correct
        if "content-encoding" in headers.keys() and "gzip" in headers["content-encoding"]:
            body = gzip.compress(content)
        else:
            body = content
        headers["content-length"] = str(len(body))
        return Response(
            content=body,
            status_code=status_code,
            headers=headers,
        )

    async def handle_delete(self, request: Request):
        logger.info(f"Receive DELETE request to {request.url.path}")
        content, status_code, headers = await self.send_delete(request)
        # Ensure content-length is correct
        if "content-encoding" in headers.keys() and "gzip" in headers["content-encoding"]:
            body = gzip.compress(content)
        else:
            body = content
        headers["content-length"] = str(len(body))
        return Response(
            content=body,
            status_code=status_code,
            headers=headers,
        )

    def _get_headers(self, request):
        allowed_headers = ["accept-encoding", "accept", "connection", "content-type", "api-key"]
        headers = dict(
            (key, request.headers.get(key))
            for key in request.headers.keys()
            if key in allowed_headers
        )
        headers["host"] = self.dial_core_host
        headers["api-key"] = self.dial_core_api_key.get_secret_value()
        return headers

    def register_routes(self):
        @self.post("/openai/deployments/{path:path}")
        async def post(request: Request, path: str):
            return await self.handle_post(request)

        @self.get("/{path:path}")
        async def get(request: Request, path: str):
            return await self.handle_get(request)

        @self.put("/{path:path}")
        async def put(request: Request, path: str):
            return await self.handle_put(request)

        @self.delete("/{path:path}")
        async def delete(request: Request, path: str):
            return await self.handle_delete(request)

    def cleanup(self):
        if self.refresh and len(self.llm_cache.cache_responses) > len(self.used_cache_responses):
            self.llm_cache.cleanup(
                set(self.llm_cache.cache_responses).difference(self.used_cache_responses)
            )



