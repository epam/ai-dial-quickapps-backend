from typing import Annotated

from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
