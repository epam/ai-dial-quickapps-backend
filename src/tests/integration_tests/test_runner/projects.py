"""Test projects in DIAL Core (v2 project API), shared by the project suites.

A project is created in Chat's layout (``PROJECT.md`` with frontmatter, ``context/``) with a
space in its name: Chat sends the header with the space literal, so this also covers the
header decoding. Requests use the canonical (percent-encoded) form of the project URL.
"""

import uuid

import httpx
from aidial_client.helpers.storage_resource import _percent_encode_relative_url

from quickapp.common.project_context import ProjectContext

MARKER = "PROJECT-MARKER-7Q"
TICKET_CODE = "TCK-8841"
INSTRUCTIONS = f"Always end every answer with the exact token {MARKER} on its own line."
# Chat's PROJECT.md: YAML frontmatter (name, description) + the instructions as the body.
MANIFEST = f"---\nname: qa projects\ndescription: QuickApps projects test\n---\n\n{INSTRUCTIONS}"
TICKETS = f"id,title,priority\n{TICKET_CODE},Login fails after password reset,P1\n"

_PROJECT_FILES = [
    ("file", ("PROJECT.md", MANIFEST.encode(), "text/markdown")),
    ("file", ("context/tickets.csv", TICKETS.encode(), "text/csv")),
]


class ProjectApiUnavailable(Exception):
    """DIAL Core has no v2 project API (an older Core)."""


def user_bucket(core: httpx.Client) -> str:
    return core.get("/v1/bucket").raise_for_status().json()["bucket"]


def create_project(core: httpx.Client, bucket: str) -> ProjectContext:
    """Create a fresh project in ``bucket``; return it (``url`` is canonical).

    Raises ``ProjectApiUnavailable`` when Core doesn't know the v2 project API.
    """
    project = ProjectContext(url=f"projects/{bucket}/qa projects {uuid.uuid4().hex[:8]}")
    response = core.put(f"/v2/{project.url}", files=_PROJECT_FILES)
    if response.status_code in (404, 405, 501):
        raise ProjectApiUnavailable(f"PUT /v2/projects/... returned {response.status_code}")
    response.raise_for_status()
    return project


def delete_project(core: httpx.Client, project: ProjectContext) -> None:
    core.delete(f"/v2/{project.url}")


def header_value(project: ProjectContext) -> str:
    """The ``x-project-id`` value as Chat sends it: percent-decoded spaces (literal)."""
    return project.url.replace("%20", " ")


def read_artifact(core: httpx.Client, project: ProjectContext, name: str) -> httpx.Response:
    return core.get(f"/v2/{project.artifacts_root}{_percent_encode_relative_url(name)}")


def list_artifacts(core: httpx.Client, project: ProjectContext) -> list[str]:
    """URLs of the files directly under the project's ``artifacts/``."""
    response = core.get(f"/v2/metadata/{project.artifacts_root.rstrip('/')}")
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return [item["url"] for item in response.json().get("items") or []]
