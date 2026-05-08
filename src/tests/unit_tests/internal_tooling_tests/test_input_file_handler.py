from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_sdk.chat_completion import Attachment
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.file_transfer._dial_file_promoter import DialFilePromoter
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)
from quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler import (
    InputFileHandler,
)

DIAL_URL = "https://dial.example.com"


def _make_handler(promoter: MagicMock | None = None) -> InputFileHandler:
    settings = MagicMock(spec=DialSettings)
    settings.url = DIAL_URL
    if promoter is None:
        promoter = MagicMock(spec=DialFilePromoter)
        promoter.promote = AsyncMock()
    return InputFileHandler(promoter=promoter, dial_settings=settings)


def _settings_no_dev_dial() -> MagicMock:
    s = MagicMock(spec=_PyInterpreterSettings)
    s.api_key = None
    s.url = "https://interpreter"
    return s


def _settings_with_dev_dial() -> MagicMock:
    s = MagicMock(spec=_PyInterpreterSettings)
    s.api_key = SecretStr("dev-key")
    s.url = "https://dev-dial.example"
    return s


@pytest.mark.asyncio
async def test_dial_url_passes_through_when_no_dev_dial():
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock()
    handler = _make_handler(promoter=promoter)

    url = await handler.get_attachment_url(
        settings=_settings_no_dev_dial(),
        dial_api_key=SecretStr("k"),
        attachment_url="files/bucket/x.csv",
        attachment=Attachment(type="text/csv", url="files/bucket/x.csv"),
        timeout=10.0,
    )

    assert url == "files/bucket/x.csv"
    promoter.promote.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_url_promoted_then_returned():
    metadata = MagicMock()
    metadata.url = "files/bucket/external.csv"
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock(return_value=metadata)
    handler = _make_handler(promoter=promoter)

    url = await handler.get_attachment_url(
        settings=_settings_no_dev_dial(),
        dial_api_key=SecretStr("k"),
        attachment_url="https://example.com/data.csv",
        attachment=Attachment(type="text/csv", url="https://example.com/data.csv"),
        timeout=10.0,
    )

    assert url == "files/bucket/external.csv"
    promoter.promote.assert_awaited_once_with(
        "https://example.com/data.csv", parameter_name="attachment_urls"
    )


@pytest.mark.asyncio
async def test_unsupported_url_raises():
    handler = _make_handler()
    with pytest.raises(InvalidToolCallParameterException):
        await handler.get_attachment_url(
            settings=_settings_no_dev_dial(),
            dial_api_key=SecretStr("k"),
            attachment_url="ftp://example.com/x",
            attachment=Attachment(type="text/csv", url="ftp://example.com/x"),
            timeout=10.0,
        )


@pytest.mark.asyncio
async def test_dial_url_with_dev_dial_uploads_to_dev():
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock()
    handler = _make_handler(promoter=promoter)

    download_result = MagicMock()
    download_result.aget_content = AsyncMock(return_value=b"csv,data")
    request_dial = MagicMock()
    request_dial.files.download = AsyncMock(return_value=download_result)

    dev_dial = MagicMock()
    bucket_resp = MagicMock(appdata=None, bucket="dev-bucket")
    dev_dial.bucket.get_raw = AsyncMock(return_value=bucket_resp)
    dev_metadata = MagicMock(url="files/dev-bucket/x.csv")
    dev_dial.files.upload = AsyncMock(return_value=dev_metadata)

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler.AsyncDial",
        side_effect=[request_dial, dev_dial],
    ):
        url = await handler.get_attachment_url(
            settings=_settings_with_dev_dial(),
            dial_api_key=SecretStr("host-key"),
            attachment_url="files/bucket/x.csv",
            attachment=Attachment(type="text/csv", url="files/bucket/x.csv"),
            timeout=10.0,
        )

    assert url == "files/dev-bucket/x.csv"
    request_dial.files.download.assert_awaited_once_with("files/bucket/x.csv")
    dev_dial.bucket.get_raw.assert_awaited_once()
    dev_dial.files.upload.assert_awaited_once()
    promoter.promote.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_url_with_dev_dial_promotes_then_uploads_to_dev():
    promoted_metadata = MagicMock(url="files/bucket/promoted.csv")
    promoter = MagicMock(spec=DialFilePromoter)
    promoter.promote = AsyncMock(return_value=promoted_metadata)
    handler = _make_handler(promoter=promoter)

    download_result = MagicMock()
    download_result.aget_content = AsyncMock(return_value=b"data")
    request_dial = MagicMock()
    request_dial.files.download = AsyncMock(return_value=download_result)

    dev_dial = MagicMock()
    dev_dial.bucket.get_raw = AsyncMock(return_value=MagicMock(appdata=None, bucket="dev"))
    dev_dial.files.upload = AsyncMock(return_value=MagicMock(url="files/dev/promoted.csv"))

    with patch(
        "quickapp.internal_tooling.py_interpreter_tooling.handlers.input_file_handler.AsyncDial",
        side_effect=[request_dial, dev_dial],
    ):
        url = await handler.get_attachment_url(
            settings=_settings_with_dev_dial(),
            dial_api_key=SecretStr("host-key"),
            attachment_url="https://example.com/x.csv",
            attachment=Attachment(type="text/csv", url="https://example.com/x.csv"),
            timeout=10.0,
        )

    assert url == "files/dev/promoted.csv"
    promoter.promote.assert_awaited_once_with(
        "https://example.com/x.csv", parameter_name="attachment_urls"
    )
    request_dial.files.download.assert_awaited_once_with("files/bucket/promoted.csv")
