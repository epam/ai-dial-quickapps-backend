import asyncio

import uvicorn
from fastapi import FastAPI, Request
from test_runner.cache.rest_api_tool_test_mixin import RestApiToolTestMixin
from test_runner.mcp_server.mcp_http_test_server import mcp


class RestTestServer(RestApiToolTestMixin, FastAPI):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register_rest_test_routes()

    def register_rest_test_routes(self):
        @self.post("/test_rest")
        async def post(request: Request):
            return await self.rest_test_post(request)

        @self.get("/test_rest")
        async def get(request: Request):
            return await self.rest_test_get(request)

        @self.put("/test_rest")
        async def put(request: Request):
            return await self.rest_test_put(request)

        @self.delete("/test_rest")
        async def delete(request: Request):
            return await self.rest_test_delete(request)


class DualServerRunner:
    def __init__(self, mcp_port=8003, rest_port=8002):
        self.mcp_port = mcp_port
        self.rest_port = rest_port
        self.rest_app = RestTestServer()

    async def _start_mcp_server(self):
        await mcp.run_async(
            transport="streamable-http",
            host="0.0.0.0",
            port=self.mcp_port,
            log_level="warning",
        )

    async def _start_rest_server(self):
        config = uvicorn.Config(
            self.rest_app,
            host="0.0.0.0",
            port=self.rest_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def run(self):
        # Run MCP and REST servers concurrently
        await asyncio.gather(
            self._start_mcp_server(),
            self._start_rest_server(),
        )


if __name__ == "__main__":
    runner = DualServerRunner()
    asyncio.run(runner.run())
