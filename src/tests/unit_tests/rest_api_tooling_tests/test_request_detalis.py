import pytest
from httpx import URL, Headers, QueryParams
# noinspection PyProtectedMember
from quickapp.rest_api_tooling._request_details import _RequestDetails


def test_missing_url_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        _RequestDetails(
            url=None,
            method="GET",
            headers=Headers(),
            params=QueryParams(),
            data={}
        )
    assert str(exc_info.value) == "URL must be set."


def test_missing_method_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        _RequestDetails(
            url=URL("https://example.com"),
            method=None,
            headers=Headers(),
            params=QueryParams(),
            data={}
        )
    assert str(exc_info.value) == "HTTP method must be set."
