from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
    get_metadata_from_state,
    set_metadata_in_state,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher


class TestTimestampMetadataEnricher:
    def test_enriches_result_without_state(self):
        enricher = _TimestampMetadataEnricher(TimeProvider())
        result = ToolCallResult(content="data", content_type="text/plain", state=None)

        enricher.enrich(result)

        assert result.state is not None
        metadata = get_metadata_from_state(result.state)
        assert metadata is not None
        assert metadata.timestamp is not None
        assert metadata.timestamp.response_timestamp is not None
        assert metadata.timestamp.timestamp_source == TimestampSource.DEFAULT
        assert metadata.timestamp.timezone_name == "UTC"

    def test_enriches_result_with_empty_state(self):
        enricher = _TimestampMetadataEnricher(TimeProvider())
        result = ToolCallResult(content="data", content_type="text/plain", state={})

        enricher.enrich(result)

        metadata = get_metadata_from_state(result.state)
        assert metadata is not None
        assert metadata.timestamp is not None

    def test_fill_if_absent_preserves_existing_metadata(self):
        enricher = _TimestampMetadataEnricher(TimeProvider())
        from datetime import datetime, timezone

        existing_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        existing = MessageMetadata(
            timestamp=TimestampMetadata(
                response_timestamp=existing_ts,
                timestamp_source=TimestampSource.REQUEST,
                timezone_name="Asia/Tokyo",
            )
        )
        state: dict = {}
        set_metadata_in_state(state, existing)
        result = ToolCallResult(content="data", content_type="text/plain", state=state)

        enricher.enrich(result)

        metadata = get_metadata_from_state(result.state)
        assert metadata is not None
        assert metadata.timestamp.response_timestamp == existing_ts
        assert metadata.timestamp.timestamp_source == TimestampSource.REQUEST
        assert metadata.timestamp.timezone_name == "Asia/Tokyo"

    def test_enriches_when_metadata_has_no_timestamp(self):
        enricher = _TimestampMetadataEnricher(TimeProvider())
        state: dict = {}
        set_metadata_in_state(state, MessageMetadata())
        result = ToolCallResult(content="data", content_type="text/plain", state=state)

        enricher.enrich(result)

        metadata = get_metadata_from_state(result.state)
        assert metadata is not None
        assert metadata.timestamp is not None
        assert metadata.timestamp.response_timestamp is not None

    def test_uses_correct_timezone(self):
        from zoneinfo import ZoneInfo

        enricher = _TimestampMetadataEnricher(
            TimeProvider(tz=ZoneInfo("US/Eastern"), source=TimestampSource.REQUEST)
        )
        result = ToolCallResult(content="data", content_type="text/plain")

        enricher.enrich(result)

        metadata = get_metadata_from_state(result.state)
        assert metadata.timestamp.timezone_name == "US/Eastern"
        assert metadata.timestamp.timestamp_source == TimestampSource.REQUEST

    def test_state_key_is_correct(self):
        enricher = _TimestampMetadataEnricher(TimeProvider())
        result = ToolCallResult(content="data", content_type="text/plain")

        enricher.enrich(result)

        assert MESSAGE_METADATA_KEY in result.state
