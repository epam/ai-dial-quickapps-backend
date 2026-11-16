class DialFilePermissionException(Exception):
    """A file operation was refused with 403: by DIAL Core, because the app lacks the
    permission, or by the storage itself, with a reason of its own (``ProjectReadScopeError``).

    Not an invalid parameter: the same path won't work on a retry. Goes through the tool's
    fallback strategies, not the "try to call the tool again" retry path.
    """

    def __init__(self, path: str, reason: str = "the app has no permission for it"):
        self.path = path
        super().__init__(f"access denied: {path}; {reason}.")
