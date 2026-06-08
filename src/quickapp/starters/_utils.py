from typing import Any

from aidial_sdk.chat_completion import Button, FormMetaclass
from aidial_sdk.pydantic.v2 import ConfigDict as DialConfigDict
from aidial_sdk.pydantic.v2 import Field as DialField
from pydantic import BaseModel

from quickapp.config.starters import ConversationStarter, ConversationStartersConfig


def _create_dial_buttons(
    starter_configs: list[ConversationStarter], auto_submit: bool
) -> list[Button]:
    return [
        Button(
            const=const,
            title=starter_config.title,
            populateText=starter_config.text,
            submit=auto_submit,
        )
        for const, starter_config in enumerate(starter_configs, start=1)
    ]


def create_starters_configuration(config: ConversationStartersConfig) -> dict[str, Any]:
    buttons = _create_dial_buttons(
        starter_configs=config.starters,
        auto_submit=config.auto_submit,
    )

    class _QuickAppStartersConfig(BaseModel, metaclass=FormMetaclass):
        model_config = DialConfigDict(
            chat_message_input_disabled=config.chat_message_input_disabled
        )

        starter: int | None = DialField(
            default=None,
            description=config.intro_text,
            buttons=buttons,
        )

    return _QuickAppStartersConfig.model_json_schema()
