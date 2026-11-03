import re

import httpx

from quickapp.common.error_details import extract_error_details, new_error_reference


def test_new_error_reference_is_eight_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{8}", new_error_reference())


def test_non_json_httpx_body_keeps_only_the_status():
    request = httpx.Request("GET", "http://api.example.com/items")
    response = httpx.Response(502, request=request, text="<html>bad gateway</html>")
    error = httpx.HTTPStatusError("502", request=request, response=response)

    details = extract_error_details(error)

    assert details.status_code == 502
    assert details.code is None
    assert details.display_message is None
