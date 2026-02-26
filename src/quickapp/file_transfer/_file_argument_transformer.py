import logging
import re
from typing import Any

from injector import inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.file_transfer._file_prefix_handlers import FilePrefixHandlers

logger = logging.getLogger(__name__)

_FILE_PATTERN = re.compile(
    r"^/*file:(?:(?P<prefix>base64|url|text)::)?(?P<file_url>.+)$", re.IGNORECASE
)


@inject
class _FileArgumentTransformer(ToolArgumentTransformer):
    """Resolves file:{prefix}::{path} references in tool arguments."""

    def __init__(self, file_service: DialFileService):
        self.__file_service = file_service

    async def transform(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        for key, value in list(kwargs.items()):
            if not isinstance(value, str):
                continue

            m = _FILE_PATTERN.match(value)
            if not m:
                continue

            detected_prefix = m.group("prefix").lower() if m.group("prefix") else None
            file_url_part = m.group("file_url")

            if detected_prefix == "base64":
                logger.debug(
                    "Detected 'base64' prefix for key %s (url: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                kwargs[key] = await FilePrefixHandlers.handle_base64(
                    file_url_part, self.__file_service
                )
            elif detected_prefix == "url":
                logger.debug(
                    "Detected 'url' prefix for key %s (url: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                kwargs[key] = file_url_part
            elif detected_prefix == "text":
                logger.debug(
                    "Detected 'text' prefix for key %s (text: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                kwargs[key] = await FilePrefixHandlers.handle_text(
                    file_url_part, self.__file_service, parameter_name=key
                )
            else:
                logger.warning(
                    "Detected file reference without prefix for key %s (value: %s)", key, value
                )
                raise InvalidToolCallParameterException(
                    parameter_name=key,
                    message="Missing required file prefix (base64::, url::, text::)",
                )

        return kwargs
