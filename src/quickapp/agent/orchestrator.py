import logging

from aidial_sdk.chat_completion import Choice
from aidial_sdk.chat_completion.request import CustomContent, Message, Role
from injector import ProviderOf, inject
from pydantic.v1 import StrictStr

from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.agent.models import TOOL_EXECUTION_HISTORY, ExecutedToolCallDTO
from quickapp.agent.processors.chunk_processor import ChunkProcessor
from quickapp.agent.processors.tool_executor import ToolExecutor
from quickapp.common import DeploymentUsage
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.common.state_holder import StateHolder
from quickapp.config.application import ApplicationConfig
from quickapp.usage_statistics.usage_statistics_service import UsageStatisticsService

logger = logging.getLogger(__name__)


@inject
class Orchestrator:

    def __init__(
        self,
        presentation_settings: PresentationSettings,
        messages_context: MessagesMixin,
        choice: Choice,
        state_holder: StateHolder,
        usage_statistics_service: UsageStatisticsService,
        tool_executor: ToolExecutor,
        assistant_invoker_provider: ProviderOf[AssistantInvoker],
        chunk_processor_provider: ProviderOf[ChunkProcessor],
        app_config: ApplicationConfig,
    ) -> None:
        self.__messages_context: MessagesMixin = messages_context
        self.__choice: Choice = choice
        self.__state_holder: StateHolder = state_holder
        self.__usage_statistics_service: UsageStatisticsService = usage_statistics_service
        self.__SHOW_USAGE_STATISTICS = presentation_settings.show_usage_statistics
        self.__tool_executor = tool_executor
        self.__assistant_invoker_provider = assistant_invoker_provider
        self.__chunk_processor_provider = chunk_processor_provider
        self.__iterations_counter = 0
        self.__MAX_ITERATIONS_COUNT = app_config.orchestrator.max_iterations
        self.__orchestrator_deployment_name = app_config.orchestrator.deployment.name
        self.__usage_statistics_list: list[DeploymentUsage] = []

    async def invoke(self):
        await self.__track_iterations()

        assistant_invoker = self.__assistant_invoker_provider.get()
        chat_completion_stream = await assistant_invoker.invoke()
        assistant_call_result = await self.__chunk_processor_provider.get().process_chunks(
            chat_completion=chat_completion_stream, destination=self.__choice
        )

        self.__messages_context.append_message(
            Message(
                role=Role.ASSISTANT,
                content=assistant_call_result.content or StrictStr(" "),  # avoid empty content
                custom_content=CustomContent(attachments=assistant_call_result.attachments),
                tool_calls=assistant_call_result.tool_calls,
            )
        )
        if assistant_call_result.usage and self.__SHOW_USAGE_STATISTICS:
            self.__usage_statistics_list.append(
                DeploymentUsage(
                    model_name=self.__orchestrator_deployment_name,
                    prompt_tokens=assistant_call_result.usage.prompt_tokens,
                    completion_tokens=assistant_call_result.usage.completion_tokens,
                )
            )
        logger.debug(f"Message from agent: {self.__messages_context.messages}")
        # State already contains assistant call result.
        # 2. Check for tool calls in the response and handle them concurrently
        tool_calls = assistant_call_result.tool_calls
        if tool_calls:
            # 3. Prepare tool message/call (i.e. add system message from tool config, validate parameters, etc.)
            # 4. Process tool calls asynchronously and concurrently
            logger.debug(f"Agent requests tool calls: {tool_calls}")
            tool_call_results = await self.__tool_executor.execute(tool_calls)
            if tool_call_results:
                logger.debug(tool_call_results)
                # 5. store tool results to state  ## Check if state might be pushed during the actual call.
                # refactor below? seems we need to append to the state
                tool_execution_history = self.__state_holder.get_state().get(
                    TOOL_EXECUTION_HISTORY, []
                )
                # todo move to separate method
                for i in range(len(tool_call_results)):
                    tool_call_result_message = tool_call_results[i].to_tool_message()
                    self.__messages_context.append_message(tool_call_result_message)
                    tool_execution_history.append(
                        ExecutedToolCallDTO(
                            tool_call=tool_calls[i],
                            tool_execution_result=tool_call_result_message,
                        ).model_dump(mode="json", exclude_none=True)
                    )
                    for attachment in tool_call_results[i].propagate_to_choice:
                        # Need to repack, cause Message contains same attachment but from other package: aidial_client.types.chat.response.Attachment
                        self.__choice.add_attachment(**attachment.model_dump())
                    if tool_call_results[i].usage and self.__SHOW_USAGE_STATISTICS:
                        self.__usage_statistics_list.extend(tool_call_results[i].usage)
                logger.debug(f"State:{tool_execution_history}")
                self.__state_holder.add_state(TOOL_EXECUTION_HISTORY, tool_execution_history)
            else:
                raise RuntimeError(f"Tool call(s) {tool_calls} doesn't return any result.")

            logger.debug(self.__messages_context.messages)
            # 7. Call agent if there were any tool call
            await self.invoke()
        else:
            # 8. If no tool calls, return the processed response and end
            self.__choice.set_state(self.__state_holder.get_state())
            if self.__usage_statistics_list and self.__SHOW_USAGE_STATISTICS:
                await self.__usage_statistics_service.process_usage_statistics(
                    self.__usage_statistics_list
                )
            logger.debug(self.__state_holder.get_state())
        # 9. Push usage stats to the stage if that is configured

        return None  # As we are storing state in StateHolder, there is no need to return any value.

    async def __track_iterations(self):
        self.__iterations_counter += 1
        if self.__iterations_counter > self.__MAX_ITERATIONS_COUNT:
            raise OrchestratorExceedMaxIterationsException()
