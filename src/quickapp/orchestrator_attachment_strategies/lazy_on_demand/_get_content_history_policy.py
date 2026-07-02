import json

from aidial_sdk.chat_completion import Role

from quickapp.common.abstract.tool_execution_history_policy import ToolExecutionHistoryPolicy
from quickapp.common.attachment_processing_utils import normalize_attachment_url_argument
from quickapp.common.file_reference_pattern import FILE_PATTERN, to_file_url_reference
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME


def _parse_function_arguments(function: dict[str, object]) -> dict[str, object] | None:
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return None
    try:
        data = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _model_facing_attachment_url(raw: str) -> str:
    """Return a ``file:url::...`` reference suitable for ``attachment_url`` tool args."""
    value = raw.strip()
    if FILE_PATTERN.match(value):
        return value
    return to_file_url_reference(normalize_attachment_url_argument(value))


def _url_from_tool_content_json(content: str) -> str | None:
    try:
        data = json.loads(content.split("\n", 1)[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    url = data.get("url")
    return url if isinstance(url, str) and url.strip() else None


def _collect_attachment_urls(
    *,
    tool_call_id: str,
    tool_call_arguments_by_id: dict[str, dict[str, object]],
    attachments: list[object],
    content: str,
) -> list[str]:
    urls: list[str] = []

    def _append(raw: str) -> None:
        ref = _model_facing_attachment_url(raw)
        if ref not in urls:
            urls.append(ref)

    parsed_args = tool_call_arguments_by_id.get(tool_call_id)
    if parsed_args is not None:
        attachment_url = parsed_args.get("attachment_url")
        if isinstance(attachment_url, str) and attachment_url.strip():
            return [_model_facing_attachment_url(attachment_url)]

    for item in attachments:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            _append(url)

    if not urls:
        payload_url = _url_from_tool_content_json(content)
        if payload_url is not None:
            _append(payload_url)

    return urls


def _build_attachment_removed_notice(attachment_urls: list[str]) -> str:
    tool_name = INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
    intro = (
        "The file attachment payload was removed from saved history to save context. "
        "The file is still available. "
    )
    if not attachment_urls:
        return (
            intro + f"When you need page-level or verbatim content, call {tool_name} again "
            "with the same attachment_url (do not ask the user to re-upload)."
        )

    if len(attachment_urls) == 1:
        args_json = json.dumps({"attachment_url": attachment_urls[0]}, ensure_ascii=False)
        return (
            intro + f"When you need page-level or verbatim content, call {tool_name} again with:\n"
            f"{args_json}\n"
            "Do not ask the user to re-upload."
        )

    examples = "\n".join(
        json.dumps({"attachment_url": url}, ensure_ascii=False) for url in attachment_urls
    )
    return (
        intro
        + f"When you need page-level or verbatim content, call {tool_name} again with one of:\n"
        f"{examples}\n"
        "Do not ask the user to re-upload."
    )


class _GetContentHistoryPolicy(ToolExecutionHistoryPolicy):
    """Strip ``custom_content.attachments`` from get_content TOOL messages.

    Once persisted, the bytes would otherwise re-surface on every subsequent
    request and undermine the lazy-load contract: a new turn should rely on
    list-tool metadata and call ``internal_attachments_get_content`` again only
    when the document is needed.

    The tool ``content`` gets an explicit notice appended so restored history tells
    the model to re-call ``internal_attachments_get_content`` with a concrete
    ``attachment_url`` reference.
    """

    def apply(self, history: list[dict[str, object]]) -> list[dict[str, object]]:
        tool_name_by_call_id: dict[str, str] = {}
        tool_call_arguments_by_id: dict[str, dict[str, object]] = {}
        for msg in history:
            if msg.get("role") != Role.ASSISTANT.value:
                continue
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = tool_call.get("id")
                function = tool_call.get("function")
                if not isinstance(tool_call_id, str) or not isinstance(function, dict):
                    continue
                name = function.get("name")
                if name != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME:
                    continue
                tool_name_by_call_id[tool_call_id] = name
                parsed_args = _parse_function_arguments(function)
                if parsed_args is not None:
                    tool_call_arguments_by_id[tool_call_id] = parsed_args

        for msg in history:
            if msg.get("role") != Role.TOOL.value:
                continue
            tool_call_id = msg.get("tool_call_id")
            if not isinstance(tool_call_id, str):
                continue
            if tool_name_by_call_id.get(tool_call_id) != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME:
                continue

            custom_content = msg.get("custom_content")
            if not isinstance(custom_content, dict):
                continue

            attachments = custom_content.get("attachments")
            if isinstance(attachments, list) and attachments:
                content = msg.get("content")
                if content is None:
                    content = ""
                elif not isinstance(content, str):
                    content = str(content)
                attachment_urls = _collect_attachment_urls(
                    tool_call_id=tool_call_id,
                    tool_call_arguments_by_id=tool_call_arguments_by_id,
                    attachments=attachments,
                    content=content,
                )
                msg["content"] = content + "\n" + _build_attachment_removed_notice(attachment_urls)

            custom_content.pop("attachments", None)
            if not custom_content:
                msg.pop("custom_content", None)

        return history
