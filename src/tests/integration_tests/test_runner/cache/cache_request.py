import json
import logging
from typing import List, Optional, Union, Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CacheRequest(BaseModel):
    system_message: Optional[str] = None
    model: str = ""
    temperature: Optional[float] = None
    user_message: list = []
    assistant_message: Optional[Union[str, List[Union[str, dict]]]] = None

    @classmethod
    def from_request_body(cls, body: bytes) -> "CacheRequest":
        """
        Parses the request body (JSON) and creates a CacheRequest object.
        Iterates through the messages list only once to populate user and assistant messages.
        Handles cases where system messages, user messages, or assistant messages might be missing.
        """
        try:
            data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format in request body")

        system_message = None
        user_message = []
        assistant_message = []

        if 'messages' in data:
            for message in data['messages']:
                role = message.get('role')
                content = message.get('content', '')
                if role == 'system' and system_message is None:
                    system_message = content
                elif role == 'user':
                    user_message.append(content)
                elif role == 'assistant':
                    if content is None:
                        # Workaround. need to investigate why content might be None
                        assistant_message.append("")
                    elif isinstance(content, list):
                        assistant_message.extend(content)
                    else:
                        assistant_message.append(content)

        model = data.get('model')
        temperature = data.get('temperature')

        logger.info("Assistant message: " + str(assistant_message))

        return cls(
            system_message=system_message,
            model=model or "",
            temperature=temperature,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    def __str__(self) -> str:
        """Return a string representation of the CacheRequest object."""
        return (
            f"CacheRequest(\n"
            f"  System Message: {self.system_message}\n"
            f"  Model: {self.model}\n"
            f"  Temperature: {self.temperature}\n"
            f"  User Messages: {self.user_message}\n"
            f"  Assistant Messages: {self.assistant_message}\n"
            f")"
        )
