from typing import Any

from httpx import URL, Headers, QueryParams


class _RequestDetails:

    def __init__(
        self,
        url: URL,
        method: str,
        headers: Headers,
        params: QueryParams,
        data: dict[str, Any],
    ):
        if not url:
            raise ValueError("URL must be set.")
        if not method:
            raise ValueError("HTTP method must be set.")

        self.__url: URL = url
        self.__method: str = method
        self.__headers: Headers = headers
        self.__params: QueryParams = params
        self.__data: dict[str, Any] = data

    @property
    def url(self) -> URL:
        return self.__url

    @property
    def method(self) -> str:
        return self.__method

    @property
    def headers(self) -> Headers:
        return self.__headers

    @property
    def params(self) -> QueryParams:
        return self.__params

    @property
    def data(self) -> dict[str, Any]:
        return self.__data
