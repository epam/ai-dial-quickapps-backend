import logging
from typing import Any

import httpx
from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject

from quickapp.common import CompletionResult, ForwardedHeaders, StagedBaseTool
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.utils import generate_attachment_filename, matches_type
from quickapp.config.tools.rest_api import RestApiTool
from quickapp.config.toolsets.rest_api import Authorization
from quickapp.dial_core_services.attachment_service import AttachmentService

from ._request_detail_builder import _RequestDetailsBuilder
from ._rest_api_stage_wrapper import _RestApiStageWrapper

logger = logging.getLogger(__name__)


@inject
class _RestApiTool(StagedBaseTool):

    def __init__(
        self,
        auth_info: Authorization,
        request_details_builder: _RequestDetailsBuilder,
        tool_config: RestApiTool,
        stage_wrapper_builder: AssistedBuilder[_RestApiStageWrapper],
        dial_attachment_service: AttachmentService,
        perf_timer: PerformanceTimer,
        forwarded_headers: ForwardedHeaders,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            name=tool_config.open_ai_tool.function.name,
            description=tool_config.open_ai_tool.function.description,
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
        )
        self.__request_details_builder: _RequestDetailsBuilder = request_details_builder
        self.stage_name_component = f"Calling {tool_config.rest_api_method_info.method_url}"
        self.__auth_info: Authorization = auth_info
        self._tool_config: RestApiTool = tool_config
        self.__dial_attachment_service = dial_attachment_service
        self.__forwarded_headers = forwarded_headers

    async def _run_in_stage_async(
        self, stage_wrapper: BaseStageWrapper | None, *args: Any, **kwargs: Any
    ) -> CompletionResult:
        request_details = (
            self.__request_details_builder.with_url(
                self._tool_config.rest_api_method_info.method_url
            )
            .with_method(self._tool_config.rest_api_method_info.method_type)
            .with_parameters(
                self._tool_config.open_ai_tool.function.parameters.properties,
                **kwargs,
            )
        )

        request_details = await request_details.with_auth(self.__auth_info)
        request_details = request_details.build()

        # Merge forwarded X-* headers from the original request into the outgoing request
        headers = dict(request_details.headers)
        if self.__forwarded_headers:
            headers.update(self.__forwarded_headers)

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request_details.method,
                url=request_details.url,
                headers=headers,
                params=request_details.params,
                json=request_details.data,
            )
            response.raise_for_status()

            raw_mime = response.headers.get('Content-Type')
            mime_type = raw_mime.split(';', 1)[0].strip() if raw_mime else None

            attachments: list[Attachment] = []
            rac = self._tool_config.response_as_attachment

            if rac and rac.enabled and mime_type and matches_type(mime_type, rac.content_types):
                title = generate_attachment_filename(
                    mime_type, base_filename=self._tool_config.open_ai_tool.function.name
                )
                logger.debug(f"Attachment: {title}, Tool Config: {self._tool_config}")
                attachment = Attachment(title=title, type=mime_type, data=response.text)
                attachment = await self.__dial_attachment_service.upload_attachment_to_core(
                    attachment
                )
                attachments.append(attachment)

            content = response.text
            if attachments and rac and not rac.include_body_as_content:
                content = f"See attached file: {attachments[0].title}"

            result = CompletionResult(
                content=content,
                content_type=response.headers.get('Content-Type', ""),
                attachments=attachments,
            )

            if stage_wrapper:
                stage_wrapper.add_result(result)

            return result
