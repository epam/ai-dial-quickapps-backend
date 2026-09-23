import logging
from typing import Any

from aidial_sdk.chat_completion import Message
from pydantic import BaseModel

from quickapp.common.abstract.base_transformer import MessagesTransformer

logger = logging.getLogger(__name__)


def _extra_fields_exclude(value: object) -> dict[Any, Any] | None:
    """Build a ``model_dump`` exclude spec covering every undeclared field under ``value``.

    Mirrors the SDK's extra-field validation, which walks nested models, lists and dicts.
    """
    if isinstance(value, BaseModel):
        exclude: dict[Any, Any] = dict.fromkeys(value.model_extra or {}, True)
        for name in type(value).model_fields:
            if nested := _extra_fields_exclude(getattr(value, name)):
                exclude[name] = nested
        return exclude or None
    if isinstance(value, list):
        return {
            index: nested
            for index, item in enumerate(value)
            if (nested := _extra_fields_exclude(item))
        } or None
    if isinstance(value, dict):
        return {
            key: nested for key, item in value.items() if (nested := _extra_fields_exclude(item))
        } or None
    return None


class _ScrubExtraFieldsTransformer(MessagesTransformer):
    """Removes undeclared (extra) fields from the working message copy.

    The app accepts them (``allow_extra_request_fields``), but they must not leave
    QuickApps: SDK-based model adapters reject them with ``400`` (e.g.
    ``custom_content.annotations`` Chat stores from citation chunks), and forwarding
    ``custom_content.skills`` makes Core share the user's skill folders with the
    orchestrator deployment. Features that read extras (skill chips) read them from
    the request's own messages instead.

    Registered by the never-preview-gated ``AgentModule``. Messages carrying extras are
    copied, not edited: the working list shares objects with the request's own messages.
    """

    async def transform(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        scrubbed = 0
        for message in messages:
            exclude = _extra_fields_exclude(message)
            if exclude is None:
                result.append(message)
                continue
            result.append(type(message).model_validate(message.model_dump(exclude=exclude)))
            scrubbed += 1

        if scrubbed:
            logger.debug("Removed undeclared fields from %d message(s)", scrubbed)
        return result
