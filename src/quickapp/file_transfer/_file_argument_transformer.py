import logging
from typing import Any

from injector import inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.file_reference_pattern import FILE_PATTERN
from quickapp.file_transfer._file_loader_service import FileLoaderService
from quickapp.file_transfer._file_prefix_handlers import FilePrefixHandlers

logger = logging.getLogger(__name__)


@inject
class _FileArgumentTransformer(ToolArgumentTransformer):
    """Resolves file:{prefix}::{path} references in tool arguments."""

    def __init__(self, file_service: FileLoaderService):
        self.__file_service = file_service

    async def transform(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        logger.debug("Transforming tool arguments: keys=%s", list(kwargs.keys()))

        for key, value in list(kwargs.items()):
            if isinstance(value, str):
                resolved = await self._resolve_value_and_log(key, value)
                if resolved is not value:
                    kwargs[key] = resolved
            elif isinstance(value, list):
                logger.debug("Processing list argument %s with %d elements", key, len(value))
                resolved_list = [
                    await self._resolve_value_and_log(key, elem) if isinstance(elem, str) else elem
                    for elem in value
                ]
                kwargs[key] = resolved_list

        return kwargs

    async def _resolve_value_and_log(self, key: str, value: str) -> str:
        resolved_value = await self._resolve_value(key, value)
        if resolved_value is not value:
            logger.debug(
                "Argument %s resolved to new value (original: %s, resolved: %s)",
                key,
                value,
                resolved_value,
            )
        return resolved_value

    async def _resolve_value(self, key: str, value: str) -> str:
        m = FILE_PATTERN.match(value)
        if not m:
            return value

        detected_prefix = m.group("prefix").lower() if m.group("prefix") else None
        file_url_part = m.group("file_url")

        if detected_prefix == "base64":
            logger.debug(
                "Detected 'base64' prefix for key %s (url: %s) - placeholder handling",
                key,
                file_url_part,
            )
            return await FilePrefixHandlers.handle_base64(
                file_url_part, self.__file_service, parameter_name=key
            )
        elif detected_prefix == "data":
            logger.debug(
                "Detected 'data' prefix for key %s (url: %s) - placeholder handling",
                key,
                file_url_part,
            )
            return await FilePrefixHandlers.handle_data(
                file_url_part, self.__file_service, parameter_name=key
            )
        elif detected_prefix == "url":
            logger.debug(
                "Detected 'url' prefix for key %s (url: %s) - placeholder handling",
                key,
                file_url_part,
            )
            return file_url_part
        elif detected_prefix == "text":
            logger.debug(
                "Detected 'text' prefix for key %s (text: %s) - placeholder handling",
                key,
                file_url_part,
            )
            return await FilePrefixHandlers.handle_text(
                file_url_part, self.__file_service, parameter_name=key
            )
        else:
            logger.warning(
                "Detected file reference without prefix for key %s (value: %s)", key, value
            )
            raise InvalidToolCallParameterException(
                parameter_name=key,
                message="Missing required file prefix (data::, base64::, url::, text::)",
            )
