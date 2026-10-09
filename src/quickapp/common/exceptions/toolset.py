class ToolsetNotFoundException(Exception):
    """
    Raised when a referenced toolset cannot be found (HTTP 404).
    """

    status_code = 404

    def __init__(self, toolset_id: str = "", details: str = ""):
        self.toolset_id = toolset_id
        self.details = details
        message = f"Toolset with id {toolset_id} not found" if toolset_id else "Toolset not found"
        super().__init__(message)


class ToolsetForbiddenException(Exception):
    """
    Raised when access to a referenced toolset is forbidden (HTTP 403).
    """

    status_code = 403

    def __init__(self, toolset_id: str = "", details: str = ""):
        self.toolset_id = toolset_id
        self.details = details
        message = (
            f"Access to toolset id {toolset_id} forbidden"
            if toolset_id
            else "Access to toolset forbidden"
        )
        super().__init__(message)
