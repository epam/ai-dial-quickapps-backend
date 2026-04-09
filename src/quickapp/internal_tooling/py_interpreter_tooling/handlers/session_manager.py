import logging

from aidial_sdk.chat_completion import Role
from injector import inject

from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.state_holder import StateHolder
from quickapp.internal_tooling.py_interpreter_tooling._constants import (
    PY_INTERPRETER_STATE_KEY,
    SESSION_ID_KEY,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
    _PyInterpreterSessionError,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.common import (
    PyInterpreterSession,
    PyInterpreterState,
)

logger = logging.getLogger(__name__)


@inject
class SessionManager:
    """Manages Python interpreter sessions"""

    def __init__(
        self, client: _PyInterpreterClient, messages_mixin: MessagesMixin, state_holder: StateHolder
    ):
        self.__client: _PyInterpreterClient = client
        self.__messages_mixin: MessagesMixin = messages_mixin
        self.__state_holder: StateHolder = state_holder
        self.__validated_session_id: str | None = None

    def get_session_id(self) -> str | None:
        """Retrieves the session ID, checking StateHolder first (within-request),
        then falling back to message history (across-request)."""
        # Fast path: StateHolder (already validated in this request)
        current_state = self.__state_holder.get_state()
        if raw := current_state.get(PY_INTERPRETER_STATE_KEY):
            return PyInterpreterState.model_validate(raw).session_id

        # Scan message history in a single pass for both new and legacy keys
        for msg in reversed(self.__messages_mixin.messages):
            if msg.role == Role.ASSISTANT and msg.custom_content:
                state = msg.custom_content.state
                if isinstance(state, dict):
                    if raw := state.get(PY_INTERPRETER_STATE_KEY):
                        return PyInterpreterState.model_validate(raw).session_id
                    if session_id := state.get(SESSION_ID_KEY):
                        return session_id

        return None

    async def ensure_valid_session(self, session_id: str | None) -> str:
        """Ensures a valid session exists or creates a new one"""
        if not session_id:
            return await self._open_session()

        # Skip network validation if already validated in this request
        if session_id == self.__validated_session_id:
            return session_id

        # Validate existing session
        try:
            await self.__client.check_session_opened(PyInterpreterSession(sessionId=session_id))
        except _PyInterpreterSessionError:
            logger.info("Session %s is no longer valid, opening a new one", session_id)
            return await self._open_session()

        # Session is opened and can be used
        self._persist_state(PyInterpreterState(session_id=session_id))
        self.__validated_session_id = session_id
        return session_id

    async def _open_session(self) -> str:
        session: PyInterpreterSession = await self.__client.open_session()
        if session.sessionId:
            self._persist_state(PyInterpreterState(session_id=session.sessionId))
            self.__validated_session_id = session.sessionId
            return session.sessionId
        raise ValueError(
            "After session opening in Python Code Interpreter the 'session_id' is None"
        )

    async def close_session(self, session_id: str):
        await self.__client.close_session(PyInterpreterSession(sessionId=session_id))
        self.__validated_session_id = None

    def _persist_state(self, interpreter_state: PyInterpreterState) -> None:
        self.__state_holder.add_state(
            PY_INTERPRETER_STATE_KEY, interpreter_state.model_dump(exclude_none=True)
        )
