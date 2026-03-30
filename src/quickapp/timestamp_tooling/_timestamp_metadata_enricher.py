from quickapp.common.abstract.completion_result_enricher import CompletionResultEnricher
from quickapp.common.completion_result import CompletionResult
from quickapp.common.message_metadata import (
    MessageMetadata,
    TimestampMetadata,
    get_metadata_from_state,
    set_metadata_in_state,
)
from quickapp.common.time_provider import TimeProvider


class _TimestampMetadataEnricher(CompletionResultEnricher):
    """Stamps every tool result with its production timestamp.

    Uses "fill if absent" semantics — if the result already carries
    timestamp metadata (e.g. set by ``_CurrentTimestampTool``), it is
    preserved.
    """

    def __init__(self, time_provider: TimeProvider):
        self.__time_provider = time_provider

    def enrich(self, result: CompletionResult) -> None:
        if result.state is None:
            result.state = {}

        existing = get_metadata_from_state(result.state)
        if existing and existing.timestamp and existing.timestamp.response_timestamp:
            return

        metadata = existing or MessageMetadata()
        metadata.timestamp = TimestampMetadata(
            response_timestamp=self.__time_provider.now(),
            timestamp_source=self.__time_provider.source,
            timezone_name=self.__time_provider.tz_name,
        )
        set_metadata_in_state(result.state, metadata)
