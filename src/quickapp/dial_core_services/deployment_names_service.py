from aidial_client import AsyncDial
from injector import ProviderOf, inject
from pydantic import BaseModel, TypeAdapter

_DEPLOYMENT_NAMES_PATH = "v1/deployment-names"
# Kinds a configured tool can point at; Core does not enumerate toolsets unless requested.
_REQUESTED_KINDS = "model,application,toolset"


class _DeploymentName(BaseModel):
    id: str


_RESPONSE_ADAPTER: TypeAdapter[list[_DeploymentName]] = TypeAdapter(list[_DeploymentName])


@inject
class DeploymentNamesCoreService:
    """Lists the deployments DIAL Core lets the calling user access (``GET /v1/deployment-names``).

    The SDK has no method for this endpoint, so it goes through the client's HTTP layer; the
    request carries the calling user's credentials via the per-request ``AsyncDial`` client.
    """

    def __init__(self, dial_client_provider: ProviderOf[AsyncDial]):
        self.__dial_client_provider: ProviderOf[AsyncDial] = dial_client_provider

    async def list_names(self) -> list[str]:
        """Return accessible model, application and toolset ids as DIAL Core reports them (may be URL-quoted).

        Raises ``httpx.HTTPError`` on transport or HTTP failure and ``ValueError`` on an
        unexpected response body.
        """
        dial_client = self.__dial_client_provider.get()
        http_client = dial_client.deployments.http_client
        response = await http_client.internal_http_client.get(
            f"{dial_client.base_url}{_DEPLOYMENT_NAMES_PATH}",
            params={"type": _REQUESTED_KINDS},
            headers=await http_client.auth_headers(),
        )
        response.raise_for_status()
        return [item.id for item in _RESPONSE_ADAPTER.validate_python(response.json())]
