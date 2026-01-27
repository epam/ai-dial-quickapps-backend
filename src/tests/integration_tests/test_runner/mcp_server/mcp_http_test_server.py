import base64
import io

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from fastmcp.server.dependencies import get_http_request
from mcp.types import BlobResourceContents, EmbeddedResource
from pydantic import AnyUrl
from starlette.requests import Request
from PIL import Image as PILImage

mcp = FastMCP("TEST_MCP_SERVER")

small_pict = '''data:image/png;base64,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'''


@mcp.tool(name="Image_converter", title="Image converter", description="Convert png image to jpg")
def convert_png_to_jpg(image_data: str):
    """
    Convert PNG image data to JPG format.
    """
    input_bytes = base64.b64decode(image_data)
    # Open the image from bytes
    with PILImage.open(io.BytesIO(input_bytes)) as img:
        # Convert to RGB if necessary (JPG doesn't support transparency)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        # Save as JPG in memory
        output = io.BytesIO()
        img.save(output, format='JPEG')
        jpg_bytes = output.getvalue()

    # Return as Image object with format specified
    base64_str = base64.b64encode(jpg_bytes).decode('utf-8')
    image_resource = EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            blob=base64_str,
            mimeType="image/jpeg",
            uri=AnyUrl("file://test/image.jpg"),
        ),
    )
    return image_resource

@mcp.tool(name="Invert_String")
async def invert_string(incoming: str):
    request: Request = get_http_request()
    headers = request.headers
    print("headers", headers)
    inverted_string = incoming[::-1]
    return {"result": inverted_string}


@mcp.tool(description="Returns string word in the format of list")
async def list_from_word(incoming: str):
    return {"result": list(incoming)}


@mcp.tool(description="Returns sum of the list of integers")
async def sum_integers(incoming: list[int]):
    total_sum = sum(incoming)
    return {"result": total_sum}


@mcp.tool(description="Returns a predefined small picture")
async def get_small_picture() -> Image:
    return Image(path="auto.jpg")


def __get_file_data(file_path: str) -> str:
    with open(file_path, "rb") as file:
        return base64.b64encode(file.read()).decode("utf-8")


def __get_file_raw_data(file_path: str) -> bytes:
    with open(file_path, "rb") as file:
        return file.read()

def __get_file_name(file_url: str) -> str:
    return file_url.split("/")[-1]


@mcp.tool(description="Returns a predefined pdf document")
async def get_test_pdf() -> EmbeddedResource:
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            blob=__get_file_data("mcp_pdf.pdf"),
            uri=AnyUrl("file://test/test.pdf"),
            mimeType="application/pdf",
        ),
    )


@mcp.tool(description="Returns a plotly graph, based on predefined data")
async def get_test_plotly() -> EmbeddedResource:
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(
            blob=__get_file_data("plotly.json"),
            uri=AnyUrl("file://test/plotly.json"),
            mimeType="application/vnd.plotly.v1+json",
        ),
    )


@mcp.resource("resource://greeting")
def get_greeting() -> str:
    """Provides a simple greeting message."""
    return "Hello from FastMCP Resources!"


# Resource returning JSON data (dict is auto-serialized)
@mcp.resource("data://config")
def get_config() -> dict:
    """Provides application configuration as JSON."""
    return {
        "theme": "dark",
        "version": "1.2.0",
        "features": ["tools", "resources"],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003, log_level="debug")
