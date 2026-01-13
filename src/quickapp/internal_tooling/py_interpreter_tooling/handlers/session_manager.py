from typing import Dict, Optional

from aidial_sdk.chat_completion import Message, Role
from injector import inject

from quickapp.internal_tooling.py_interpreter_tooling._constants import SESSION_ID_KEY
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
    _PyInterpreterSessionError,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.common import PyInterpreterSession


@inject
class SessionManager:
    """Manages Python interpreter sessions"""

    def __init__(self, client: _PyInterpreterClient, messages: list[Message]):
        self.__client: _PyInterpreterClient = client
        self.__messages: list[Message] = messages

    def get_session_id(self) -> str | None:
        """Retrieves the session ID from message history"""
        for msg in reversed(self.__messages):
            if msg.role == Role.ASSISTANT and msg.custom_content:
                state = msg.custom_content.state
                if isinstance(state, Dict) and state.get(SESSION_ID_KEY):
                    return state.get(SESSION_ID_KEY)

        return None

    async def ensure_valid_session(self, session_id: Optional[str], open_session: bool) -> str:
        """Ensures a valid session exists or creates a new one"""
        if not session_id:
            return await self._open_session()

        # Validate existing session
        try:
            await self.__client.check_session_opened(PyInterpreterSession(sessionId=session_id))
        except _PyInterpreterSessionError as e:
            if open_session:
                return await self._open_session()
            else:
                raise e

        # Session is opened and can be used
        return session_id

    async def _open_session(self) -> str:
        session: PyInterpreterSession = await self.__client.open_session()
        if session.sessionId:
            return session.sessionId
        raise ValueError(
            "After session opening in Python Code Interpreter the 'session_id' is None"
        )

    async def close_session(self, session_id: str):
        await self.__client.close_session(PyInterpreterSession(sessionId=session_id))
