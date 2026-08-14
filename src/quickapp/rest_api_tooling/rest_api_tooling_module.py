import logging

from fastapi_injector import request_scope
from injector import Binder, ClassAssistedBuilder, Module, multiprovider

from quickapp.common import AcceptLanguage, StagedBaseTool
from quickapp.common.localized_string import resolve_localized
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.common.utils import sanitize_toolname
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.rest_api import RestApiTool
from quickapp.config.toolsets.rest_api import RestApiToolSet

from ._request_detail_builder import _RequestDetailsBuilder
from ._rest_api_stage_wrapper import _RestApiStageWrapper
from ._rest_api_tool import _RestApiTool

logger = logging.getLogger(__name__)


class RestApiToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_RestApiStageWrapper, to=_RestApiStageWrapper)
        binder.bind(_RestApiTool, to=_RestApiTool, scope=request_scope)
        binder.bind(_RequestDetailsBuilder, to=_RequestDetailsBuilder)
        binder.bind(OAuthTokenFetcher, to=OAuthTokenFetcher)
        logger.debug("RestApiTooling module configuration completed")

    @multiprovider
    def __provide_rest_api_tools(
        self,
        app_config: ApplicationConfig,
        tool_builder: ClassAssistedBuilder[_RestApiTool],
        accept_language: AcceptLanguage,
    ) -> list[StagedBaseTool]:
        result: list[StagedBaseTool] = []
        for toolset_info in app_config.tool_sets:
            if isinstance(toolset_info, RestApiToolSet) and toolset_info.enabled:
                toolset_stage_name = resolve_localized(toolset_info.name, accept_language)
                result.extend(
                    self.__create_rest_api_tools(toolset_info, tool_builder, toolset_stage_name)
                )
        return result

    @staticmethod
    def __create_rest_api_tools(
        rest_api_toolset: RestApiToolSet,
        tool_builder: ClassAssistedBuilder[_RestApiTool],
        toolset_stage_name: str,
    ) -> list[StagedBaseTool]:
        result: list[StagedBaseTool] = []
        for tool_config in rest_api_toolset.tools:
            if not tool_config.enabled:
                continue
            if isinstance(tool_config, RestApiTool):
                if (
                    "response_as_attachment" not in tool_config.model_fields_set
                    and rest_api_toolset.response_as_attachment is not None
                ):
                    tool_config = tool_config.model_copy(
                        update={"response_as_attachment": rest_api_toolset.response_as_attachment}
                    )
                if "response_as_attachment" not in tool_config.model_fields_set:
                    logger.warning(
                        "REST API tool '%s' uses the default response_as_attachment.enabled=false. "
                        "If you relied on automatic attachment creation, "
                        "set enabled=true explicitly.",
                        tool_config.open_ai_tool.function.name,
                    )
                tool_config = tool_config.model_copy(
                    update={
                        "open_ai_tool": tool_config.open_ai_tool.model_copy(
                            update={
                                "function": tool_config.open_ai_tool.function.model_copy(
                                    update={
                                        "name": sanitize_toolname(
                                            f"{resolve_localized(rest_api_toolset.name)}_{tool_config.open_ai_tool.function.name}"
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            tool = tool_builder.build(
                tool_config=tool_config, auth_info=rest_api_toolset.authorization
            )
            tool.stage_name_component = toolset_stage_name
            result.append(tool)
        return result
