import json
import logging
from io import BytesIO
from typing import Any

import httpx
from aidial_client.types.deployment import Features
from pydantic import BaseModel, ConfigDict, Field, SecretStr, alias_generators

logger = logging.getLogger(__name__)


class AttachmentResponse(BaseModel):
    name: str = Field(description="The name of the attachment")
    parent_path: str = Field(description="The parent path of the attachment")
    bucket: str = Field(description="The bucket of the attachment")
    url: str = Field(description="The URL of the attachment")
    node_type: str = Field(description="The node type of the attachment")
    resource_type: str = Field(description="The resource type of the attachment")
    updated_at: int | None = Field(
        default=None, description="The updated timestamp in milliseconds"
    )
    content_length: int = Field(description="The content length of the attachment")
    content_type: str = Field(description="The content type of the attachment")

    model_config = ConfigDict(alias_generator=alias_generators.to_camel)


# The model representing actual response on 11/11/2025. The documentation
# https://dialx.ai/dial_api#tag/Deployment-listing/operation/getToolset is outdated.
# might be updated with new version of aidial_client
class ToolsetInfo(BaseModel, extra='allow'):
    id: str
    toolset: str
    display_name: str
    description: str | None = Field(default=None, description="Optional toolset description")
    features: Features
    transport: str = Field(
        description="The transport supported by a specific MCP server. The available options are HTTP or SSE"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="A list of available tools in the MCP server."
    )


class DialCoreClient:
    def __init__(self, api_key: str | SecretStr, base_url: str):
        self.api_key = self._get_api_key(api_key)
        self.base_url = base_url
        self._bucket_id: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={'Api-Key': self._get_api_key(self.api_key)},
        )
        return self

    def _get_api_key(self, api_key: str | SecretStr) -> str:
        if isinstance(api_key, SecretStr):
            return api_key.get_secret_value()
        return api_key

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._client:
            await self._client.aclose()

    async def _get_bucket_json(self) -> dict[str, str]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get('/v1/bucket')
        response.raise_for_status()
        return response.json()

    async def _load_bucket(self) -> str:
        bucket_json = await self._get_bucket_json()
        if "appdata" in bucket_json:
            return bucket_json["appdata"]
        elif "bucket" in bucket_json:
            return bucket_json["bucket"]
        else:
            raise ValueError("No appdata or bucket found")

    async def get_metadata(self, path) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f'/v1/metadata/{path}')
        response.raise_for_status()
        return response.json()

    async def _get_items(self, path):
        response = await self.get_metadata(path + "/")
        return response["items"]

    async def search_file_on_core(self, name):
        bucket = await self.get_bucket()
        sub_folders = ["files/" + bucket]
        for folder in sub_folders:
            items = await self._get_items(folder)
            for item in items:
                if item.get("nodeType") == 'FOLDER':
                    sub_folders.append(f"{folder}/{item['name']}")
                if item['name'] == name:
                    return item['url']
        return None

    async def get_bucket(self, refresh: bool = False) -> str:
        """Get the bucket ID from cache or load it from the API.
        Use `refresh=True` to force loading from the API.
        """

        if self._bucket_id is None or refresh:
            self._bucket_id = await self._load_bucket()

        return self._bucket_id

    async def put_file(
        self, name: str, mime_type: str, content: BytesIO, path: str | None = None
    ) -> dict[str, Any]:
        if not path:
            path = await self.get_bucket()

        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."

        response = await self._client.put(
            f"/v1/files/{path}/{name}",
            files={name: (name, content, mime_type)},
        )
        response.raise_for_status()
        return response.json()

    async def get_file(self, url: str) -> bytes:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/v1/{url}")
        response.raise_for_status()
        return response.content

    async def grant_permissions(self, files, deployment_id: str, perms=None) -> bytes:
        """
        Grant access permissions for a set of files to a recipient.
        Args:
          files: list of file IDs (str)
          deployment_id: the user ID or application ID to grant to
          perms: list of permissions to grant (default: ["read"])
        """
        if perms is None:
            perms = ["read"]
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        payload = {
            "resourcePermissions": [{"url": f, "permissions": perms} for f in files],
            "receiver": deployment_id,
            # "receiver": "curiously-manual",
        }

        logger.debug(
            "Granting permissions to %s; payload:\n%s", deployment_id, json.dumps(payload, indent=2)
        )

        response = await self._client.post(
            "/v1/ops/resource/per-request-permissions/grant", json=payload
        )
        response.raise_for_status()
        return response.content

    async def get_deployment_info(self, deployment: str) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/openai/deployments/{deployment}")
        response.raise_for_status()
        return response.json()

    async def get_toolset_info(self, toolset: str) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/openai/toolsets/{toolset}")
        response.raise_for_status()
        return response.json()

    async def get_application_info(self, deployment: str) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/openai/applications/{deployment}")
        response.raise_for_status()
        return response.json()

    async def get_deployment_config(self, deployment: str) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/v1/deployments/{deployment}/configuration")
        response.raise_for_status()
        return response.json()

    async def get_file_as_json(self, url: str) -> str:
        file = await self.get_file(url)
        to_json = file.decode(encoding='utf8')
        return json.loads(to_json)

    async def get_model_pricing(self, model_name: str) -> dict[str, Any]:
        assert (
            self._client is not None
        ), "HTTP client is not initialized. Use this class within a context manager."
        response = await self._client.get(f"/openai/models/{model_name}")
        response.raise_for_status()
        return response.json()

    async def get_bucket_items(self, bucket: str) -> list[dict]:
        """
        Return list of metadata items under the given bucket/path.
        """
        return await self._get_items(bucket)

    async def upload_bytes(
        self,
        name: str,
        file_bytes: bytes,
        mime_type: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload raw bytes as a file. MIME type defaults to 'application/octet-stream'
        if not provided.
        """
        bio = BytesIO(file_bytes)
        mt = mime_type or "application/octet-stream"
        return await self.put_file(name=name, mime_type=mt, content=bio, path=path)
