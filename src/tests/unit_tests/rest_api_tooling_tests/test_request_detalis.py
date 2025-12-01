import unittest
from httpx import URL, Headers, QueryParams
# noinspection PyProtectedMember
from quickapp.rest_api_tooling._request_details import _RequestDetails



class TestRequestDetailsV2(unittest.TestCase):
    def test_missing_url_raises_value_error(self):
        with self.assertRaises(ValueError) as context:
            _RequestDetails(
                url=None,
                method="GET",
                headers=Headers(),
                params=QueryParams(),
                data={}
            )
        self.assertEqual(str(context.exception), "URL must be set.")

    def test_missing_method_raises_value_error(self):
        with self.assertRaises(ValueError) as context:
            _RequestDetails(
                url=URL("https://example.com"),
                method=None,
                headers=Headers(),
                params=QueryParams(),
                data={}
            )
        self.assertEqual(str(context.exception), "HTTP method must be set.")
