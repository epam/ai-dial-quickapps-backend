import logging
from typing import Any

import httpx
from pydantic import SecretStr

from quickapp.internal_tooling.py_interpreter_tooling._exceptions import (
    _PyInterpreterSessionError,
    _PyInterpreterTimeOutError,
    _PyInterpreterWrongRequestStateError,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.common import PyInterpreterSession
from quickapp.internal_tooling.py_interpreter_tooling.model.request import (
    CodeExecutionRequest,
    InputFileTransferDto,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.response import (
    CodeExecutionResponse,
    File,
    LoadedFiles,
)

logger = logging.getLogger(__name__)


class _PyInterpreterClient:
    """Client for interacting with the code Py Interpreter API."""

    _BASE_PATH = "/v1/ops/code_interpreter"

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={'Api-Key': self.api_key.get_secret_value()},
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._client:
            await self._client.aclose()

    async def _validate_client(self):
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."

    async def _make_post_request(self, path: str, json: dict[str, Any]) -> httpx.Response:
        if not self._client:
            raise ValueError("No client present in the PyInterpreterClient")
        try:
            return await self._client.post(url=path, json=json)
        except httpx.TimeoutException:
            raise _PyInterpreterTimeOutError(
                "Unable to execute code. Executions is taking too long time!"
            )

    async def _make_post(self, path: str, json: dict[str, Any]) -> httpx.Response:
        response = await self._make_post_request(path=path, json=json)
        if response.status_code == 400:
            raise _PyInterpreterWrongRequestStateError(
                f"Something wrong with state passed to Python Code Interpreter. Details: {response.content!r}"
            )
        elif response.status_code == 401:
            raise _PyInterpreterWrongRequestStateError(
                f"Something wrong with the user API key while connecting to Python Code Interpreter. Details: {response.content!r}"
            )
        elif response.status_code == 404:
            raise _PyInterpreterSessionError(
                "Python Code Interpreter session has been closed. Open a new session to work with Python Code Interpreter."
            )
        elif response.status_code == 429:
            raise _PyInterpreterSessionError(
                f"User has opened too many sessions in the Python Code Interpreter. Ask user to wait 5-10 minutes "
                f"(during this time some of sessions will be closed) and get back with the question. Details: {response.content!r}"
            )

        response.raise_for_status()

        if not response.content:
            raise ValueError("Empty response received")

        return response

    async def check_session_opened(self, request: PyInterpreterSession) -> bool:
        if not request.sessionId:
            return False

        await self._validate_client()
        await self._make_post(path=f"{self._BASE_PATH}/get_session", json=request.model_dump())
        return True

    async def open_session(self) -> PyInterpreterSession:
        await self._validate_client()

        response = await self._make_post(
            path=f"{self._BASE_PATH}/open_session", json=PyInterpreterSession().model_dump()
        )

        return PyInterpreterSession.model_validate(response.json())

    async def close_session(self, request: PyInterpreterSession):
        await self._validate_client()
        try:
            await self._make_post(
                path=f"{self._BASE_PATH}/close_session", json=request.model_dump()
            )
        except _PyInterpreterSessionError:
            # If session is already closed, we ignore the error to make the close_session idempotent
            logger.warning(
                "Trying to close an already closed session. Ignoring the error.", exc_info=True
            )
        logger.debug("PyInterpreter session closed")

    async def execute_code(self, request: CodeExecutionRequest) -> CodeExecutionResponse:
        await self._validate_client()

        response = await self._make_post(
            path=f"{self._BASE_PATH}/execute_code", json=request.model_dump()
        )

        return CodeExecutionResponse.model_validate(response.json())

    async def list_files(self, request: PyInterpreterSession) -> LoadedFiles:
        await self._validate_client()

        response = await self._make_post(
            path=f"{self._BASE_PATH}/list_files", json=request.model_dump()
        )

        return LoadedFiles.model_validate(response.json())

    async def transfer_input_file(self, request: InputFileTransferDto) -> File:
        await self._validate_client()

        response = await self._make_post(
            path=f"{self._BASE_PATH}/transfer_input_file", json=request.model_dump()
        )

        return File.model_validate(response.json())
