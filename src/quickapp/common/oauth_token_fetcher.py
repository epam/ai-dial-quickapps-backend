from authlib.integrations.httpx_client import AsyncOAuth2Client

from quickapp.config.toolsets.rest_api import ClientIdSecretAuthorization


class OAuthTokenFetcher:
    @staticmethod
    async def fetch_oauth_token(auth_info: ClientIdSecretAuthorization) -> str:
        async with AsyncOAuth2Client(
            client_id=auth_info.client_id, client_secret=auth_info.client_secret
        ) as client:
            token = await client.fetch_token(
                url=auth_info.token_url,
                grant_type="client_credentials",
                scope=auth_info.scope,
                audience=auth_info.aud,
                auth=None,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return token.get("access_token")
