from typing import ClassVar

from .initialization import InitializationException


class OffloadConfigurationException(InitializationException):
    """Large tool-response offload is enabled but its required DIAL files
    read-back tools are not exposed, so offload was disabled. Soft: the request
    proceeds (large content stays inline); rendered as a warning in the
    Initialization issues stage.
    """

    is_hard: ClassVar[bool] = False

    def __init__(self, missing_tools: list[str]):
        self.missing_tools = missing_tools
        super().__init__(
            "Large tool-response offload is enabled but the DIAL files read-back tools "
            f"({'/'.join(missing_tools)}) are not exposed; offload has been disabled to "
            "avoid producing responses the LLM cannot read back."
        )
