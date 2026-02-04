import json
from enum import Enum
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.application import ApplicationConfig
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.tool import AnyTool
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet

project_root_path = Path(__file__).parents[3]


class PredefinedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='predefined_')
    base_path: str | None = Field(
        default=None, description="base path where predefined templates are stored"
    )


class PromptConfigResponse(BaseModel):
    prompt: str
    allowed_models: List[str] = Field(default=[])


class PromptMapping(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='config_')
    prompt_mapping: Dict[str, List[str]] = Field(
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


class TemplateType(str, Enum):
    system_prompt = 'prompt'
    tool_set = 'toolset'
    tool = 'tool'


class ConfigResolver:
    def __init__(self):
        self.predefined_settings = PredefinedSettings()
        if self.predefined_settings.base_path:
            self.base_path = Path(self.predefined_settings.base_path)
        else:
            self.base_path = project_root_path / "config/predefined"
        self.cache = {}  # avoid re-reading files
        self.prompt_mapping = PromptMapping()
        self.template_map = self._scan_templates()

    def _scan_templates(self):
        template_map: Dict[str, List[str]] = {tt: [] for tt in TemplateType}
        prompt_dir = self.base_path / TemplateType.system_prompt.value
        if prompt_dir.exists() and prompt_dir.is_dir():
            for file_path in prompt_dir.glob("*.md"):
                template_map[TemplateType.system_prompt.value].append(file_path.stem)

        tools_dir = self.base_path / TemplateType.tool.value
        if tools_dir.exists() and tools_dir.is_dir():
            for json_file in tools_dir.glob("*.json"):
                template_map[TemplateType.tool.value].append(json_file.stem)

        tool_sets_dir = self.base_path / TemplateType.tool_set.value
        if tool_sets_dir.exists() and tool_sets_dir.is_dir():
            for json_file in tool_sets_dir.glob("*.json"):
                template_map[TemplateType.tool_set.value].append(json_file.stem)

        return template_map

    def get_prompts(self) -> List[PromptConfigResponse]:
        all_prompts = self.template_map[TemplateType.system_prompt.value]
        resolved_prompts = [
            PromptConfigResponse(
                prompt=p, allowed_models=self.prompt_mapping.prompt_mapping.get(p, [])
            )
            for p in all_prompts
        ]
        return resolved_prompts

    def get_tools(self) -> List[str]:
        return self.template_map[TemplateType.tool.value]

    def get_tool_sets(self) -> List[str]:
        return self.template_map[TemplateType.tool_set.value]

    def read_template_content(self, template_type: TemplateType, template_name: str):
        key = f"{template_type.value}/{template_name}"
        if key in self.cache:
            return self.cache[key]  # No need to read file again.
        if template_type == TemplateType.system_prompt:
            file_path = self.base_path / f"{key}.md"
            try:
                content = file_path.read_text(encoding='utf-8')
                self.cache[key] = content
                return content
            except Exception as e:
                raise FileNotFoundError(f"Error reading prompt '{file_path}': {e}")
        else:
            # Toolsets and Tools are JSON
            file_path = self.base_path / f"{key}.json"
            try:
                with file_path.open('r', encoding='utf-8') as f:
                    content = json.load(f)
                self.cache[key] = content
                return content
            except Exception as e:
                raise FileNotFoundError(f"Error reading JSON template '{file_path}': {e}")

    def resolve_config(self, raw_config: ApplicationConfig) -> ApplicationConfig:
        # orchestrator system prompt
        spc = raw_config.orchestrator.system_prompt
        if isinstance(spc, PredefinedSystemPromptConfig):
            spc.content = self.read_template_content(TemplateType.system_prompt, spc.template)

        # tool-sets
        resolved_tool_set_list = []
        for tool_set in raw_config.tool_sets:
            if isinstance(tool_set, PredefinedToolSet):
                resolved_tool_set_list.append(self.resolve_predefined_toolset(tool_set))
            else:
                # It's not a template, however it might contain tool references
                resolved_tool_set_list.append(self.resolve_toolset(tool_set))
        raw_config.tool_sets = resolved_tool_set_list

        return raw_config

    def resolve_predefined_toolset(self, tool_set: PredefinedToolSet) -> ToolSet:
        template_content = self.read_template_content(TemplateType.tool_set, tool_set.template_name)
        actual_tool_set: ToolSet = TypeAdapter(ToolSet).validate_python(template_content)
        return self.resolve_toolset(actual_tool_set)

    def resolve_toolset(self, tool_set: ToolSet) -> ToolSet:
        if not hasattr(tool_set, 'tools'):
            return tool_set
        resolved_tools: List[AnyTool] = []
        for tool in tool_set.tools:
            if isinstance(tool, PredefinedTool) and tool.enabled:
                resolved_tools.append(self.resolve_tool(tool))
            else:
                # It's not a template, just append it
                resolved_tools.append(tool)

        tool_set.tools.clear()
        tool_set.tools.extend(resolved_tools)  # type: ignore[arg-type]

        return tool_set

    def resolve_tool(self, tool: PredefinedTool) -> AnyTool:
        template_content = self.read_template_content(TemplateType.tool, tool.template_name)
        actual_tool: AnyTool = TypeAdapter(AnyTool).validate_python(template_content)

        return actual_tool
