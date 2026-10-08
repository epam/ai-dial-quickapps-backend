class HiddenToolErrorException(Exception):
    """Shown in the stage instead of the real tool error when ``display_error_in_stage`` is off.

    Its text is fixed and safe, so stages render it as-is.
    """

    def __init__(self) -> None:
        super().__init__("An error occurred while executing the tool.")
