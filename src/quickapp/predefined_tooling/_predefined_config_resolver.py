import logging
from typing import Any

from injector import ProviderOf, inject
from pydantic import TypeAdapter, ValidationError

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


@inject
class PredefinedConfigResolver(ConfigResolver):
    def __init__(
        self,
        provider: PredefinedContentProvider,
        exceptions_provider: ProviderOf[_PredefinedToolingContext],
    ):
        self._provider = provider
        self._exceptions_provider = exceptions_provider

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
