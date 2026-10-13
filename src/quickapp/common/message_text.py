from aidial_sdk.chat_completion import Message, MessageContentTextPart


def message_text(message: Message) -> str:
    """Return the message's text, joining text parts; ``""`` when there is no non-blank text."""
    content = message.content
    if content is None:
        return ""
    if isinstance(content, str):
        text = content
    else:
        text = "\n".join(part.text for part in content if isinstance(part, MessageContentTextPart))
    return text if text.strip() else ""
