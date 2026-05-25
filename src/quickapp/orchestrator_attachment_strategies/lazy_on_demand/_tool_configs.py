from quickapp.common.tool_names import (
    INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
    INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
)
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

GET_CONTENT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
            description=(
                "Loads one allowed attachment by URL for use in this turn. "
                f"Pass the exact `url` string from the "
                f"`{INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME}` tool "
                "result (`entries[].url`) or from user `<attachments>` metadata in messages. "
                "Only URLs from current admin contexts or user attachments are accepted; arbitrary paths or URLs are rejected. "
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "attachment_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Exact file `url` from `internal_attachments_available_context.entries[].url` "
                            "or from user `<attachments>` section (same string, including path). "
                        ),
                    )
                },
                required=["attachment_url"],
            ),
        )
    ),
    display=ToolDisplayConfig(
        stage=ToolStageConfig(name="Get context content", show=True, defer_close=True),
    ),
)


def render_get_content_tool_config(input_attachment_types: list[str]) -> InternalTool:
    """Return a per-request copy of :data:`GET_CONTENT_TOOL_CONFIG` whose function and
    ``attachment_url`` descriptions advertise the orchestrator's accepted MIME patterns.

    The template constant is treated as immutable; this helper deep-copies it and
    appends a single ``"Accepted MIME types: <pattern>, <pattern>."`` sentence to the
    function description and the ``attachment_url`` parameter description, so the model
    learns the live allowlist (wildcards preserved verbatim, e.g. ``image/*``).

    When ``input_attachment_types`` is empty, the helper returns a deep copy of the
    template without any appended sentence — this branch is defensive only;
    :func:`should_enable_get_content_tool` filters out the no-allowlist case before
    registration in practice.
    """
    rendered = GET_CONTENT_TOOL_CONFIG.model_copy(deep=True)
    if not input_attachment_types:
        return rendered
    suffix = "Accepted MIME types: " + ", ".join(input_attachment_types) + "."
    function = rendered.open_ai_tool.function
    function.description = function.description.rstrip() + " " + suffix
    attachment_url_param = function.parameters.properties["attachment_url"]
    attachment_url_param.description = (
        (attachment_url_param.description or "").rstrip() + " " + suffix
    )
    return rendered
