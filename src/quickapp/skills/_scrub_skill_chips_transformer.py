import logging

from aidial_sdk.chat_completion import Message

from quickapp.common.abstract.base_transformer import MessagesTransformer

logger = logging.getLogger(__name__)

SKILL_CHIPS_FIELD = "skills"
"""Name of the ``custom_content`` field a client uses to invoke a skill."""


class _ScrubSkillChipsTransformer(MessagesTransformer):
    """Removes ``custom_content.skills`` from the working message copy.

    Registered by the never-preview-gated ``SkillsModule``: neither the
    orchestrator LLM nor a DIAL deployment tool that forwards the conversation
    needs the field, and forwarding it makes Core share the user's skill folders
    with those deployments too — a leak that must not depend on the preview flag.

    Messages carrying the field are copied, not edited: the working list shares
    objects with the request's own messages.
    """

    async def transform(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        scrubbed = 0
        for message in messages:
            custom_content = message.custom_content
            if custom_content is None or SKILL_CHIPS_FIELD not in (
                custom_content.model_extra or {}
            ):
                result.append(message)
                continue
            clean_custom_content = custom_content.model_copy()
            delattr(clean_custom_content, SKILL_CHIPS_FIELD)
            result.append(message.model_copy(update={"custom_content": clean_custom_content}))
            scrubbed += 1

        if scrubbed:
            logger.debug("Removed skill chips from %d message(s)", scrubbed)
        return result
