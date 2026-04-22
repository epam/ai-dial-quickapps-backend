import json
import logging
from io import StringIO
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup
from httpx import HTTPStatusError, RequestError
from injector import inject

from quickapp.common import TimedStageWrapper, ToolCallResult

logger = logging.getLogger(__name__)


@inject
class _RestApiStageWrapper(TimedStageWrapper):

    def _get_formatted_parameters(self, parameters: dict[str, Any]) -> str:
        return f"> ##### Request:\n```json\n{json.dumps(parameters, indent=4, default=self.__serialize)}\n```\n\n"

    def _build_debug_info_from_result(self, result: ToolCallResult) -> str:
        formatted_response = (
            result.content
            if not result.content_type or not result.content
            else self.__format_response(result)
        )
        return f"> ##### Response:\n{formatted_response}\n"

    def _build_debug_info_from_exception(self, exception: Exception) -> str:

        if isinstance(exception, HTTPStatusError):
            status_code = exception.response.status_code
            response_text = exception.response.text or "No response text available"
            return (
                f"> ##### Status Code:\n{status_code}\n"
                f"> ##### Response:\n```text\n{response_text}\n```"
            )

        if isinstance(exception, RequestError):
            error_message = (
                exception.args[0] if exception.args else "occurred while calling web API"
            )
            return f"> ##### Error:\n {exception.__class__.__name__} {error_message}\n"

        return "> ##### Exception:\nGeneral exception occurred while calling web API\n"

    @staticmethod
    def __serialize(obj):
        from pydantic import BaseModel

        if isinstance(obj, BaseModel):
            return obj.model_dump()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        raise TypeError(f"Object of type {obj.__class__.__name__} isn't JSON serializable")

    @staticmethod
    def __format_response(result: ToolCallResult) -> str:
        main_type = result.content_type.split(';')[0].split('/')[1].lower()
        formatters = {
            'json': _RestApiStageWrapper.__format_json,
            'xml': _RestApiStageWrapper.__format_xml,
            'html': _RestApiStageWrapper.__format_html,
            'csv': _RestApiStageWrapper.__format_csv,
        }
        try:
            formatted = formatters.get(main_type, lambda x: x)(result.content)
            return formatted if 'csv' in main_type else f"```{main_type}\n{formatted}\n```"
        except Exception as e:
            logger.exception(e)
            return f"```{main_type}\n{result.content}\n```"

    @staticmethod
    def __format_json(content: str) -> str:
        return json.dumps(json.loads(content), indent=4)

    @staticmethod
    def __format_xml(content: str) -> str:
        from xml.dom.minidom import parseString

        return parseString(content).toprettyxml()

    @staticmethod
    def __format_html(content: str) -> str:
        result = BeautifulSoup(content, 'html.parser').prettify()
        if isinstance(result, bytes):
            return result.decode('utf-8')
        return result

    @staticmethod
    def __format_csv(content: str) -> str:
        df = pd.read_csv(StringIO(content))
        return df.to_markdown()
