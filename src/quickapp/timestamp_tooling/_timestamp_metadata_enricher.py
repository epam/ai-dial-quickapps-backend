from quickapp.common.abstract.completion_result_enricher import CompletionResultEnricher
from quickapp.common.completion_result import CompletionResult
from quickapp.common.message_metadata import MessageMetadata
from quickapp.common.time_provider import TimeProvider


class _TimestampMetadataEnricher(CompletionResultEnricher):
    def __init__(self, time_provider: TimeProvider):
        self.__time_provider = time_provider

    def enrich(self, result: CompletionResult) -> None:
        if result.state is None:
            result.state = {}
        existing = MessageMetadata.from_state(result.state)
        if existing.response_timestamp is None:
            existing.response_timestamp = self.__time_provider.now()
        if existing.timestamp_source is None:
            existing.timestamp_source = self.__time_provider.source
        if existing.timezone_name is None:
            existing.timezone_name = self.__time_provider.tz_name
        if existing.content_type is None:
            existing.content_type = result.content_type
        result.state.update(existing.to_state_entry())
