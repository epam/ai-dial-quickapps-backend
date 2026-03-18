from typing import Any

from pydantic import BaseModel, Field


class _Button(BaseModel):
    value: Any
    caption: str
    confirmationText: str | None = Field(default=None)
    populateText: str | None = Field(default=None)
    submit: bool = Field(default=True)

    def to_json_schema(self) -> dict:
        return {
            "const": self.value,
            "title": self.caption,
            "dial:widgetOptions": {
                "confirmationMessage": self.confirmationText,
                "populateText": self.populateText,
                "submit": self.submit,
            },
        }


def _create_buttons(
    *,
    buttons: list[_Button],
    property_name: str = "starter",
    description: str = "Select an action",
    ty: str = "number",
    chat_disabled: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "dial:chatMessageInputDisabled": chat_disabled,
        "properties": {
            property_name: {
                "description": description,
                "type": ty,
                "dial:widget": "buttons",
                "oneOf": [button.to_json_schema() for button in buttons],
            },
        },
    }
