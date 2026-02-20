from datetime import datetime, timezone
from unittest.mock import Mock

from quickapp.common.completion_result import CompletionResult
from quickapp.common.message_metadata import (
    MESSAGE_METADATA_KEY,
    MessageMetadata,
    TimestampMetadata,
    TimestampSource,
)
from quickapp.common.time_provider import TimeProvider
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher


def _make_enricher(
    source: TimestampSource = TimestampSource.SERVER,
    tz_name: str = "UTC",
) -> _TimestampMetadataEnricher:
    provider = Mock(spec=TimeProvider)
    provider.now.return_value = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    provider.source = source
    provider.tz_name = tz_name
    return _TimestampMetadataEnricher(provider)


def test_enrichment_sets_all_fields_when_absent():
    enricher = _make_enricher()
    result = CompletionResult(content="hello", content_type="text/plain")
    enricher.enrich(result)

    assert result.state is not None
    metadata = MessageMetadata.from_state(result.state)
    assert metadata.timestamp is not None
    assert metadata.timestamp.response_timestamp == datetime(
        2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc
    )
    assert metadata.timestamp.timestamp_source == TimestampSource.SERVER
    assert metadata.timestamp.timezone_name == "UTC"
    assert metadata.content_type == "text/plain"


def test_enrichment_preserves_preset_values():
    enricher = _make_enricher()
    preset_ts = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    preset_metadata = MessageMetadata(
        timestamp=TimestampMetadata(
            response_timestamp=preset_ts,
            timestamp_source=TimestampSource.USER_TIMEZONE,
            timezone_name="Europe/Warsaw",
        ),
        content_type="text/html",
    )
    result = CompletionResult(
        content="hello",
        content_type="text/plain",
        state=preset_metadata.to_state_entry(),
    )
    enricher.enrich(result)

    metadata = MessageMetadata.from_state(result.state)
    assert metadata.timestamp is not None
    assert metadata.timestamp.response_timestamp == preset_ts
    assert metadata.timestamp.timestamp_source == TimestampSource.USER_TIMEZONE
    assert metadata.timestamp.timezone_name == "Europe/Warsaw"
    assert metadata.content_type == "text/html"


def test_enrichment_creates_state_when_none():
    enricher = _make_enricher()
    result = CompletionResult(content="data", content_type="application/json", state=None)
    enricher.enrich(result)

    assert result.state is not None
    assert MESSAGE_METADATA_KEY in result.state
