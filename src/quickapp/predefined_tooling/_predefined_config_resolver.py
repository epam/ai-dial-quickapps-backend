import logging
from functools import cached_property
from typing import Any

from injector import ProviderOf, inject
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.application import ApplicationConfig
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.config.json_merge_patch import JsonMergePatchError, json_merge_patch
from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.tool import AnyTool
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.config.toolsets.toolset import ToolSet
from quickapp.config.utils import TOOL_SETS_LIST_ADAPTER, TOOLSET_ADAPTER, expand_predefined_tools
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext

_TOOL_ADAPTER: TypeAdapter[AnyTool] = TypeAdapter(AnyTool)

logger = logging.getLogger(__name__)


def _loc_to_json_pointer(loc: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(p) for p in loc)


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
class PredefinedConfigResolver(ConfigResolver):
    def __init__(
        self,
        provider: PredefinedContentProvider,
        exceptions_provider: ProviderOf[_PredefinedToolingContext],
    ):
        self._provider = provider
        self._exceptions_provider = exceptions_provider
        self.prompt_mapping = PromptMapping()

    @cached_property
    def template_map(self) -> dict[str, list[str]]:
        """Read-only map of template type → names, excluding SKILL and default config.
        Cached: the
        provider loads templates once at startup, so the result is stable."""
        return {
            ct.value: self._provider.list_names(ct)
            for ct in ContentType
            if ct not in (ContentType.SKILL, ContentType.DEFAULT_CONFIGURATION)
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

    def get_default_configuration(self) -> dict[str, Any]:
        """Return merged default configuration with ``tool_sets`` fully resolved.

        Predefined toolsets and ``predefined-tool`` entries inside hosting toolsets
        are expanded to validated tool models (same as runtime resolution).
        """
        cfg = dict(self._provider.get_default_configuration())
        raw_tool_sets = cfg.get("tool_sets")
        if not isinstance(raw_tool_sets, list):
            return cfg
        try:
            tool_sets = TOOL_SETS_LIST_ADAPTER.validate_python(raw_tool_sets)
        except ValidationError as e:
            logger.warning(
                "Invalid tool_sets in default_configuration; leaving tool_sets unchanged: %s",
                e,
            )
            return cfg
        resolved = self._resolve_tool_sets(tool_sets, log_only=True)
        cfg["tool_sets"] = TOOL_SETS_LIST_ADAPTER.dump_python(resolved, mode="json")
        return cfg

    def read_template_content(
        self, template_type: ContentType, template_name: str
    ) -> str | dict[str, Any]:
        if template_type.is_text:
            return self._provider.read_text(template_type, template_name)
        return self._provider.read_json(template_type, template_name)

    def resolve_config(self, raw_config: ApplicationConfig) -> ApplicationConfig:
        self._resolve_system_prompt(raw_config)
        raw_config.tool_sets = self._resolve_tool_sets(raw_config.tool_sets)
        return raw_config

    def _resolve_system_prompt(self, raw_config: ApplicationConfig) -> None:
        # Fail-fast: a missing predefined prompt leaves no LLM to call, so the
        # request cannot proceed.
        try:
            spc = raw_config.orchestrator.system_prompt
            if isinstance(spc, PredefinedSystemPromptConfig):
                content = self.read_template_content(ContentType.PROMPT, spc.template)
                spc.content = str(content)
        except ConfigResolutionException as e:
            self._record_exception(e)
            raise

    def _resolve_tool_sets(
        self, tool_sets: list[ToolSet], *, log_only: bool = False
    ) -> list[ToolSet]:
        """Resolve each toolset; failures skip that entry so the rest can proceed.

        When ``log_only`` is True (default-configuration export), a failed **toolset**
        (missing template, merge/validation error) is only logged. When False,
        ``ConfigResolutionException`` is also recorded for the initialization-issues
        stage, and ``KeyError`` is re-raised. Skipped **predefined tools** inside a
        hosting toolset are always logged and recorded via
        ``_notify_skipped_predefined_tool`` regardless of ``log_only``.
        """
        resolved: list[ToolSet] = []
        for tool_set in tool_sets:
            try:
                if isinstance(tool_set, PredefinedToolSet):
                    resolved.append(self.resolve_predefined_toolset(tool_set))
                else:
                    resolved.append(self.resolve_toolset(tool_set))
            except ConfigResolutionException as e:
                if log_only:
                    logger.warning("Skipping toolset: %s", e)
                else:
                    self._record_exception(e)
            except KeyError as e:
                if log_only:
                    logger.warning("Skipping toolset (template missing): %s", e)
                else:
                    raise
        return resolved

    def _notify_skipped_predefined_tool(
        self, tool: PredefinedTool, exc: ConfigResolutionException
    ) -> None:
        logger.warning("Skipping predefined tool %r: %s", tool.template_name, exc)
        self._record_exception(exc)

    def _record_exception(self, exception: ConfigResolutionException) -> None:
        self._exceptions_provider.get().append_exception(exception)

    def resolve_predefined_toolset(self, tool_set: PredefinedToolSet) -> ToolSet:
        template_content = self.read_template_content(ContentType.TOOLSET, tool_set.template_name)
        actual_tool_set: ToolSet = _merge_and_validate(
            tool_set.template_name,
            template_content,
            tool_set.override,
            TOOLSET_ADAPTER,
        )
        return self.resolve_toolset(actual_tool_set)

    def resolve_toolset(self, tool_set: ToolSet) -> ToolSet:
        return expand_predefined_tools(
            tool_set,
            resolve_tool=self.resolve_tool,
            on_predefined_tool_error=self._notify_skipped_predefined_tool,
        )

    def resolve_tool(self, tool: PredefinedTool) -> AnyTool:
        template_content = self.read_template_content(ContentType.TOOL, tool.template_name)
        return _merge_and_validate(
            tool.template_name,
            template_content,
            tool.override,
            _TOOL_ADAPTER,
        )


def _merge_and_validate(
    template_name: str,
    template_content: Any,
    override: dict[str, Any] | None,
    adapter: TypeAdapter[Any],
) -> Any:
    if override is not None:
        try:
            template_content = json_merge_patch(template_content, override)
        except JsonMergePatchError as e:
            raise ConfigResolutionException(
                message=e.message,
                template_name=template_name,
                json_path=e.path,
            ) from e
    try:
        return adapter.validate_python(template_content)
    except ValidationError as e:
        errors = e.errors()
        pairs = [(_loc_to_json_pointer(err["loc"]), err["msg"]) for err in errors]
        first_path, first_msg = pairs[0] if pairs else ("", str(e))
        details = "\n".join(f"{path}: {msg}" for path, msg in pairs)
        raise ConfigResolutionException(
            message=first_msg,
            template_name=template_name,
            json_path=first_path,
            details=details,
        ) from e
