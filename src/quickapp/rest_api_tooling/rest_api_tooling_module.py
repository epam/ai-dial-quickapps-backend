import logging

from fastapi_injector import request_scope
from injector import Binder, ClassAssistedBuilder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.rest_api import RestApiToolSet

from ._request_detail_builder import _RequestDetailsBuilder
from ._rest_api_stage_wrapper import _RestApiStageWrapper
from ._rest_api_tool import _RestApiTool

logger = logging.getLogger(__name__)


class RestApiToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_RestApiStageWrapper, to=_RestApiStageWrapper)
        binder.bind(_RestApiTool, to=_RestApiTool)
        binder.bind(_RequestDetailsBuilder, to=_RequestDetailsBuilder)
        binder.bind(OAuthTokenFetcher, to=OAuthTokenFetcher)
        logger.debug("RestApiTooling module configuration completed")

    @request_scope
    @multiprovider
    def __provide_rest_api_tools(
        self, app_config: ApplicationConfig, tool_builder: ClassAssistedBuilder[_RestApiTool]
    ) -> list[StagedBaseTool]:
        result = []
        for toolset_info in app_config.tool_sets:
            if isinstance(toolset_info, RestApiToolSet) and toolset_info.enabled:
                for tool in self.__create_rest_api_tools(toolset_info, tool_builder):
                    result.append(tool)
        return result

    @staticmethod
    def __create_rest_api_tools(
        rest_api_toolset: RestApiToolSet, tool_builder: ClassAssistedBuilder[_RestApiTool]
    ) -> list[StagedBaseTool]:
        return [
            tool_builder.build(tool_config=tool_config, auth_info=rest_api_toolset.authorization)
            for tool_config in rest_api_toolset.tools
            if tool_config.enabled
        ]
