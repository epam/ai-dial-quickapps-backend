from aidial_client._exception import DialException


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


class ProjectWriteConflictException(Exception):
    """A conditional project file write kept losing to other writes in the same project.

    Core checks a project file write against the project-wide ETag, which every write to
    the project changes. Raised after the last retry; retrying the tool call right away
    won't help.
    """

    def __init__(self, url: str, attempts: int):
        self.url = url
        self.attempts = attempts
        super().__init__(
            f"Could not write {url}: the project kept changing during {attempts} attempts. "
            "Other writes to the same project are in progress; try again later."
        )


class PartialMoveException(Exception):
    """A move that copied the file but couldn't delete the source: both files now exist."""

    def __init__(self, source_url: str, destination_url: str):
        self.source_url = source_url
        self.destination_url = destination_url
        super().__init__(
            f"Moved {source_url} to {destination_url}, but could not delete the source: "
            "the destination is written and the source still exists."
        )


class FileTooLargeError(ValueError):
    """A file is larger than the configured file-loading size limit."""

    def __init__(self, size: int, limit: int):
        self.size = size
        self.limit = limit
        super().__init__(f"File size {size} exceeds the limit of {limit} bytes.")


class ProjectFileOperationException(DialException):
    """A project file copy/move the service refuses; the message is meant for the agent."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class SameSourceAndDestinationException(ProjectFileOperationException):
    def __init__(self, url: str):
        super().__init__(f"Source and destination are the same: {url}")


class ProjectFileTooLargeException(ProjectFileOperationException):
    def __init__(self, url: str, limit: int):
        super().__init__(
            f"{url} is larger than {limit} bytes; copy/move of large project files is not "
            "supported."
        )
