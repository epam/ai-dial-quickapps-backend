from datetime import datetime, timedelta
from typing import ClassVar, Literal


class _Pricing:
    CACHE_EXPIRATION_WINDOW: ClassVar[timedelta] = timedelta(hours=1)

    def __init__(
        self,
        input_token_price: float | Literal["-"] = "-",
        output_token_price: float | Literal["-"] = "-",
    ):
        self.input_token_price: float | Literal["-"] = input_token_price
        self.output_token_price: float | Literal["-"] = output_token_price
        self.last_updated: datetime = datetime.now()

    def is_expired(self) -> bool:
        return datetime.now() - self.last_updated > self.CACHE_EXPIRATION_WINDOW
