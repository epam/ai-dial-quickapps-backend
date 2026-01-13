from typing import Annotated, Optional

from pydantic import SecretStr

DIAL_API_KEY = Annotated[SecretStr, "DIAL_API_KEY"]
DIAL_BEARER = Annotated[Optional[SecretStr], "DIAL_BEARER"]
