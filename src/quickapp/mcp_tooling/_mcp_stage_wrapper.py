import json
import logging
from typing import Any

from injector import inject
from pydantic import BaseModel

from quickapp.common import TimedStageWrapper, ToolCallResult
from quickapp.common.response_formatter import ResponseFormatter
from quickapp.common.utils import fenced_code_block

logger = logging.getLogger(__name__)


@inject
class _MCPStageWrapper(TimedStageWrapper):

    def _get_display_name(self) -> str:
        return self.name

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        formatted_request = json.dumps(parameters, indent=4, default=self.__serialize)
        stage_result = ""
        if formatted_request and formatted_request != "{}":
            stage_result += f"> ##### Request:\n```json\n{formatted_request}\n```\n\n"
        return stage_result

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        formatted_response = (
            result.content
            if not result.content_type or not result.content
            else self.__format_response(result)
        )
        stage_result = ""
        if formatted_response:
            stage_result += f"> ##### Response:\n{formatted_response}\n"
        return stage_result

    def _build_debug_info_from_exception(self, exception: Exception) -> str:
        return f"> ##### Exception:\n{type(exception).__name__}: {exception}\n"

    @staticmethod
    def __serialize(obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        raise TypeError(f"Object of type {type(obj).__name__} isn't JSON serializable")

    @staticmethod
    def __format_response(result: ToolCallResult) -> str | None:
        formatters = {
            "json": ResponseFormatter.format_json,
            "xml": ResponseFormatter.format_xml,
            "html": ResponseFormatter.format_html,
            "csv": ResponseFormatter.format_csv,
        }

        main_type = result.content_type.split(";")[0].split("/")[1].lower()
        try:
            formatted = formatters.get(main_type, lambda x: x)(result.content)
            # csv is rendered as a Markdown table, not a fenced code block.
            if main_type == "csv":
                return formatted
            language = "" if main_type == "plain" else main_type
            return fenced_code_block(formatted, language)
        except Exception as e:
            logger.exception(str(e))
            return fenced_code_block(result.content, main_type)
