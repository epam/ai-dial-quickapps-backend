import logging

from fastapi_injector import request_scope
from injector import Binder, ClassAssistedBuilder, Module, multiprovider

from quickapp.common import ACCEPT_LANGUAGE, StagedBaseTool
from quickapp.common.localized_string import resolve_localized
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.common.utils import sanitize_toolname
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.rest_api import RestApiTool
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.tool_discovery._deferred_tools_context import _DeferredToolsContext

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
        accept_language: ACCEPT_LANGUAGE,
        deferred_context: _DeferredToolsContext,
    ) -> list[StagedBaseTool]:
        result: list[StagedBaseTool] = []
        discovery_cfg = app_config.orchestrator.tool_discovery
        for toolset_info in app_config.tool_sets:
            if isinstance(toolset_info, RestApiToolSet) and toolset_info.enabled:
                toolset_stage_name = resolve_localized(toolset_info.name, accept_language)
                tools = self.__create_rest_api_tools(toolset_info, tool_builder, toolset_stage_name)
                deferred_effective = (
                    toolset_info.deferred
                    and discovery_cfg.enabled
                    and len(tools) >= discovery_cfg.min_tools_for_deferral
                )
                if deferred_effective:
                    from quickapp.config.tools.base import BaseOpenAITool

                    catalog = [
                        {
                            "name": t.tool_config.open_ai_tool.function.name,
                            "description": t.tool_config.open_ai_tool.function.description or "",
                        }
                        for t in tools
                        if isinstance(t.tool_config, BaseOpenAITool)
                    ]
                    definitions = {
                        t.tool_config.open_ai_tool.function.name: t.tool_config.open_ai_tool.model_dump(
                            mode="json", exclude_none=True
                        )
                        for t in tools
                        if isinstance(t.tool_config, BaseOpenAITool)
                    }
                    deferred_context.register_deferred_tools(catalog, definitions)
                    logger.debug(
                        "Deferred %d tools from REST toolset '%s' into DeferredToolsContext",
                        len(tools),
                        toolset_stage_name,
                    )
                result.extend(tools)
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
