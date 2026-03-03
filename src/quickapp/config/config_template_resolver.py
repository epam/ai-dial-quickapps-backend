from typing import Any

from injector import inject
from pydantic import BaseModel, Field, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.application import ApplicationConfig
from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.tool import AnyTool
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet


class PromptConfigResponse(BaseModel):
    prompt: str
    allowed_models: list[str] = Field(default=[])


class PromptMapping(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='config_')
    prompt_mapping: dict[str, list[str]] = Field(
        default={
            "gpt_prompt": [
                "gpt-5-mini-2025-08-07",
                "gpt-4o-mini-2024-07-18",
                "gpt-5.1-2025-11-13",
                "gpt-4o-2024-05-13-adapter-staging",
                "gpt-5.1-chat-2025-11-13",
                "gpt-4o-transcribe-2025-03-20",
                "gpt-5-2025-08-07",
                "gpt-35-turbo",
                "gpt-5.1-codex-2025-11-13",
                "gpt-4o-mini-tts",
                "gpt-4-turbo-2024-04-09",
                "gpt-5-2025-08-07-reasoning",
                "gpt-4o",
                "gpt-4o-2024-05-13-adapter-prod",
                "gpt-4o-2024-11-20",
                "gpt-oss-120b",
                "gpt-4o-2024-05-13",
                "gpt-4o-2024-08-06",
                "gpt-4o-assistants",
                "gpt-4o-mini-2024-07-18-adapter-prod",
                "gpt-35-turbo-0125",
                "gpt-4.1-2025-04-14",
                "gpt-5-2025-08-07-low-filter",
                "gpt-4o-2024-11-20-with-caching",
                "gpt-4o-2024-05-13-adapter-sales",
                "gpt-35-turbo-1106",
                "gpt-4o-mini-transcribe-2025-03-20",
                "gpt-5-nano-2025-08-07",
                "gpt-image-1",
                "gpt-4.1-mini-2025-04-14",
                "gpt-4.1-bing-grounding",
                "gpt-4-0613-assistants",
                "gpt-4o-bing-grounding-test",
                "gpt-4-turbo",
                "gpt-4o-google-dlp-interceptor",
                "gpt-5-chat-2025-08-07",
                "gpt-4.1-nano-2025-04-14",
            ],
            "gemini_prompt": [
                "gemini-pro-vision-adapter",
                "gemini-2.5-flash-image-preview",
                "gemini-2.5-pro-google-search",
                "gemini-2.0-flash-lite-001",
                "gemini-2.5-flash",
                "gemini-2.0-flash-exp",
                "gemini-2.5-pro",
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash-exp-google-search",
            ],
            "anthropic_prompt": [
                "anthropic.claude-v3-haiku-interceptor",
                "us.anthropic.claude-opus-4-1-20250805-v1:0",
                "anthropic.claude-v3-haiku-google-dlp-interceptor",
                "anthropic.claude",
                "claude-haiku-4-5@20251001",
                "anthropic.claude-v3-5-haiku",
                "anthropic.claude-v3-haiku-us-east-1",
                "claude-3-5-sonnet-v2@20241022",
                "claude-3-opus@20240229",
                "anthropic.claude-v2",
                "anthropic.claude-v3-haiku",
                "claude-3-7-sonnet@20250219",
                "us.anthropic.claude-3-7-sonnet-20250219-v1-with-thinking",
                "anthropic.claude-v3-haiku-us-west-2",
                "anthropic.claude-v3-haiku-pii-interceptor",
                "anthropic.claude-instant-v1",
                "anthropic.claude-v3-5-sonnet",
                "anthropic.claude-v3-5-sonnet-v1",
                "anthropic.claude-v3-5-sonnet-v2",
                "claude-3-5-haiku@20241022",
                "anthropic.claude-v4-5-sonnet-v1",
                "anthropic.claude-v3-haiku-bundle",
                "anthropic.claude-haiku-4-5-20251001-v1:0",
                "claude-3-haiku@20240307",
                "anthropic.claude-v3-sonnet",
                "claude-3-5-sonnet-v2@latest",
                "claude-opus-4@20250514",
                "claude-3-5-sonnet@20240620",
                "anthropic.claude-opus-4-20250514-v1",
                "anthropic.claude-v3-opus",
                "anthropic.claude-v2-1",
                "us.anthropic.claude-3-7-sonnet-20250219-v1",
                "anthropic.claude-sonnet-4-20250514-v1",
                "claude-sonnet-4@20250514",
            ],
        },
        description="Mapping between predefined system_prompts and DialCore deployments",
    )

    @model_validator(mode='after')
    def check_unique_models(self):
        all_models = []
        for group in self.prompt_mapping.values():
            all_models.extend(group)
        duplicates = {name for name in all_models if all_models.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate model/deployment names found: {duplicates}")
        return self


@inject
class ConfigResolver:
    def __init__(self, provider: PredefinedContentProvider):
        self._provider = provider
        self.prompt_mapping = PromptMapping()

    @property
    def template_map(self) -> dict[str, list[str]]:
        """Read-only property delegating to the provider, excluding SKILL."""
        return {
            ct.value: self._provider.list_names(ct) for ct in ContentType if ct != ContentType.SKILL
        }

    def get_prompts(self) -> list[PromptConfigResponse]:
        return [
            PromptConfigResponse(
                prompt=p, allowed_models=self.prompt_mapping.prompt_mapping.get(p, [])
            )
            for p in self._provider.list_names(ContentType.PROMPT)
        ]

    def get_tools(self) -> list[str]:
        return self._provider.list_names(ContentType.TOOL)

    def get_tool_sets(self) -> list[str]:
        return self._provider.list_names(ContentType.TOOLSET)

    def read_template_content(self, template_type: ContentType, template_name: str) -> str | dict[str, Any]:
        if template_type.is_text:
            return self._provider.read_text(template_type, template_name)
        return self._provider.read_json(template_type, template_name)

    def resolve_config(self, raw_config: ApplicationConfig) -> ApplicationConfig:
        # orchestrator system prompt
        spc = raw_config.orchestrator.system_prompt
        if isinstance(spc, PredefinedSystemPromptConfig):
            spc.content = self.read_template_content(ContentType.PROMPT, spc.template)

        # tool-sets
        resolved_tool_set_list = []
        for tool_set in raw_config.tool_sets:
            if isinstance(tool_set, PredefinedToolSet):
                resolved_tool_set_list.append(self.resolve_predefined_toolset(tool_set))
            else:
                resolved_tool_set_list.append(self.resolve_toolset(tool_set))
        raw_config.tool_sets = resolved_tool_set_list

        return raw_config

    def resolve_predefined_toolset(self, tool_set: PredefinedToolSet) -> ToolSet:
        template_content = self.read_template_content(ContentType.TOOLSET, tool_set.template_name)
        actual_tool_set: ToolSet = TypeAdapter(ToolSet).validate_python(template_content)
        return self.resolve_toolset(actual_tool_set)

    def resolve_toolset(self, tool_set: ToolSet) -> ToolSet:
        if not hasattr(tool_set, 'tools'):
            return tool_set
        resolved_tools: list[AnyTool] = []
        for tool in tool_set.tools:
            if isinstance(tool, PredefinedTool) and tool.enabled:
                resolved_tools.append(self.resolve_tool(tool))
            else:
                resolved_tools.append(tool)

        tool_set.tools.clear()
        tool_set.tools.extend(resolved_tools)  # type: ignore[arg-type]

        return tool_set

    def resolve_tool(self, tool: PredefinedTool) -> AnyTool:
        template_content = self.read_template_content(ContentType.TOOL, tool.template_name)
        return TypeAdapter(AnyTool).validate_python(template_content)
