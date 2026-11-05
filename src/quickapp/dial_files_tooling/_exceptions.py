class DialFilePermissionException(Exception):
    """DIAL Core refused a file operation with 403.

    Not an invalid parameter: another path won't help, because the app lacks the permission
    itself. Goes through the tool's fallback strategies, so the model stops instead of
    retrying other paths.
    """

    def __init__(self, path: str):
        self.path = path
        super().__init__(
            f"access denied: {path}; the app has no permission for it. "
            "Don't retry with other paths."
        )
