from pydantic import BaseModel, Field


class ConversationStarter(BaseModel):
    title: str = Field(description="The title of the conversation starter button.")
    text: str = Field(
        description="The text to populate in the chat input when the button is clicked."
    )


class ConversationStartersConfig(BaseModel):
    intro_text: str = Field(
        default="Select an action",
        description="The introductory text shown above the conversation starters.",
    )
    chat_message_input_disabled: bool = Field(
        default=False,
        description="Whether to disable the chat message input when using conversation starters. If true, users can only interact with the agent through the conversation starter buttons.",
    )
    auto_submit: bool = Field(
        default=True,
        description="Whether to automatically submit the conversation starter text when a button is clicked. If false, the text will be populated in the chat input but not submitted, allowing users to edit it before sending.",
    )
    starters: list[ConversationStarter] = Field(
        description="The list of conversation starters.", min_length=1
    )
