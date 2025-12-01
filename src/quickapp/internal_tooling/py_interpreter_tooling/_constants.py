from quickapp.common.media_types import MediaTypes

SESSION_ID_KEY = "py_interpreter_session_id"

SUPPORTED_DISPLAY_MEDIA_TYPES = frozenset(
    [
        MediaTypes.PNG,
        MediaTypes.JPEG,
        MediaTypes.PLOTLY,
        MediaTypes.JSON,
        MediaTypes.CSV,
        MediaTypes.XML,
    ]
)
