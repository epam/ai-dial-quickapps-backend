import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def format_openai_message_pipe_tree(
    msg: Dict[str, Any],
    idx,
    model: Optional[str] = None,
    include_tools: bool = True,
    include_attachments: bool = True,
    include_stages: bool = True,
):
    """Produce a human-readable 'pipe-tree' log of OpenAI Chat messages.
    - Header: "{idx} {role} (model=...): {content_preview}"
    - Attachments: parsed from structured attachments or parsed from content lines
      like 'Attachment <name>, of type <mime>, url <url>, reference_url <ref>'.
    - Tools: assistant tool_calls (function name + args string, truncated).
    - Stages: optional, if present in message["stages"] or message["metadata"]["stages"].

    Args:
        msg: message dict as in Chat Completions.
        idx: index of a message.
        model: string to show in each header, if provided.
        include_tools: include assistant tool calls.
        include_attachments: include attachment lines.
        include_stages: include stage lines.

    Returns:
        Multiline string with the formatted log.
    """
    env_val = os.getenv("CHAT_MESSAGE_LOG_LEN")
    try:
        preview_len: int = int(env_val) if env_val is not None else -1
    except ValueError:
        preview_len = -1
    role = msg.get("role", "?")
    content_preview, was_truncated = _preview_text(
        _flatten_content(msg.get("content")), preview_len
    )
    header = f"{idx} {role}"
    if model:
        header += f" (model={model})"
    header += f": {content_preview}"
    if was_truncated:
        header += f" ({preview_len})"
    logger.info(header)

    # Attachments
    if include_attachments:
        atts = _extract_attachments(msg)
        if atts:
            logger.info("|--- attachments:")
            for i, att in enumerate(atts, start=1):
                name = att.get("name") or att.get("filename") or "-"
                mime = att.get("mime") or att.get("type") or "-"
                url = att.get("url")
                ref = att.get("reference_url") or att.get("ref_url")
                data_desc = None
                # Try to describe inline data (bytes/base64/opaque)
                data = att.get("data")
                if data is not None and not url:
                    if isinstance(data, (bytes, bytearray)):
                        data_desc = f"BYTES({len(data)})"
                    elif isinstance(data, str):
                        data_desc = f"STR({len(data)} chars)"
                    else:
                        data_desc = "DATA"
                # Compose one-liner
                parts = [f"[{i}] name={name}", f"type={mime}"]
                if url:
                    parts.append(f"url={url}")
                elif data_desc:
                    parts.append(f"data={data_desc}")
                if ref:
                    parts.append(f"ref_url={ref}")
                logger.info("|------ " + " ".join(parts))

        # Try to parse 'Attachment ...' lines embedded in content text
        inline_atts = _parse_attachments_from_text(_flatten_content(msg.get("content")))
        if inline_atts:
            # If we already had attachments, keep a single section; else create it.
            if not atts:
                logger.info("|--- attachments:")
            for i, att in enumerate(inline_atts, start=(len(atts) + 1) if atts else 1):
                name = att.get("name", "-")
                mime = att.get("mime", "-")
                url = att.get("url")
                ref = att.get("reference_url")
                parts = [f"[{i}] name={name}", f"type={mime}"]
                if url:
                    parts.append(f"url={url}")
                if ref:
                    parts.append(f"ref_url={ref}")
                logger.info("|------ " + " ".join(parts))

    # Stages (optional)
    if include_stages:
        stages = _extract_stages(msg)
        if stages:
            logger.info("|--- stages:")
            for i, st in enumerate(stages, start=1):
                title = st.get("title") or "-"
                cprev, trunc = _preview_text(_flatten_content(st.get("content")), preview_len)
                suffix = f" ({preview_len})" if trunc else ""
                logger.info(f"|------ [{i}] title={title} content={cprev}{suffix}")

    # Tool calls (assistant)
    if include_tools and role == "assistant":
        tool_lines = _extract_tool_previews(msg, preview_len)
        if tool_lines:
            logger.info("|--- tools:")
            for i, (fname, argprev, trunc) in enumerate(tool_lines, start=1):
                suffix = f" ({preview_len})" if trunc else ""
                logger.info(f"|------ [{i}] function={fname} args={argprev}{suffix}")


def _flatten_content(content: Any) -> str:
    """Handle str or list-of-parts content; return a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # If content is a list (e.g., [{'type':'text', 'text':'...'}, ...])
    if isinstance(content, list):
        chunks: List[str] = []
        for part in content:
            if isinstance(part, dict):  # Prefer text-like fields if present
                if "text" in part and isinstance(part["text"], str):
                    chunks.append(part["text"])
                elif "content" in part and isinstance(part["content"], str):
                    chunks.append(part["content"])
                elif "input_text" in part and isinstance(part["input_text"], str):
                    chunks.append(part["input_text"])
                # else ignore non-text parts for preview
        return "\n".join(chunks)
    return str(content)


def _preview_text(text: str, limit: int) -> Tuple[str, bool]:
    """Collapse whitespace and truncate to limit; return (preview, was_truncated)."""
    if not text:
        return "", False
    if limit < 0:
        return text, False
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed, False
    return collapsed[:limit].rstrip() + "...", True


def _extract_tool_previews(msg: Dict[str, Any], preview_len: int) -> List[Tuple[str, str, bool]]:
    """Return list of (function_name, args_preview, was_truncated) for assistant tool calls. Supports both 'tool_calls' and legacy 'function_call'."""
    previews: List[Tuple[str, str, bool]] = []
    tool_calls = msg.get("tool_calls") or []
    if isinstance(tool_calls, list) and tool_calls:
        for tc in tool_calls:
            f = tc.get("function") if isinstance(tc, dict) else None
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "-")
            args = f.get("arguments")
            if isinstance(args, (dict, list)):
                try:
                    args_str = json.dumps(args, ensure_ascii=False)
                except Exception:
                    args_str = str(args)
            elif isinstance(args, str):
                args_str = args
            else:
                args_str = ""
            argprev, trunc = _preview_text(args_str, preview_len)
            previews.append((name, argprev, trunc))
    return previews


def _extract_attachments(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Try to collect structured attachments from common locations: - msg["attachments"] - msg["custom_content"]["attachments"] - msg["metadata"]["attachments"]
    Returns a normalized list with keys: name, mime/type, url, reference_url, data (optional)."""
    out: List[Dict[str, Any]] = []
    sources = [
        msg.get("attachments"),
        (msg.get("custom_content") or {}).get("attachments"),
        (msg.get("metadata") or {}).get("attachments"),
    ]
    for src in sources:
        if not isinstance(src, list):
            continue
        for a in src:
            if not isinstance(a, dict):
                continue
            norm: Dict[str, Any] = {
                "name": a.get("name") or a.get("filename"),
                "mime": a.get("mime") or a.get("type"),
                "type": a.get("mime"),
                "url": a.get("url") or a.get("download_url") or a.get("href"),
                "reference_url": a.get("reference_url") or a.get("ref_url"),
            }
            if "data" in a:
                norm["data"] = a.get("data")
            out.append(norm)
    return out


_ATTACHMENT_REGEX = re.compile(
    r"Attachment\s+([^,]+),\s+of\s+type\s+([^,]+),\s+url\s+(\S+),\s+reference_url\s+(\S+)",
    flags=re.IGNORECASE,
)


def _parse_attachments_from_text(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    for m in _ATTACHMENT_REGEX.finditer(text):
        name = m.group(1).strip()
        mime = m.group(2).strip()
        url = m.group(3).strip()
        ref = m.group(4).strip()
        if ref in ("None", "null", "NULL", "nil"):
            ref = None
        out.append({"name": name, "mime": mime, "url": url, "reference_url": ref})
    return out


def _extract_stages(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Try to find stages in msg["stages"] or msg["metadata"]["stages"] or msg["custom_content"]["stages"].
    Each stage is a dict with title and content (if available)."""
    candidates = [
        msg.get("stages"),
        (msg.get("metadata") or {}).get("stages"),
        (msg.get("custom_content") or {}).get("stages"),
    ]
    for c in candidates:
        if isinstance(c, list) and c:
            return c
    return []
